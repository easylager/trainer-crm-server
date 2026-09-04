"""
Advanced platform analytics for the admin bot dashboard.

Five focused read-only use cases — one per dashboard tab — built on raw SQL for
predictable performance on production-sized data:

* :func:`get_admin_money_stats`        — MRR/ARR, GMV trend, revenue, pending invoices, top paying trainers, subscription mix.
* :func:`get_admin_growth_stats`       — new trainer cohorts, trial→paid conversion, time-to-first-paid, referral program.
* :func:`get_admin_retention_stats`    — churn rate, expiring subs, sleeping trainers, revival, retention curve.
* :func:`get_admin_engagement_stats`   — DAU/WAU/MAU proxies, feature usage, activity by day-of-week, top active trainers.
* :func:`get_admin_clients_stats`      — client funnel, repeat rate, top cities, top trainers by clients, recent requests.

All money returned in cents (``int``). All percentages returned as floats rounded
to 1 decimal place. All trainer/client/city ids included so the Mini-App can
provide drilldown without extra round-trips.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_client_invite_tracking import (
    sql_trainer_shared_client_invite,
    sql_trainer_submitted_for_moderation,
)
from src.infrastructure.db.models import (
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_TRIAL,
)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _pct(num: float | int | None, den: float | int | None, *, ndigits: int = 1) -> float | None:
    """Safe percentage; returns None when denominator is zero/None."""
    if not den:
        return None
    try:
        return round(100.0 * float(num or 0) / float(den), ndigits)
    except Exception:  # pragma: no cover — defensive
        return None


def _mom_pct(current: int | float | None, previous: int | float | None) -> float | None:
    """Month-over-month growth percentage; ``None`` when previous is zero."""
    if not previous:
        return None
    try:
        return round(100.0 * (float(current or 0) - float(previous)) / float(previous), 1)
    except Exception:  # pragma: no cover
        return None


def _iso(d: datetime | date | None) -> str | None:
    if d is None:
        return None
    if hasattr(d, "isoformat"):
        return d.isoformat()
    return str(d)


def _module_combo_label(modules: dict | None) -> str:
    """Human-readable label for a module combination, e.g. ``"CRM + Группы + Аналитика"``."""
    m = modules or {}
    parts = ["CRM"]
    if m.get("online"):
        parts.append("Онлайн-запись")
    if m.get("groups"):
        parts.append("Группы")
    if m.get("analytics"):
        parts.append("Аналитика")
    if len(parts) == 1:
        return "CRM (только база)"
    return " + ".join(parts)


def _module_combo_key(modules: dict | None) -> str:
    """Deterministic sortable key, ``"o.g.a"`` ordering for stable group-by buckets."""
    m = modules or {}
    return f"{int(bool(m.get('online')))}-{int(bool(m.get('groups')))}-{int(bool(m.get('analytics')))}"


# ──────────────────────────────────────────────────────────────────────────
# 💰 MONEY
# ──────────────────────────────────────────────────────────────────────────

async def get_admin_money_stats(session: AsyncSession) -> dict:
    """Revenue, MRR/ARR, GMV trend, top-paying trainers, pending invoices, subscription mix."""
    today = date.today()

    # 1) MRR — for every currently-active *paid* subscription take the latest paid
    #    invoice that covers the period and normalize to a monthly value.
    mrr_cents = 0
    active_paid_count = 0
    try:
        r = await session.execute(
            text(
                """
                WITH active_paid AS (
                    SELECT id, trainer_id, plan_id, billing_period_months, started_at, expires_at
                    FROM trainer_subscriptions
                    WHERE status = :s_active
                      AND expires_at > CURRENT_TIMESTAMP
                      AND started_at <= CURRENT_TIMESTAMP
                ),
                latest_inv AS (
                    SELECT DISTINCT ON (ap.id)
                        ap.id AS sub_id,
                        inv.amount_cents,
                        COALESCE(
                            NULLIF(inv.checkout_billing_period_months, 0),
                            NULLIF(ap.billing_period_months, 0),
                            1
                        ) AS months
                    FROM active_paid ap
                    JOIN trainer_invoices inv
                      ON inv.trainer_id = ap.trainer_id
                     AND inv.subscription_plan_id = ap.plan_id
                     AND inv.status = 'paid'
                     AND inv.paid_at IS NOT NULL
                     AND inv.paid_at <= ap.started_at + INTERVAL '2 days'
                    ORDER BY ap.id, inv.paid_at DESC
                )
                SELECT
                    COALESCE(SUM(amount_cents::numeric / NULLIF(months, 0)), 0)::bigint AS mrr,
                    COUNT(*) AS sub_count
                FROM latest_inv
                """
            ),
            {"s_active": SUBSCRIPTION_STATUS_ACTIVE},
        )
        row = r.fetchone()
        if row:
            mrr_cents = int(row[0] or 0)
            active_paid_count = int(row[1] or 0)
    except ProgrammingError:
        pass

    arr_cents = mrr_cents * 12

    # 2) Subscription revenue (paid invoices) — last 30 vs previous 30 days.
    revenue_paid_30d_cents = 0
    revenue_paid_prev_30d_cents = 0
    paid_invoices_30d_count = 0
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN paid_at >= CURRENT_TIMESTAMP - INTERVAL '30 days' THEN amount_cents END), 0)::bigint,
                    COALESCE(SUM(CASE WHEN paid_at >= CURRENT_TIMESTAMP - INTERVAL '60 days'
                                       AND paid_at  <  CURRENT_TIMESTAMP - INTERVAL '30 days'
                                       THEN amount_cents END), 0)::bigint,
                    COUNT(*) FILTER (WHERE paid_at >= CURRENT_TIMESTAMP - INTERVAL '30 days')
                FROM trainer_invoices
                WHERE status = 'paid' AND paid_at IS NOT NULL
                """
            )
        )
        row = r.fetchone()
        if row:
            revenue_paid_30d_cents = int(row[0] or 0)
            revenue_paid_prev_30d_cents = int(row[1] or 0)
            paid_invoices_30d_count = int(row[2] or 0)
    except ProgrammingError:
        pass

    revenue_paid_mom_pct = _mom_pct(revenue_paid_30d_cents, revenue_paid_prev_30d_cents)

    # 3) GMV (Gross Merchandise Value flowing through the platform):
    #    completed-booking session price + pass sales + certificate sales.
    async def _gmv_cents(d_start: date, d_end: date) -> int:
        try:
            r2 = await session.execute(
                text(
                    """
                    WITH session_cents AS (
                        SELECT COALESCE(SUM(
                            CASE WHEN pr.booking_id IS NOT NULL THEN 0
                                 ELSE GREATEST(0,
                                    COALESCE(b.booking_price_cents, ts.price_cents, 0)
                                    - COALESCE(cbc.amount_cents, 0)
                                 )
                            END
                        ), 0)::bigint AS amt
                        FROM bookings b
                        JOIN slots s ON s.id = b.slot_id
                        LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
                        LEFT JOIN pass_redemptions pr ON pr.booking_id = b.id
                        LEFT JOIN certificate_booking_credits cbc ON cbc.booking_id = b.id
                        WHERE b.status = 'completed'
                          AND NOT b.is_sandbox -- Onboarding demo never contributes to platform GMV.
                          AND s.slot_date >= :ds AND s.slot_date <= :de
                    ),
                    pass_cents AS (
                        SELECT COALESCE(SUM(pi.price_cents), 0)::bigint AS amt
                        FROM pass_instances pi
                        JOIN trainer_pass_products tpp ON tpp.id = pi.pass_product_id
                        WHERE pi.status != 'cancelled'
                          AND pi.source_certificate_instance_id IS NULL
                          AND DATE((pi.issued_at AT TIME ZONE 'UTC')) >= :ds
                          AND DATE((pi.issued_at AT TIME ZONE 'UTC')) <= :de
                    ),
                    cert_cents AS (
                        SELECT COALESCE(SUM(ci.amount_cents), 0)::bigint AS amt
                        FROM certificate_instances ci
                        WHERE ci.status != 'cancelled'
                          AND DATE((ci.issued_at AT TIME ZONE 'UTC')) >= :ds
                          AND DATE((ci.issued_at AT TIME ZONE 'UTC')) <= :de
                    )
                    SELECT (SELECT amt FROM session_cents) + (SELECT amt FROM pass_cents) + (SELECT amt FROM cert_cents)
                    """
                ),
                {"ds": d_start, "de": d_end},
            )
            return int((r2.scalar() or 0))
        except ProgrammingError:  # pragma: no cover — defensive against missing tables
            return 0

    gmv_30d_cents = await _gmv_cents(today - timedelta(days=29), today)
    gmv_prev_30d_cents = await _gmv_cents(today - timedelta(days=59), today - timedelta(days=30))
    gmv_mom_pct = _mom_pct(gmv_30d_cents, gmv_prev_30d_cents)

    # 4) GMV by month — last 6 calendar months for sparkline.
    gmv_by_month: list[dict] = []
    cursor = today.replace(day=1)
    for _ in range(6):
        start = cursor
        # End of previous month-of-cursor:
        if cursor.month == 12:
            next_first = cursor.replace(year=cursor.year + 1, month=1, day=1)
        else:
            next_first = cursor.replace(month=cursor.month + 1, day=1)
        end = next_first - timedelta(days=1)
        gmv_by_month.append(
            {
                "month": start.isoformat()[:7],  # 'YYYY-MM'
                "gmv_cents": await _gmv_cents(start, end),
            }
        )
        # Move cursor to previous month
        if cursor.month == 1:
            cursor = cursor.replace(year=cursor.year - 1, month=12, day=1)
        else:
            cursor = cursor.replace(month=cursor.month - 1, day=1)
    gmv_by_month.reverse()  # oldest first

    # 5) Subscription tier mix — count active subs grouped by module combination.
    subscription_mix: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT modules, COUNT(*)::int
                FROM trainer_subscriptions
                WHERE status IN (:s1, :s2)
                  AND expires_at > CURRENT_TIMESTAMP
                  AND started_at <= CURRENT_TIMESTAMP
                GROUP BY modules
                """
            ),
            {"s1": SUBSCRIPTION_STATUS_TRIAL, "s2": SUBSCRIPTION_STATUS_ACTIVE},
        )
        buckets: dict[str, dict] = {}
        for modules_json, cnt in r.fetchall():
            key = _module_combo_key(modules_json)
            existing = buckets.get(key)
            if existing is None:
                buckets[key] = {
                    "key": key,
                    "label": _module_combo_label(modules_json),
                    "modules": modules_json or {},
                    "count": int(cnt or 0),
                }
            else:
                existing["count"] += int(cnt or 0)
        subscription_mix = sorted(buckets.values(), key=lambda x: x["count"], reverse=True)
    except ProgrammingError:
        pass

    # 6) Top-10 paying trainers by lifetime paid subscription value.
    top_paying_trainers: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    inv.trainer_id,
                    NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), '') AS name,
                    SUM(inv.amount_cents)::bigint AS lifetime_cents,
                    COUNT(*)::int AS paid_invoices,
                    MAX(inv.paid_at) AS last_paid_at
                FROM trainer_invoices inv
                LEFT JOIN trainer_profiles p ON p.trainer_id = inv.trainer_id
                WHERE inv.status = 'paid'
                GROUP BY inv.trainer_id, p.first_name, p.last_name
                ORDER BY lifetime_cents DESC
                LIMIT 10
                """
            )
        )
        for tid, name, lifetime, cnt, last_paid_at in r.fetchall():
            top_paying_trainers.append(
                {
                    "trainer_id": int(tid),
                    "display_name": (name or f"Тренер #{tid}").strip(),
                    "lifetime_cents": int(lifetime or 0),
                    "paid_invoices": int(cnt or 0),
                    "last_paid_at": _iso(last_paid_at),
                }
            )
    except ProgrammingError:
        pass

    # 7) Pending invoices (cash sitting in the funnel) — sent or draft, not paid yet.
    pending_invoices: list[dict] = []
    pending_total_cents = 0
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    inv.id,
                    inv.trainer_id,
                    NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), '') AS name,
                    inv.amount_cents,
                    inv.status,
                    inv.period_start AS issued_at,
                    inv.due_date,
                    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - inv.period_start))::bigint AS waiting_seconds
                FROM trainer_invoices inv
                LEFT JOIN trainer_profiles p ON p.trainer_id = inv.trainer_id
                WHERE inv.status IN ('sent', 'draft', 'overdue')
                  AND inv.paid_at IS NULL
                ORDER BY inv.period_start ASC
                LIMIT 30
                """
            )
        )
        for iid, tid, name, amount, status, issued_at, due_date, waiting_seconds in r.fetchall():
            waiting_days = int((waiting_seconds or 0) // 86400)
            pending_total_cents += int(amount or 0)
            pending_invoices.append(
                {
                    "invoice_id": int(iid),
                    "trainer_id": int(tid),
                    "display_name": (name or f"Тренер #{tid}").strip(),
                    "amount_cents": int(amount or 0),
                    "status": status,
                    "issued_at": _iso(issued_at),
                    "due_date": _iso(due_date),
                    "waiting_days": waiting_days,
                }
            )
    except ProgrammingError:
        pass

    # 8) Quick aggregates: total paying trainers ever, average paid invoice amount.
    paying_trainers_total = 0
    avg_paid_invoice_cents = 0
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    COUNT(DISTINCT trainer_id),
                    COALESCE(AVG(amount_cents), 0)::bigint
                FROM trainer_invoices
                WHERE status = 'paid'
                """
            )
        )
        row = r.fetchone()
        if row:
            paying_trainers_total = int(row[0] or 0)
            avg_paid_invoice_cents = int(row[1] or 0)
    except ProgrammingError:
        pass

    return {
        "today": today.isoformat(),
        "mrr_cents": mrr_cents,
        "arr_cents": arr_cents,
        "active_paid_subscriptions": active_paid_count,
        "revenue_paid_30d_cents": revenue_paid_30d_cents,
        "revenue_paid_prev_30d_cents": revenue_paid_prev_30d_cents,
        "revenue_paid_mom_pct": revenue_paid_mom_pct,
        "paid_invoices_30d_count": paid_invoices_30d_count,
        "gmv_30d_cents": gmv_30d_cents,
        "gmv_prev_30d_cents": gmv_prev_30d_cents,
        "gmv_mom_pct": gmv_mom_pct,
        "gmv_by_month": gmv_by_month,
        "subscription_mix": subscription_mix,
        "top_paying_trainers": top_paying_trainers,
        "pending_invoices": pending_invoices,
        "pending_invoices_count": len(pending_invoices),
        "pending_invoices_total_cents": pending_total_cents,
        "paying_trainers_total": paying_trainers_total,
        "avg_paid_invoice_cents": avg_paid_invoice_cents,
    }


# ──────────────────────────────────────────────────────────────────────────
# 📈 GROWTH
# ──────────────────────────────────────────────────────────────────────────

async def get_admin_growth_stats(session: AsyncSession) -> dict:
    """New trainer cohorts, trial→paid conversion, time-to-first-paid, referral program."""
    today = date.today()

    # 1) New trainer counts: 7d, 30d, prev-30d, MoM.
    r = await session.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days')   AS d7,
                COUNT(*) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days')  AS d30,
                COUNT(*) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '60 days'
                                  AND created_at <  CURRENT_TIMESTAMP - INTERVAL '30 days')   AS d30_prev
            FROM trainers
            """
        )
    )
    row = r.fetchone() or (0, 0, 0)
    new_trainers_7d = int(row[0] or 0)
    new_trainers_30d = int(row[1] or 0)
    new_trainers_prev_30d = int(row[2] or 0)
    new_trainers_mom_pct = _mom_pct(new_trainers_30d, new_trainers_prev_30d)

    # 2) New trainers by month (last 6 calendar months).
    new_trainers_by_month: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    TO_CHAR(date_trunc('month', created_at), 'YYYY-MM') AS month,
                    COUNT(*)::int
                FROM trainers
                WHERE created_at >= date_trunc('month', CURRENT_DATE) - INTERVAL '5 months'
                GROUP BY month
                ORDER BY month
                """
            )
        )
        seen = {row[0]: row[1] for row in r.fetchall()}
        cursor = today.replace(day=1)
        months_seq = []
        for _ in range(6):
            months_seq.append(cursor.isoformat()[:7])
            if cursor.month == 1:
                cursor = cursor.replace(year=cursor.year - 1, month=12, day=1)
            else:
                cursor = cursor.replace(month=cursor.month - 1, day=1)
        for m in reversed(months_seq):
            new_trainers_by_month.append({"month": m, "count": int(seen.get(m, 0))})
    except ProgrammingError:
        pass

    # 3) Trial→paid conversion: trainers whose first subscription was a trial AND who
    #    later paid an invoice. Last-90d cohort vs previous-90d.
    async def _trial_to_paid(d_start_offset: int, d_end_offset: int) -> tuple[int, int]:
        """Returns (trial_starts_count, paid_after_trial_count) for trials started in [now-d_start, now-d_end]."""
        try:
            r2 = await session.execute(
                text(
                    """
                    WITH first_sub AS (
                        SELECT DISTINCT ON (trainer_id) trainer_id, status, started_at
                        FROM trainer_subscriptions
                        ORDER BY trainer_id, started_at ASC
                    ),
                    cohort AS (
                        SELECT trainer_id FROM first_sub
                        WHERE status = :s_trial
                          AND started_at >= CURRENT_TIMESTAMP - make_interval(days => :d_start)
                          AND started_at <  CURRENT_TIMESTAMP - make_interval(days => :d_end)
                    )
                    SELECT
                        (SELECT COUNT(*) FROM cohort)::int AS trials,
                        (SELECT COUNT(*) FROM cohort c
                         WHERE EXISTS (
                             SELECT 1 FROM trainer_invoices inv
                             WHERE inv.trainer_id = c.trainer_id
                               AND inv.status = 'paid'
                         ))::int AS paid
                    """
                ),
                {"s_trial": SUBSCRIPTION_STATUS_TRIAL, "d_start": d_start_offset, "d_end": d_end_offset},
            )
            row2 = r2.fetchone() or (0, 0)
            return int(row2[0] or 0), int(row2[1] or 0)
        except ProgrammingError:
            return 0, 0

    trial_starts_90d, trial_paid_90d = await _trial_to_paid(90, 0)
    trial_starts_prev_90d, trial_paid_prev_90d = await _trial_to_paid(180, 90)
    trial_to_paid_pct = _pct(trial_paid_90d, trial_starts_90d)
    trial_to_paid_pct_prev = _pct(trial_paid_prev_90d, trial_starts_prev_90d)

    # 4) Time-to-first-paid (median, p90) — for trainers who paid in last 90 days.
    median_days_to_first_paid = None
    p90_days_to_first_paid = None
    try:
        r = await session.execute(
            text(
                """
                WITH first_paid AS (
                    SELECT inv.trainer_id, MIN(inv.paid_at) AS first_paid_at
                    FROM trainer_invoices inv
                    WHERE inv.status = 'paid' AND inv.paid_at IS NOT NULL
                      AND inv.paid_at >= CURRENT_TIMESTAMP - INTERVAL '90 days'
                    GROUP BY inv.trainer_id
                )
                SELECT
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (fp.first_paid_at - t.created_at)) / 86400.0) AS p50,
                    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (fp.first_paid_at - t.created_at)) / 86400.0) AS p90
                FROM first_paid fp
                JOIN trainers t ON t.id = fp.trainer_id
                """
            )
        )
        row = r.fetchone()
        if row and row[0] is not None:
            median_days_to_first_paid = round(float(row[0]), 1)
        if row and row[1] is not None:
            p90_days_to_first_paid = round(float(row[1]), 1)
    except ProgrammingError:
        pass

    # 5) Time-to-first-booking (median).
    median_days_to_first_booking = None
    try:
        r = await session.execute(
            text(
                """
                WITH first_book AS (
                    SELECT trainer_id, MIN(created_at) AS first_booking_at
                    FROM bookings
                    WHERE status NOT IN ('cancelled', 'declined')
                      AND NOT is_sandbox -- Real time-to-first-booking; demo doesn't count.
                    GROUP BY trainer_id
                )
                SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (fb.first_booking_at - t.created_at)) / 86400.0)
                FROM first_book fb
                JOIN trainers t ON t.id = fb.trainer_id
                WHERE t.created_at >= CURRENT_TIMESTAMP - INTERVAL '180 days'
                """
            )
        )
        v = r.scalar()
        if v is not None:
            median_days_to_first_booking = round(float(v), 1)
    except ProgrammingError:
        pass

    # 6) Referral program rollup.
    referral_invites_total = 0
    referral_credited_total = 0
    referral_credit_days_total = 0
    referral_credit_days_30d = 0
    top_referrers: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    (SELECT COUNT(*) FROM trainer_referrals)::int                                            AS invites,
                    (SELECT COUNT(*) FROM trainer_referrals WHERE credit_granted_at IS NOT NULL)::int        AS credited,
                    (SELECT COALESCE(SUM(amount_days), 0) FROM trainer_referral_credits
                       WHERE reason IN (
                         'referral_accrual',
                         'referral_accrual_onboarding',
                         'referral_accrual_first_booking',
                         'referral_accrual_payment'
                       ))::int                                                                                AS days_total,
                    (SELECT COALESCE(SUM(amount_days), 0) FROM trainer_referral_credits
                       WHERE reason IN (
                         'referral_accrual',
                         'referral_accrual_onboarding',
                         'referral_accrual_first_booking',
                         'referral_accrual_payment'
                       )
                         AND created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days')::int                       AS days_30d
                """
            )
        )
        row = r.fetchone()
        if row:
            referral_invites_total = int(row[0] or 0)
            referral_credited_total = int(row[1] or 0)
            referral_credit_days_total = int(row[2] or 0)
            referral_credit_days_30d = int(row[3] or 0)

        r = await session.execute(
            text(
                """
                SELECT
                    tr.referrer_id,
                    NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), '') AS name,
                    COUNT(*)::int                                                                       AS invited,
                    COUNT(*) FILTER (WHERE tr.credit_granted_at IS NOT NULL)::int                       AS credited
                FROM trainer_referrals tr
                LEFT JOIN trainer_profiles p ON p.trainer_id = tr.referrer_id
                GROUP BY tr.referrer_id, p.first_name, p.last_name
                ORDER BY credited DESC, invited DESC
                LIMIT 10
                """
            )
        )
        for tid, name, inv, cred in r.fetchall():
            top_referrers.append(
                {
                    "trainer_id": int(tid),
                    "display_name": (name or f"Тренер #{tid}").strip(),
                    "invited": int(inv or 0),
                    "credited": int(cred or 0),
                }
            )
    except ProgrammingError:
        pass

    # 7) Recent signups (last 20) + signup channel hint (referral / direct).
    recent_signups: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    t.id, t.created_at, t.status,
                    NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), '') AS name,
                    EXISTS(SELECT 1 FROM trainer_referrals tr WHERE tr.referred_id = t.id)               AS is_referred,
                    EXISTS(SELECT 1 FROM bookings b WHERE b.trainer_id = t.id AND b.status NOT IN ('cancelled','declined') AND NOT b.is_sandbox) AS has_booking,
                    EXISTS(SELECT 1 FROM trainer_invoices inv WHERE inv.trainer_id = t.id AND inv.status = 'paid')          AS has_paid
                FROM trainers t
                LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
                ORDER BY t.id DESC
                LIMIT 20
                """
            )
        )
        for tid, created_at, status, name, is_ref, has_book, has_paid in r.fetchall():
            recent_signups.append(
                {
                    "trainer_id": int(tid),
                    "display_name": (name or f"Тренер #{tid}").strip(),
                    "created_at": _iso(created_at),
                    "status": str(status or ""),
                    "channel": "referral" if is_ref else "direct",
                    "has_booking": bool(has_book),
                    "has_paid": bool(has_paid),
                }
            )
    except ProgrammingError:
        pass

    return {
        "today": today.isoformat(),
        "new_trainers_7d": new_trainers_7d,
        "new_trainers_30d": new_trainers_30d,
        "new_trainers_prev_30d": new_trainers_prev_30d,
        "new_trainers_mom_pct": new_trainers_mom_pct,
        "new_trainers_by_month": new_trainers_by_month,
        "trial_starts_90d": trial_starts_90d,
        "trial_paid_90d": trial_paid_90d,
        "trial_to_paid_pct": trial_to_paid_pct,
        "trial_to_paid_pct_prev": trial_to_paid_pct_prev,
        "median_days_to_first_paid": median_days_to_first_paid,
        "p90_days_to_first_paid": p90_days_to_first_paid,
        "median_days_to_first_booking": median_days_to_first_booking,
        "referral_invites_total": referral_invites_total,
        "referral_credited_total": referral_credited_total,
        "referral_credit_days_total": referral_credit_days_total,
        "referral_credit_days_30d": referral_credit_days_30d,
        "top_referrers": top_referrers,
        "recent_signups": recent_signups,
    }


# ──────────────────────────────────────────────────────────────────────────
# 🔁 RETENTION
# ──────────────────────────────────────────────────────────────────────────

async def get_admin_retention_stats(session: AsyncSession) -> dict:
    """Churn rate, expiring subs, sleeping trainers, revival, retention curve by signup cohort.

    All population filters below use ``status <> 'deactivated'``, not ``status = 'active'`` —
    the latter means "listed in the public catalog" (onboarding v2), not "working"; most
    trainers stay ``pending_profile`` for weeks by design, so gating retention/churn on
    catalog status would silently exclude them (see TASK-026, get_admin_product_analytics).
    """
    today = date.today()

    # 1) Churn (subscription level): subs that ended in last 30d AND the trainer has
    #    no overlapping/successor subscription. Denominator: subs active 30d ago.
    churn_count_30d = 0
    base_active_30d_ago = 0
    churn_rate_30d_pct: float | None = None
    churned_trainers: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                WITH expired_30d AS (
                    SELECT id, trainer_id, expires_at
                    FROM trainer_subscriptions
                    WHERE expires_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                      AND expires_at <  CURRENT_TIMESTAMP
                      AND status IN (:s1, :s2)
                ),
                churned AS (
                    SELECT e.trainer_id, MAX(e.expires_at) AS expired_at
                    FROM expired_30d e
                    WHERE NOT EXISTS (
                        SELECT 1 FROM trainer_subscriptions ts2
                        WHERE ts2.trainer_id = e.trainer_id
                          AND ts2.expires_at > CURRENT_TIMESTAMP
                          AND ts2.status IN (:s1, :s2)
                    )
                    GROUP BY e.trainer_id
                )
                SELECT
                    (SELECT COUNT(*)::int FROM churned)                                     AS churn_count,
                    (SELECT COUNT(DISTINCT trainer_id)::int
                       FROM trainer_subscriptions
                       WHERE started_at <= CURRENT_TIMESTAMP - INTERVAL '30 days'
                         AND expires_at >  CURRENT_TIMESTAMP - INTERVAL '30 days'
                         AND status IN (:s1, :s2))                                          AS base_active
                """
            ),
            {"s1": SUBSCRIPTION_STATUS_TRIAL, "s2": SUBSCRIPTION_STATUS_ACTIVE},
        )
        row = r.fetchone()
        if row:
            churn_count_30d = int(row[0] or 0)
            base_active_30d_ago = int(row[1] or 0)
        churn_rate_30d_pct = _pct(churn_count_30d, base_active_30d_ago)

        r = await session.execute(
            text(
                """
                SELECT
                    e.trainer_id,
                    NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), '') AS name,
                    MAX(e.expires_at) AS expired_at
                FROM trainer_subscriptions e
                LEFT JOIN trainer_profiles p ON p.trainer_id = e.trainer_id
                WHERE e.expires_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                  AND e.expires_at <  CURRENT_TIMESTAMP
                  AND e.status IN (:s1, :s2)
                  AND NOT EXISTS (
                    SELECT 1 FROM trainer_subscriptions ts2
                    WHERE ts2.trainer_id = e.trainer_id
                      AND ts2.expires_at > CURRENT_TIMESTAMP
                      AND ts2.status IN (:s1, :s2)
                  )
                GROUP BY e.trainer_id, p.first_name, p.last_name
                ORDER BY expired_at DESC
                LIMIT 30
                """
            ),
            {"s1": SUBSCRIPTION_STATUS_TRIAL, "s2": SUBSCRIPTION_STATUS_ACTIVE},
        )
        for tid, name, expired_at in r.fetchall():
            churned_trainers.append(
                {
                    "trainer_id": int(tid),
                    "display_name": (name or f"Тренер #{tid}").strip(),
                    "expired_at": _iso(expired_at),
                }
            )
    except ProgrammingError:
        pass

    # 2) Expiring soon — counts at 7/14/30 days + a top-30 list with details.
    expiring_7d_count = 0
    expiring_14d_count = 0
    expiring_30d_count = 0
    expiring_soon: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    SUM(CASE WHEN expires_at <= CURRENT_TIMESTAMP + INTERVAL '7 days'  THEN 1 ELSE 0 END)::int,
                    SUM(CASE WHEN expires_at <= CURRENT_TIMESTAMP + INTERVAL '14 days' THEN 1 ELSE 0 END)::int,
                    SUM(CASE WHEN expires_at <= CURRENT_TIMESTAMP + INTERVAL '30 days' THEN 1 ELSE 0 END)::int
                FROM trainer_subscriptions
                WHERE expires_at > CURRENT_TIMESTAMP
                  AND status IN (:s1, :s2)
                """
            ),
            {"s1": SUBSCRIPTION_STATUS_TRIAL, "s2": SUBSCRIPTION_STATUS_ACTIVE},
        )
        row = r.fetchone() or (0, 0, 0)
        expiring_7d_count = int(row[0] or 0)
        expiring_14d_count = int(row[1] or 0)
        expiring_30d_count = int(row[2] or 0)

        r = await session.execute(
            text(
                """
                SELECT
                    ts.trainer_id, ts.status, ts.modules, ts.expires_at,
                    NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), '') AS name,
                    EXTRACT(EPOCH FROM (ts.expires_at - CURRENT_TIMESTAMP))::bigint AS seconds_left
                FROM trainer_subscriptions ts
                LEFT JOIN trainer_profiles p ON p.trainer_id = ts.trainer_id
                WHERE ts.expires_at > CURRENT_TIMESTAMP
                  AND ts.expires_at <= CURRENT_TIMESTAMP + INTERVAL '30 days'
                  AND ts.status IN (:s1, :s2)
                ORDER BY ts.expires_at ASC
                LIMIT 30
                """
            ),
            {"s1": SUBSCRIPTION_STATUS_TRIAL, "s2": SUBSCRIPTION_STATUS_ACTIVE},
        )
        for tid, status, modules_json, expires_at, name, seconds_left in r.fetchall():
            expiring_soon.append(
                {
                    "trainer_id": int(tid),
                    "display_name": (name or f"Тренер #{tid}").strip(),
                    "status": str(status or ""),
                    "label": _module_combo_label(modules_json),
                    "expires_at": _iso(expires_at),
                    "days_left": max(0, int((seconds_left or 0) // 86400)),
                }
            )
    except ProgrammingError:
        pass

    # 3) Sleeping trainers — active status, no booking in last 30/60/90 days.
    sleeping_30_count = 0
    sleeping_60_count = 0
    sleeping_90_count = 0
    sleeping_trainers: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    SUM(CASE WHEN COALESCE(last_book, '1970-01-01'::timestamptz) < CURRENT_TIMESTAMP - INTERVAL '30 days' THEN 1 ELSE 0 END)::int,
                    SUM(CASE WHEN COALESCE(last_book, '1970-01-01'::timestamptz) < CURRENT_TIMESTAMP - INTERVAL '60 days' THEN 1 ELSE 0 END)::int,
                    SUM(CASE WHEN COALESCE(last_book, '1970-01-01'::timestamptz) < CURRENT_TIMESTAMP - INTERVAL '90 days' THEN 1 ELSE 0 END)::int
                FROM (
                    SELECT t.id, (
                        SELECT MAX(b.created_at) FROM bookings b
                        WHERE b.trainer_id = t.id AND b.status NOT IN ('cancelled','declined')
                    ) AS last_book
                    FROM trainers t
                    WHERE t.status <> 'deactivated'
                ) sub
                """
            )
        )
        row = r.fetchone() or (0, 0, 0)
        sleeping_30_count = int(row[0] or 0)
        sleeping_60_count = int(row[1] or 0)
        sleeping_90_count = int(row[2] or 0)

        r = await session.execute(
            text(
                """
                SELECT
                    t.id,
                    NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), '') AS name,
                    (SELECT MAX(b.created_at) FROM bookings b
                     WHERE b.trainer_id = t.id AND b.status NOT IN ('cancelled','declined')) AS last_book,
                    t.created_at
                FROM trainers t
                LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
                WHERE t.status <> 'deactivated'
                  AND COALESCE(
                        (SELECT MAX(b.created_at) FROM bookings b
                         WHERE b.trainer_id = t.id AND b.status NOT IN ('cancelled','declined')),
                        t.created_at
                      ) < CURRENT_TIMESTAMP - INTERVAL '30 days'
                ORDER BY 3 ASC NULLS FIRST, t.created_at ASC
                LIMIT 30
                """
            )
        )
        for tid, name, last_book, created_at in r.fetchall():
            sleeping_trainers.append(
                {
                    "trainer_id": int(tid),
                    "display_name": (name or f"Тренер #{tid}").strip(),
                    "last_booking_at": _iso(last_book),
                    "created_at": _iso(created_at),
                }
            )
    except ProgrammingError:
        pass

    # 4) Revival: trainers who came back (had booking in last 30d after a 30+ day gap before).
    revival_count_30d = 0
    revived_trainers: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                WITH recent AS (
                    SELECT trainer_id, MIN(created_at) AS recent_first
                    FROM bookings
                    WHERE status NOT IN ('cancelled','declined')
                      AND created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                    GROUP BY trainer_id
                ),
                prior AS (
                    SELECT r.trainer_id,
                           (SELECT MAX(b.created_at) FROM bookings b
                            WHERE b.trainer_id = r.trainer_id
                              AND b.status NOT IN ('cancelled','declined')
                              AND b.created_at < r.recent_first) AS last_before
                    FROM recent r
                )
                SELECT
                    p.trainer_id,
                    p.last_before,
                    NULLIF(TRIM(CONCAT(COALESCE(prof.first_name, ''), ' ', COALESCE(prof.last_name, ''))), '') AS name
                FROM prior p
                LEFT JOIN trainer_profiles prof ON prof.trainer_id = p.trainer_id
                WHERE p.last_before IS NOT NULL
                  AND p.last_before < CURRENT_TIMESTAMP - INTERVAL '30 days'
                ORDER BY p.last_before ASC
                LIMIT 30
                """
            )
        )
        for tid, last_before, name in r.fetchall():
            revival_count_30d += 1
            revived_trainers.append(
                {
                    "trainer_id": int(tid),
                    "display_name": (name or f"Тренер #{tid}").strip(),
                    "last_booking_before_revival": _iso(last_before),
                }
            )
    except ProgrammingError:
        pass

    # 5) Retention curve by trainer signup cohort (last 6 months):
    #    of trainers who signed up in month M, what % are still active today?
    cohort_retention: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    TO_CHAR(date_trunc('month', t.created_at), 'YYYY-MM') AS cohort,
                    COUNT(*)::int                                          AS cohort_size,
                    SUM(CASE WHEN t.status <> 'deactivated' THEN 1 ELSE 0 END)::int AS still_active
                FROM trainers t
                WHERE t.created_at >= date_trunc('month', CURRENT_DATE) - INTERVAL '5 months'
                GROUP BY cohort
                ORDER BY cohort
                """
            )
        )
        for cohort, size, active in r.fetchall():
            cohort_retention.append(
                {
                    "cohort_month": cohort,
                    "cohort_size": int(size or 0),
                    "still_active": int(active or 0),
                    "retention_pct": _pct(active, size),
                }
            )
    except ProgrammingError:
        pass

    return {
        "today": today.isoformat(),
        "churn_count_30d": churn_count_30d,
        "base_active_30d_ago": base_active_30d_ago,
        "churn_rate_30d_pct": churn_rate_30d_pct,
        "churned_trainers": churned_trainers,
        "expiring_7d_count": expiring_7d_count,
        "expiring_14d_count": expiring_14d_count,
        "expiring_30d_count": expiring_30d_count,
        "expiring_soon": expiring_soon,
        "sleeping_30_count": sleeping_30_count,
        "sleeping_60_count": sleeping_60_count,
        "sleeping_90_count": sleeping_90_count,
        "sleeping_trainers": sleeping_trainers,
        "revival_count_30d": revival_count_30d,
        "revived_trainers": revived_trainers,
        "cohort_retention": cohort_retention,
    }


# ──────────────────────────────────────────────────────────────────────────
# 🎯 ENGAGEMENT
# ──────────────────────────────────────────────────────────────────────────

async def get_admin_engagement_stats(session: AsyncSession) -> dict:
    """DAU/WAU/MAU proxies (booking activity), feature adoption, top active trainers, day-of-week heat.

    Feature-adoption denominators use ``status <> 'deactivated'`` — ``status = 'active'`` means
    catalog-published, not working (see get_admin_retention_stats).
    """
    today = date.today()

    # 1) Active trainer proxies — distinct trainers with any non-cancelled booking activity.
    dau = wau = mau = 0
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    COUNT(DISTINCT trainer_id) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '1 day')   AS dau,
                    COUNT(DISTINCT trainer_id) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days')  AS wau,
                    COUNT(DISTINCT trainer_id) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days') AS mau
                FROM bookings
                WHERE status NOT IN ('cancelled', 'declined')
                """
            )
        )
        row = r.fetchone() or (0, 0, 0)
        dau, wau, mau = int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)
    except ProgrammingError:
        pass

    # 2) Feature usage among ACTIVE trainers.
    trainers_active = 0
    groups_users = 0
    online_subs = 0
    analytics_subs = 0
    passes_users = 0
    certs_users = 0
    try:
        r = await session.execute(
            text("SELECT COUNT(*)::int FROM trainers WHERE status <> 'deactivated'")
        )
        trainers_active = int(r.scalar() or 0)

        r = await session.execute(
            text(
                """
                SELECT COUNT(DISTINCT tg.trainer_id)::int
                FROM training_groups tg
                JOIN trainers t ON t.id = tg.trainer_id AND t.status <> 'deactivated'
                WHERE tg.status NOT IN ('archived', 'cancelled')
                """
            )
        )
        groups_users = int(r.scalar() or 0)

        r = await session.execute(
            text(
                """
                SELECT
                    COUNT(DISTINCT ts.trainer_id) FILTER (WHERE (ts.modules->>'online')::boolean = true)    AS online,
                    COUNT(DISTINCT ts.trainer_id) FILTER (WHERE (ts.modules->>'analytics')::boolean = true) AS analytics
                FROM trainer_subscriptions ts
                JOIN trainers t ON t.id = ts.trainer_id AND t.status <> 'deactivated'
                WHERE ts.status IN (:s1, :s2)
                  AND ts.expires_at > CURRENT_TIMESTAMP
                """
            ),
            {"s1": SUBSCRIPTION_STATUS_TRIAL, "s2": SUBSCRIPTION_STATUS_ACTIVE},
        )
        row = r.fetchone() or (0, 0)
        online_subs = int(row[0] or 0)
        analytics_subs = int(row[1] or 0)

        r = await session.execute(
            text(
                """
                SELECT COUNT(DISTINCT tpp.trainer_id)::int
                FROM pass_instances pi
                JOIN trainer_pass_products tpp ON tpp.id = pi.pass_product_id
                JOIN trainers t ON t.id = tpp.trainer_id AND t.status <> 'deactivated'
                WHERE pi.status = 'active' AND pi.sessions_remaining > 0
                """
            )
        )
        passes_users = int(r.scalar() or 0)

        r = await session.execute(
            text(
                """
                SELECT COUNT(DISTINCT ci.trainer_id)::int
                FROM certificate_instances ci
                JOIN trainers t ON t.id = ci.trainer_id AND t.status <> 'deactivated'
                WHERE ci.status IN ('issued', 'activated')
                """
            )
        )
        certs_users = int(r.scalar() or 0)
    except ProgrammingError:
        pass

    feature_usage = [
        {"feature": "groups",       "label": "Группы (когорты)",     "users": groups_users,   "share_pct": _pct(groups_users, trainers_active)},
        {"feature": "online",       "label": "Онлайн-запись",         "users": online_subs,    "share_pct": _pct(online_subs, trainers_active)},
        {"feature": "analytics",    "label": "Аналитика",             "users": analytics_subs, "share_pct": _pct(analytics_subs, trainers_active)},
        {"feature": "passes",       "label": "Абонементы (продают)", "users": passes_users,   "share_pct": _pct(passes_users, trainers_active)},
        {"feature": "certificates", "label": "Сертификаты (продают)","users": certs_users,    "share_pct": _pct(certs_users, trainers_active)},
    ]

    # 3) Bookings per active trainer (last 30d) — avg + median.
    avg_bookings_per_active = 0.0
    median_bookings_per_active = 0.0
    try:
        r = await session.execute(
            text(
                """
                WITH per_t AS (
                    SELECT trainer_id, COUNT(*)::int AS cnt
                    FROM bookings
                    WHERE status NOT IN ('cancelled', 'declined')
                      AND created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                    GROUP BY trainer_id
                )
                SELECT
                    COALESCE(AVG(cnt), 0)::numeric                                     AS avg_cnt,
                    COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cnt), 0)::numeric AS median_cnt
                FROM per_t
                """
            )
        )
        row = r.fetchone()
        if row:
            avg_bookings_per_active = round(float(row[0] or 0), 1)
            median_bookings_per_active = round(float(row[1] or 0), 1)
    except ProgrammingError:
        pass

    # 4) Top active trainers (last 30d).
    top_active_trainers: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    b.trainer_id,
                    NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), '') AS name,
                    COUNT(*) FILTER (WHERE b.status = 'completed')::int AS completed,
                    COUNT(*) FILTER (WHERE b.status NOT IN ('cancelled','declined'))::int AS total
                FROM bookings b
                LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
                WHERE b.created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                GROUP BY b.trainer_id, p.first_name, p.last_name
                ORDER BY total DESC
                LIMIT 20
                """
            )
        )
        for tid, name, completed, total in r.fetchall():
            top_active_trainers.append(
                {
                    "trainer_id": int(tid),
                    "display_name": (name or f"Тренер #{tid}").strip(),
                    "completed": int(completed or 0),
                    "total": int(total or 0),
                }
            )
    except ProgrammingError:
        pass

    # 5) Day-of-week heat (completed bookings, last 30d, by slot_date weekday Mon=1..Sun=7).
    dow_labels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    dow_counts = [0] * 7
    try:
        r = await session.execute(
            text(
                """
                SELECT EXTRACT(ISODOW FROM s.slot_date)::int AS dow, COUNT(*)::int
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.status = 'completed'
                  AND s.slot_date >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY dow
                """
            )
        )
        for dow, cnt in r.fetchall():
            i = int(dow or 1) - 1
            if 0 <= i < 7:
                dow_counts[i] = int(cnt or 0)
    except ProgrammingError:
        pass

    return {
        "today": today.isoformat(),
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "trainers_active": trainers_active,
        "wau_share_pct": _pct(wau, trainers_active),
        "mau_share_pct": _pct(mau, trainers_active),
        "avg_bookings_per_active_30d": avg_bookings_per_active,
        "median_bookings_per_active_30d": median_bookings_per_active,
        "feature_usage": feature_usage,
        "top_active_trainers": top_active_trainers,
        "dow_labels": dow_labels,
        "dow_counts": dow_counts,
    }


# ──────────────────────────────────────────────────────────────────────────
# 👥 CLIENTS
# ──────────────────────────────────────────────────────────────────────────

async def get_admin_clients_stats(session: AsyncSession) -> dict:
    """Client funnel: total, active, repeat rate, top cities/trainers, recent client requests."""
    today = date.today()

    # 1) Totals & telegram coverage.
    clients_total = 0
    clients_with_telegram = 0
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE telegram_id IS NOT NULL)::int AS with_tg
                FROM clients
                """
            )
        )
        row = r.fetchone()
        if row:
            clients_total = int(row[0] or 0)
            clients_with_telegram = int(row[1] or 0)
    except ProgrammingError:
        pass

    # 2) Activity windows (any non-cancelled booking in window).
    clients_active_30d = 0
    clients_active_90d = 0
    new_clients_30d = 0
    new_clients_prev_30d = 0
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    COUNT(DISTINCT client_id) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days')::int AS a30,
                    COUNT(DISTINCT client_id) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '90 days')::int AS a90
                FROM bookings
                WHERE status NOT IN ('cancelled', 'declined')
                """
            )
        )
        row = r.fetchone() or (0, 0)
        clients_active_30d = int(row[0] or 0)
        clients_active_90d = int(row[1] or 0)

        r = await session.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days')::int AS d30,
                    COUNT(*) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '60 days'
                                      AND created_at <  CURRENT_TIMESTAMP - INTERVAL '30 days')::int  AS d30_prev
                FROM clients
                """
            )
        )
        row = r.fetchone() or (0, 0)
        new_clients_30d = int(row[0] or 0)
        new_clients_prev_30d = int(row[1] or 0)
    except ProgrammingError:
        pass
    new_clients_mom_pct = _mom_pct(new_clients_30d, new_clients_prev_30d)

    # 3) Repeat-rate: clients with ≥2 confirmed/completed bookings.
    clients_repeat = 0
    avg_bookings_per_client_90d = 0.0
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (WHERE n >= 2)::int          AS repeat_clients,
                    COALESCE(AVG(n), 0)::numeric                 AS avg_bookings
                FROM (
                    SELECT client_id, COUNT(*)::int AS n
                    FROM bookings
                    WHERE status IN ('confirmed', 'completed')
                      AND created_at >= CURRENT_TIMESTAMP - INTERVAL '90 days'
                    GROUP BY client_id
                ) sub
                """
            )
        )
        row = r.fetchone()
        if row:
            clients_repeat = int(row[0] or 0)
            avg_bookings_per_client_90d = round(float(row[1] or 0), 2)
    except ProgrammingError:
        pass
    repeat_rate_pct = _pct(clients_repeat, clients_active_90d)

    # 4) Client request funnel (30d): created → with response → with booking.
    requests_30d = 0
    requests_with_response_30d = 0
    requests_with_booking_30d = 0
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    (SELECT COUNT(*) FROM client_requests
                       WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days')::int                       AS d30,
                    (SELECT COUNT(DISTINCT cr.id) FROM client_requests cr
                       JOIN client_request_responses crr ON crr.client_request_id = cr.id
                       WHERE cr.created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days')::int                    AS resp,
                    (SELECT COUNT(DISTINCT cr.id) FROM client_requests cr
                       JOIN bookings b ON b.client_request_id = cr.id AND b.status NOT IN ('cancelled','declined')
                       WHERE cr.created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days')::int                    AS booked
                """
            )
        )
        row = r.fetchone()
        if row:
            requests_30d = int(row[0] or 0)
            requests_with_response_30d = int(row[1] or 0)
            requests_with_booking_30d = int(row[2] or 0)
    except ProgrammingError:
        pass
    request_response_pct = _pct(requests_with_response_30d, requests_30d)
    request_booking_pct = _pct(requests_with_booking_30d, requests_30d)

    # 5) Top cities by active client count (90d) and bookings (90d).
    top_cities: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    c.id, c.name,
                    COUNT(DISTINCT b.client_id)::int AS active_clients,
                    COUNT(b.*)::int                  AS bookings
                FROM cities c
                LEFT JOIN trainer_profiles tp ON tp.city_id = c.id
                LEFT JOIN bookings b
                       ON b.trainer_id = tp.trainer_id
                      AND b.status NOT IN ('cancelled','declined')
                      AND b.created_at >= CURRENT_TIMESTAMP - INTERVAL '90 days'
                GROUP BY c.id, c.name
                ORDER BY active_clients DESC NULLS LAST, bookings DESC NULLS LAST
                LIMIT 10
                """
            )
        )
        for cid, cname, ac, bk in r.fetchall():
            top_cities.append(
                {
                    "city_id": int(cid),
                    "name": cname or "—",
                    "active_clients": int(ac or 0),
                    "bookings_90d": int(bk or 0),
                }
            )
    except ProgrammingError:
        pass

    # 6) Top trainers by unique clients (90d).
    top_trainers_by_clients: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    b.trainer_id,
                    NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), '') AS name,
                    COUNT(DISTINCT b.client_id)::int                                                      AS clients,
                    COUNT(*) FILTER (WHERE b.status = 'completed')::int                                   AS completed
                FROM bookings b
                LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
                WHERE b.status NOT IN ('cancelled','declined')
                  AND b.created_at >= CURRENT_TIMESTAMP - INTERVAL '90 days'
                GROUP BY b.trainer_id, p.first_name, p.last_name
                ORDER BY clients DESC, completed DESC
                LIMIT 20
                """
            )
        )
        for tid, name, clients, completed in r.fetchall():
            top_trainers_by_clients.append(
                {
                    "trainer_id": int(tid),
                    "display_name": (name or f"Тренер #{tid}").strip(),
                    "clients": int(clients or 0),
                    "completed_90d": int(completed or 0),
                }
            )
    except ProgrammingError:
        pass

    # 7) Recent client requests (last 20).
    recent_requests: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    cr.id, cr.status, cr.created_at, cr.client_id,
                    c.name AS city, s.name AS service,
                    (SELECT COUNT(*) FROM client_request_responses crr WHERE crr.client_request_id = cr.id)::int AS responses
                FROM client_requests cr
                LEFT JOIN cities c   ON c.id = cr.city_id
                LEFT JOIN services s ON s.id = cr.service_id
                ORDER BY cr.id DESC
                LIMIT 20
                """
            )
        )
        for rid, status, created_at, client_id, city, service, responses in r.fetchall():
            recent_requests.append(
                {
                    "request_id": int(rid),
                    "status": str(status or ""),
                    "created_at": _iso(created_at),
                    "client_id": int(client_id or 0),
                    "city": city or "—",
                    "service": service or "—",
                    "responses": int(responses or 0),
                }
            )
    except ProgrammingError:
        pass

    return {
        "today": today.isoformat(),
        "clients_total": clients_total,
        "clients_with_telegram": clients_with_telegram,
        "clients_active_30d": clients_active_30d,
        "clients_active_90d": clients_active_90d,
        "new_clients_30d": new_clients_30d,
        "new_clients_prev_30d": new_clients_prev_30d,
        "new_clients_mom_pct": new_clients_mom_pct,
        "clients_repeat_90d": clients_repeat,
        "repeat_rate_pct": repeat_rate_pct,
        "avg_bookings_per_client_90d": avg_bookings_per_client_90d,
        "requests_30d": requests_30d,
        "requests_with_response_30d": requests_with_response_30d,
        "requests_with_booking_30d": requests_with_booking_30d,
        "request_response_pct": request_response_pct,
        "request_booking_pct": request_booking_pct,
        "top_cities": top_cities,
        "top_trainers_by_clients": top_trainers_by_clients,
        "recent_requests": recent_requests,
    }


# ──────────────────────────────────────────────────────────────────────────
# 🔬 PRODUCT ANALYTICS — where activation breaks, what predicts payment
# ──────────────────────────────────────────────────────────────────────────

async def get_admin_product_analytics(session: AsyncSession) -> dict:
    """
    Founder-grade product analytics. Six focused sections:

    activation_funnel  — step-by-step drop-off from trainer creation to first real booking.
    proof_of_value     — % reaching each value milestone (2nd booking, catalog live, inbound, etc.).
    marketplace        — catalog demand funnel: views → clicks → saves.
    monetization       — trial → paid conversion ladder.
    habit              — weekly active count, avg bookings per active trainer.
    correlation        — THE KEY: paid vs never-paid behavior comparison after 14 days.
                         Biggest delta = strongest monetization predictor.
    """
    today = date.today()

    # ── 1. ACTIVATION FUNNEL ─────────────────────────────────────────────
    _shared_invite = sql_trainer_shared_client_invite()
    _submitted_mod = sql_trainer_submitted_for_moderation()
    activation: dict = {}
    try:
        r = await session.execute(
            text(
                f"""
                SELECT
                    COUNT(*)                                                    AS created,
                    COUNT(*) FILTER (WHERE telegram_id IS NOT NULL)             AS linked_telegram,
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM trainer_schedule_templates tpl
                        WHERE tpl.trainer_id = t.id
                    ))                                                          AS has_template,
                    COUNT(*) FILTER (WHERE {_shared_invite})                    AS copied_invite,
                    COUNT(*) FILTER (WHERE {_submitted_mod})                    AS submitted_moderation,
                    -- «activated» = опубликован в каталоге (status='active'), не «работает» —
                    -- онбординг v2 гейтит каталог, а не инструменты; см. TASK-026.
                    COUNT(*) FILTER (WHERE status = 'active')                   AS activated,
                    COUNT(*) FILTER (
                        WHERE EXISTS (
                            SELECT 1 FROM bookings b
                            WHERE b.trainer_id = t.id
                              AND b.status NOT IN ('cancelled', 'declined')
                              AND COALESCE(b.is_sandbox, false) = false
                        )
                    )                                                           AS has_first_booking
                FROM trainers t
                WHERE status != 'deactivated'
                """
            )
        )
        row = r.fetchone()
        if row:
            created, linked, has_tmpl, copied, submitted, activated, first_booking = row
            activation = {
                "created": int(created or 0),
                "linked_telegram": int(linked or 0),
                "has_template": int(has_tmpl or 0),
                "copied_invite": int(copied or 0),
                "submitted_moderation": int(submitted or 0),
                "activated": int(activated or 0),
                "has_first_booking": int(first_booking or 0),
            }
    except ProgrammingError:
        pass

    # ── 2. PROOF OF VALUE (all working trainers, not only catalog-published) ──
    proof: dict = {}
    try:
        r = await session.execute(
            text(
                f"""
                WITH real_bookings AS (
                    SELECT b.trainer_id, COUNT(*) AS cnt
                    FROM bookings b
                    WHERE b.status NOT IN ('cancelled', 'declined')
                      AND COALESCE(b.is_sandbox, false) = false
                    GROUP BY b.trainer_id
                )
                SELECT
                    COUNT(DISTINCT t.id)                                        AS active_total,
                    COUNT(DISTINCT t.id) FILTER (WHERE rb.cnt >= 1)             AS first_booking,
                    COUNT(DISTINCT t.id) FILTER (WHERE rb.cnt >= 2)             AS second_booking,
                    COUNT(DISTINCT t.id) FILTER (WHERE rb.cnt >= 5)             AS five_bookings,
                    COUNT(DISTINCT t.id) FILTER (WHERE {_shared_invite})        AS invited_client,
                    COUNT(DISTINCT t.id) FILTER (
                        WHERE EXISTS (
                            SELECT 1 FROM trainer_schedule_templates tst
                            WHERE tst.trainer_id = t.id
                        )
                    )                                                           AS has_template,
                    COUNT(DISTINCT t.id) FILTER (
                        WHERE t.is_catalog_visible = true AND EXISTS (
                            SELECT 1 FROM trainer_profiles tp
                            WHERE tp.trainer_id = t.id
                        )
                    )                                                           AS catalog_live,
                    COUNT(DISTINCT t.id) FILTER (
                        WHERE EXISTS (
                            SELECT 1 FROM trainer_demand_events tde
                            WHERE tde.trainer_id = t.id AND tde.kind = 'profile_view'
                        )
                    )                                                           AS got_first_view,
                    COUNT(DISTINCT t.id) FILTER (
                        WHERE EXISTS (
                            SELECT 1 FROM trainer_demand_events tde
                            WHERE tde.trainer_id = t.id AND tde.kind = 'contact_click'
                        )
                    )                                                           AS got_first_click,
                    COUNT(DISTINCT t.id) FILTER (
                        WHERE EXISTS (
                            SELECT 1 FROM trainer_demand_events tde
                            WHERE tde.trainer_id = t.id AND tde.kind = 'catalog_favorite'
                        )
                    )                                                           AS got_first_save
                FROM trainers t
                LEFT JOIN real_bookings rb ON rb.trainer_id = t.id
                -- Работающие, не только опубликованные в каталоге (см. TASK-026) —
                -- иначе весь пробный период тренер не попадает в этот срез вовсе.
                WHERE t.status <> 'deactivated'
                """
            )
        )
        row = r.fetchone()
        if row:
            (
                active_total, first_b, second_b, five_b, invited,
                has_tmpl, catalog, got_view, got_click, got_save,
            ) = row
            n = int(active_total or 0) or None

            def _p(x: object) -> float | None:
                return _pct(x, n)

            proof = {
                "active_total": int(active_total or 0),
                "first_booking": int(first_b or 0),
                "first_booking_pct": _p(first_b),
                "second_booking": int(second_b or 0),
                "second_booking_pct": _p(second_b),
                "five_bookings": int(five_b or 0),
                "five_bookings_pct": _p(five_b),
                "invited_client": int(invited or 0),
                "invited_client_pct": _p(invited),
                "has_template": int(has_tmpl or 0),
                "has_template_pct": _p(has_tmpl),
                "catalog_live": int(catalog or 0),
                "catalog_live_pct": _p(catalog),
                "got_first_view": int(got_view or 0),
                "got_first_view_pct": _p(got_view),
                "got_first_click": int(got_click or 0),
                "got_first_click_pct": _p(got_click),
                "got_first_save": int(got_save or 0),
                "got_first_save_pct": _p(got_save),
            }
    except ProgrammingError:
        pass

    # ── 3. MARKETPLACE (catalog demand funnel) ────────────────────────────
    marketplace: dict = {}
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    COUNT(DISTINCT t.id)                            AS trainers_in_catalog,
                    COALESCE(SUM(de.views), 0)::bigint              AS total_views,
                    COALESCE(SUM(de.clicks), 0)::bigint             AS total_clicks,
                    COALESCE(SUM(de.saves), 0)::bigint              AS total_saves,
                    COUNT(DISTINCT de.tid_view)                     AS trainers_with_views,
                    COUNT(DISTINCT de.tid_click)                    AS trainers_with_clicks,
                    COUNT(DISTINCT de.tid_save)                     AS trainers_with_saves
                FROM trainers t
                JOIN trainer_profiles tp ON tp.trainer_id = t.id
                LEFT JOIN LATERAL (
                    SELECT
                        SUM(CASE WHEN kind = 'profile_view'    THEN 1 ELSE 0 END) AS views,
                        SUM(CASE WHEN kind = 'contact_click'   THEN 1 ELSE 0 END) AS clicks,
                        SUM(CASE WHEN kind = 'catalog_favorite' THEN 1 ELSE 0 END) AS saves,
                        MIN(CASE WHEN kind = 'profile_view'    THEN t.id END) AS tid_view,
                        MIN(CASE WHEN kind = 'contact_click'   THEN t.id END) AS tid_click,
                        MIN(CASE WHEN kind = 'catalog_favorite' THEN t.id END) AS tid_save
                    FROM trainer_demand_events
                    WHERE trainer_id = t.id
                ) de ON true
                WHERE t.is_catalog_visible = true AND t.status = 'active'
                """
            )
        )
        row = r.fetchone()
        if row:
            (in_cat, tot_v, tot_c, tot_s, tr_v, tr_c, tr_s) = row
            marketplace = {
                "trainers_in_catalog": int(in_cat or 0),
                "total_views": int(tot_v or 0),
                "total_clicks": int(tot_c or 0),
                "total_saves": int(tot_s or 0),
                "trainers_with_views": int(tr_v or 0),
                "trainers_with_clicks": int(tr_c or 0),
                "trainers_with_saves": int(tr_s or 0),
                "view_to_click_pct": _pct(tot_c, tot_v),
                "click_to_save_pct": _pct(tot_s, tot_c),
            }
    except ProgrammingError:
        pass

    # ── 4. MONETIZATION FUNNEL ────────────────────────────────────────────
    monetization: dict = {}
    try:
        r = await session.execute(
            text(
                """
                WITH first_sub AS (
                    SELECT DISTINCT ON (trainer_id)
                        trainer_id, status, expires_at, started_at
                    FROM trainer_subscriptions
                    ORDER BY trainer_id, started_at ASC
                ),
                paid_trainers AS (
                    SELECT DISTINCT trainer_id
                    FROM trainer_invoices
                    WHERE status = 'paid'
                )
                SELECT
                    COUNT(DISTINCT fs.trainer_id)                                        AS trial_started,
                    COUNT(DISTINCT fs.trainer_id) FILTER (
                        WHERE fs.status = :s_trial AND fs.expires_at > NOW()
                    )                                                                    AS trial_active,
                    COUNT(DISTINCT fs.trainer_id) FILTER (
                        WHERE fs.expires_at <= NOW()
                        AND NOT EXISTS (
                            SELECT 1 FROM trainer_subscriptions ts2
                            WHERE ts2.trainer_id = fs.trainer_id
                              AND ts2.status = :s_active
                        )
                    )                                                                    AS trial_expired_no_paid,
                    COUNT(DISTINCT pt.trainer_id)                                        AS paid_at_least_once,
                    COUNT(DISTINCT fs.trainer_id) FILTER (
                        WHERE fs.expires_at <= NOW() - INTERVAL '30 days'
                          AND pt.trainer_id IS NULL
                    )                                                                    AS trial_expired_30d_churned
                FROM first_sub fs
                LEFT JOIN paid_trainers pt ON pt.trainer_id = fs.trainer_id
                """
            ),
            {"s_trial": SUBSCRIPTION_STATUS_TRIAL, "s_active": SUBSCRIPTION_STATUS_ACTIVE},
        )
        row = r.fetchone()
        if row:
            (t_start, t_active, t_expired_no_paid, paid, t_expired_30d_churned) = row
            monetization = {
                "trial_started": int(t_start or 0),
                "trial_active": int(t_active or 0),
                "trial_expired_no_paid": int(t_expired_no_paid or 0),
                "trial_to_paid_pct": _pct(paid, t_start),
                "paid_at_least_once": int(paid or 0),
                "trial_expired_30d_churned": int(t_expired_30d_churned or 0),
                "churn_30d_pct": _pct(t_expired_30d_churned, t_start),
            }
    except ProgrammingError:
        pass

    # ── 5. HABIT PROXY ────────────────────────────────────────────────────
    habit: dict = {}
    try:
        r = await session.execute(
            text(
                """
                WITH week_active AS (
                    SELECT DISTINCT b.trainer_id
                    FROM bookings b
                    JOIN slots s ON s.id = b.slot_id
                    WHERE b.status NOT IN ('cancelled', 'declined')
                      AND COALESCE(b.is_sandbox, false) = false
                      AND s.slot_date >= CURRENT_DATE - 7
                ),
                -- Working trainers, not only catalog-published (see get_admin_retention_stats).
                all_active AS (
                    SELECT t.id AS trainer_id
                    FROM trainers t
                    WHERE t.status <> 'deactivated'
                ),
                booking_counts AS (
                    SELECT b.trainer_id, COUNT(*) AS cnt
                    FROM bookings b
                    WHERE b.status NOT IN ('cancelled', 'declined')
                      AND COALESCE(b.is_sandbox, false) = false
                    GROUP BY b.trainer_id
                ),
                -- trainers who had first booking in past 30 days
                recent_activated AS (
                    SELECT b.trainer_id,
                           MIN(s.slot_date) AS first_date
                    FROM bookings b
                    JOIN slots s ON s.id = b.slot_id
                    WHERE b.status NOT IN ('cancelled', 'declined')
                      AND COALESCE(b.is_sandbox, false) = false
                    GROUP BY b.trainer_id
                    HAVING MIN(s.slot_date) >= CURRENT_DATE - 30
                )
                SELECT
                    COUNT(DISTINCT aa.trainer_id)   AS active_total,
                    COUNT(DISTINCT wa.trainer_id)   AS weekly_active,
                    ROUND(AVG(bc.cnt)::numeric, 1)  AS avg_bookings_per_trainer,
                    COUNT(DISTINCT ra.trainer_id)   AS recently_activated_30d
                FROM all_active aa
                LEFT JOIN week_active wa ON wa.trainer_id = aa.trainer_id
                LEFT JOIN booking_counts bc ON bc.trainer_id = aa.trainer_id
                LEFT JOIN recent_activated ra ON ra.trainer_id = aa.trainer_id
                """
            )
        )
        row = r.fetchone()
        if row:
            (act_total, wkly, avg_b, rec_act) = row
            habit = {
                "active_total": int(act_total or 0),
                "weekly_active": int(wkly or 0),
                "weekly_active_pct": _pct(wkly, act_total),
                "avg_bookings_per_trainer": float(avg_b or 0),
                "recently_activated_30d": int(rec_act or 0),
            }
    except ProgrammingError:
        pass

    # ── 6. CORRELATION TABLE — paid vs not-paid (cohort: active ≥14 days) ─
    # THE MOST IMPORTANT SECTION: what behaviors actually predict payment?
    correlation: list[dict] = []
    try:
        r = await session.execute(
            text(
                f"""
                WITH eligible AS (
                    SELECT
                        t.id,
                        {_shared_invite}                                            AS invited_client,
                        t.is_catalog_visible AND EXISTS (
                            SELECT 1 FROM trainer_profiles tp WHERE tp.trainer_id = t.id
                        )                                                           AS catalog_live,
                        EXISTS (
                            SELECT 1 FROM trainer_invoices i
                            WHERE i.trainer_id = t.id AND i.status = 'paid'
                        )                                                           AS is_paid,
                        EXISTS (
                            SELECT 1 FROM trainer_schedule_templates tst
                            WHERE tst.trainer_id = t.id
                        )                                                           AS has_template,
                        (
                            SELECT COUNT(*)
                            FROM bookings b
                            WHERE b.trainer_id = t.id
                              AND b.status NOT IN ('cancelled', 'declined')
                              AND COALESCE(b.is_sandbox, false) = false
                        )                                                           AS booking_count,
                        EXISTS (
                            SELECT 1 FROM trainer_demand_events tde
                            WHERE tde.trainer_id = t.id AND tde.kind = 'profile_view'
                        )                                                           AS got_view,
                        EXISTS (
                            SELECT 1 FROM trainer_demand_events tde
                            WHERE tde.trainer_id = t.id AND tde.kind = 'contact_click'
                        )                                                           AS got_inbound_click,
                        EXISTS (
                            SELECT 1 FROM trainer_demand_events tde
                            WHERE tde.trainer_id = t.id AND tde.kind = 'catalog_favorite'
                        )                                                           AS got_save
                    FROM trainers t
                    -- Working trainers, not only catalog-published (see get_admin_retention_stats).
                    WHERE t.status <> 'deactivated'
                      AND t.created_at < NOW() - INTERVAL '14 days'
                )
                SELECT
                    is_paid,
                    COUNT(*)                                                        AS cohort_size,
                    ROUND(AVG(booking_count::numeric), 1)                          AS avg_bookings,
                    COUNT(*) FILTER (WHERE booking_count >= 1)                     AS cnt_first_booking,
                    COUNT(*) FILTER (WHERE booking_count >= 2)                     AS cnt_second_booking,
                    COUNT(*) FILTER (WHERE booking_count >= 5)                     AS cnt_five_bookings,
                    COUNT(*) FILTER (WHERE has_template)                           AS cnt_has_template,
                    COUNT(*) FILTER (WHERE invited_client)                         AS cnt_invited_client,
                    COUNT(*) FILTER (WHERE catalog_live)                           AS cnt_catalog_live,
                    COUNT(*) FILTER (WHERE got_view)                               AS cnt_got_view,
                    COUNT(*) FILTER (WHERE got_inbound_click)                      AS cnt_got_click,
                    COUNT(*) FILTER (WHERE got_save)                               AS cnt_got_save
                FROM eligible
                GROUP BY is_paid
                ORDER BY is_paid DESC
                """
            )
        )
        for row in r.fetchall():
            (
                is_paid, cohort_size, avg_b,
                cnt_fb, cnt_sb, cnt_5b, cnt_tmpl, cnt_inv, cnt_cat,
                cnt_view, cnt_click, cnt_save,
            ) = row
            n = int(cohort_size or 0) or None

            def _pp(x: object) -> float | None:
                return _pct(x, n)

            correlation.append(
                {
                    "is_paid": bool(is_paid),
                    "cohort_size": int(cohort_size or 0),
                    "avg_bookings": float(avg_b or 0),
                    "pct_first_booking": _pp(cnt_fb),
                    "pct_second_booking": _pp(cnt_sb),
                    "pct_five_bookings": _pp(cnt_5b),
                    "pct_has_template": _pp(cnt_tmpl),
                    "pct_invited_client": _pp(cnt_inv),
                    "pct_catalog_live": _pp(cnt_cat),
                    "pct_got_view": _pp(cnt_view),
                    "pct_got_click": _pp(cnt_click),
                    "pct_got_save": _pp(cnt_save),
                }
            )
    except ProgrammingError:
        pass

    hint_funnel, feature_adoption = await _get_hint_funnel_and_feature_adoption(session)

    return {
        "today": today.isoformat(),
        "activation_funnel": activation,
        "proof_of_value": proof,
        "marketplace": marketplace,
        "monetization": monetization,
        "habit": habit,
        "correlation": correlation,
        "hint_funnel": hint_funnel,
        "feature_adoption": feature_adoption,
    }


_HINT_FUNNEL_WINDOW_DAYS = 30
_FEATURE_ADOPTION_DAY_MARKS = (7, 14)


async def _get_hint_funnel_and_feature_adoption(
    session: AsyncSession,
) -> tuple[list[dict], dict]:
    """
    TASK-028: (a) per-hint shown/clicked/dismissed over the last 30 days, from the guidance
    telemetry written by ``POST /trainer/hub/inbox-event``; (b) how many of the 11 tracked
    features a trainer has touched by day 7 / day 14 of their lifetime, from
    ``trainer_feature_first_use``. Both read-only, no side effects.
    """
    hint_funnel: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                WITH events AS (
                    SELECT
                        payload->>'item_id' AS item_id,
                        CASE
                            WHEN event_type IN ('trainer.hub.inbox_item_shown', 'trainer.hub.next_step_shown')
                                THEN 'shown'
                            WHEN event_type IN ('trainer.hub.hint_clicked', 'trainer.hub.next_step_clicked')
                                THEN 'clicked'
                            WHEN event_type IN ('trainer.hub.hint_dismissed', 'trainer.hub.next_step_dismissed')
                                THEN 'dismissed'
                        END AS action
                    FROM platform_audit_events
                    WHERE event_type IN (
                        'trainer.hub.inbox_item_shown', 'trainer.hub.hint_clicked', 'trainer.hub.hint_dismissed',
                        'trainer.hub.next_step_shown', 'trainer.hub.next_step_clicked', 'trainer.hub.next_step_dismissed'
                    )
                    AND occurred_at >= now() - make_interval(days => :window_days)
                    AND payload->>'item_id' IS NOT NULL
                )
                SELECT
                    item_id,
                    COUNT(*) FILTER (WHERE action = 'shown')::int AS shown,
                    COUNT(*) FILTER (WHERE action = 'clicked')::int AS clicked,
                    COUNT(*) FILTER (WHERE action = 'dismissed')::int AS dismissed
                FROM events
                GROUP BY item_id
                ORDER BY shown DESC, item_id
                """
            ),
            {"window_days": _HINT_FUNNEL_WINDOW_DAYS},
        )
        hint_funnel = [
            {
                "item_id": row[0],
                "shown": int(row[1] or 0),
                "clicked": int(row[2] or 0),
                "dismissed": int(row[3] or 0),
            }
            for row in r.fetchall()
        ]
    except ProgrammingError:
        pass

    feature_adoption: dict[str, list[dict] | int] = {}
    for day_mark in _FEATURE_ADOPTION_DAY_MARKS:
        rows: list[dict] = []
        try:
            r = await session.execute(
                text(
                    """
                    WITH eligible AS (
                        SELECT id, created_at FROM trainers
                        WHERE created_at <= now() - make_interval(days => :day_mark)
                    ),
                    touched AS (
                        SELECT e.id AS trainer_id, COUNT(f.feature)::int AS n
                        FROM eligible e
                        LEFT JOIN trainer_feature_first_use f
                            ON f.trainer_id = e.id
                           AND f.first_used_at <= e.created_at + make_interval(days => :day_mark)
                        GROUP BY e.id
                    )
                    SELECT n, COUNT(*)::int FROM touched GROUP BY n ORDER BY n
                    """
                ),
                {"day_mark": day_mark},
            )
            rows = [{"features_touched": int(row[0]), "trainers": int(row[1])} for row in r.fetchall()]
        except ProgrammingError:
            pass
        feature_adoption[f"day{day_mark}"] = rows

    from src.application.trainer_feature_tracking import FEATURE_KEYS

    feature_adoption["total_features"] = len(FEATURE_KEYS)

    return hint_funnel, feature_adoption


# ──────────────────────────────────────────────────────────────────────────
# 👥 TRAINERS HUB — one screen instead of growth / retention / engagement
# ──────────────────────────────────────────────────────────────────────────

async def get_admin_trainers_hub_stats(session: AsyncSession) -> dict:
    """Segments, trial→paid, expiring paid, top by bookings, sleeping payers.

    Trainer population filters use ``status <> 'deactivated'`` — ``status = 'active'`` means
    catalog-published, not working (see get_admin_retention_stats); a paying/trial trainer
    stuck in ``pending_profile`` must still count here.
    """
    paying = 0
    trial = 0
    live_7d = 0
    sleeping_paid = 0
    onboarding = 0
    ghosts = 0
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    COUNT(DISTINCT ts.trainer_id) FILTER (WHERE ts.status = :s_active)::int AS paying,
                    COUNT(DISTINCT ts.trainer_id) FILTER (WHERE ts.status = :s_trial)::int AS trial
                FROM trainer_subscriptions ts
                JOIN trainers t ON t.id = ts.trainer_id AND t.status <> 'deactivated'
                WHERE ts.expires_at > CURRENT_TIMESTAMP
                  AND ts.started_at <= CURRENT_TIMESTAMP
                """
            ),
            {"s_active": SUBSCRIPTION_STATUS_ACTIVE, "s_trial": SUBSCRIPTION_STATUS_TRIAL},
        )
        row = r.fetchone() or (0, 0)
        paying = int(row[0] or 0)
        trial = int(row[1] or 0)
    except ProgrammingError:
        pass

    r = await session.execute(
        text(
            """
            SELECT COUNT(DISTINCT b.trainer_id)::int
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN trainers t ON t.id = b.trainer_id AND t.status <> 'deactivated'
            WHERE b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
              AND NOT b.is_sandbox
              AND s.slot_date >= CURRENT_DATE - INTERVAL '6 days'
              AND s.slot_date <= CURRENT_DATE
            """
        ),
    )
    live_7d = int((r.scalar() or 0) or 0)

    try:
        r = await session.execute(
            text(
                """
                SELECT COUNT(DISTINCT t.id)::int
                FROM trainers t
                JOIN trainer_subscriptions ts
                  ON ts.trainer_id = t.id
                 AND ts.status = :s_active
                 AND ts.expires_at > CURRENT_TIMESTAMP
                WHERE t.status <> 'deactivated'
                  AND NOT EXISTS (
                    SELECT 1 FROM bookings b
                    JOIN slots s ON s.id = b.slot_id
                    WHERE b.trainer_id = t.id
                      AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                      AND NOT b.is_sandbox
                      AND s.slot_date >= CURRENT_DATE - INTERVAL '14 days'
                  )
                """
            ),
            {"s_active": SUBSCRIPTION_STATUS_ACTIVE},
        )
        sleeping_paid = int((r.scalar() or 0) or 0)
    except ProgrammingError:
        pass

    r = await session.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE telegram_id IS NOT NULL)::int AS onboarding,
                COUNT(*) FILTER (
                    WHERE telegram_id IS NULL
                      AND moderation_submitted_at IS NULL
                )::int AS ghosts
            FROM trainers
            WHERE status = 'pending_profile'
            """
        ),
    )
    row = r.fetchone() or (0, 0)
    onboarding = int(row[0] or 0)
    ghosts = int(row[1] or 0)

    trial_starts_90d = 0
    trial_paid_90d = 0
    try:
        r = await session.execute(
            text(
                """
                WITH first_sub AS (
                    SELECT DISTINCT ON (trainer_id) trainer_id, status, started_at
                    FROM trainer_subscriptions
                    ORDER BY trainer_id, started_at ASC
                ),
                cohort AS (
                    SELECT trainer_id FROM first_sub
                    WHERE status = :s_trial
                      AND started_at >= CURRENT_TIMESTAMP - INTERVAL '90 days'
                )
                SELECT
                    (SELECT COUNT(*) FROM cohort)::int,
                    (SELECT COUNT(*) FROM cohort c
                     WHERE EXISTS (
                         SELECT 1 FROM trainer_invoices inv
                         WHERE inv.trainer_id = c.trainer_id AND inv.status = 'paid'
                     ))::int
                """
            ),
            {"s_trial": SUBSCRIPTION_STATUS_TRIAL},
        )
        row = r.fetchone() or (0, 0)
        trial_starts_90d = int(row[0] or 0)
        trial_paid_90d = int(row[1] or 0)
    except ProgrammingError:
        pass

    expiring_paid: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT DISTINCT ON (ts.trainer_id)
                    ts.trainer_id,
                    NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), '') AS name,
                    ts.expires_at,
                    EXTRACT(EPOCH FROM (ts.expires_at - CURRENT_TIMESTAMP))::bigint AS seconds_left
                FROM trainer_subscriptions ts
                LEFT JOIN trainer_profiles p ON p.trainer_id = ts.trainer_id
                WHERE ts.status = :s_active
                  AND ts.expires_at > CURRENT_TIMESTAMP
                  AND ts.expires_at <= CURRENT_TIMESTAMP + INTERVAL '14 days'
                ORDER BY ts.trainer_id, ts.expires_at ASC
                """
            ),
            {"s_active": SUBSCRIPTION_STATUS_ACTIVE},
        )
        rows = sorted(r.fetchall(), key=lambda x: x[2])
        for tid, name, expires_at, seconds_left in rows[:20]:
            expiring_paid.append(
                {
                    "trainer_id": int(tid),
                    "display_name": (name or f"Тренер #{tid}").strip(),
                    "expires_at": _iso(expires_at),
                    "days_left": max(0, int((seconds_left or 0) // 86400)),
                }
            )
    except ProgrammingError:
        pass

    top_by_bookings: list[dict] = []
    r = await session.execute(
        text(
            """
            SELECT
                b.trainer_id,
                NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), '') AS name,
                COUNT(*) FILTER (
                    WHERE s.slot_date >= CURRENT_DATE - INTERVAL '6 days'
                      AND s.slot_date <= CURRENT_DATE
                )::int AS bookings_7d,
                COUNT(*) FILTER (
                    WHERE s.slot_date >= CURRENT_DATE - INTERVAL '29 days'
                      AND s.slot_date <= CURRENT_DATE
                )::int AS bookings_30d,
                MAX(s.slot_date) AS last_slot
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
            WHERE b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
              AND NOT b.is_sandbox
              AND s.slot_date >= CURRENT_DATE - INTERVAL '29 days'
            GROUP BY b.trainer_id, p.first_name, p.last_name
            ORDER BY bookings_7d DESC, bookings_30d DESC
            LIMIT 20
            """
        ),
    )
    for tid, name, b7, b30, last_slot in r.fetchall():
        top_by_bookings.append(
            {
                "trainer_id": int(tid),
                "display_name": (name or f"Тренер #{tid}").strip(),
                "bookings_7d": int(b7 or 0),
                "bookings_30d": int(b30 or 0),
                "last_booking_date": last_slot.isoformat() if last_slot else None,
            }
        )

    sleeping_paid_list: list[dict] = []
    try:
        r = await session.execute(
            text(
                """
                SELECT
                    t.id,
                    NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), '') AS name,
                    lb.last_slot
                FROM trainers t
                JOIN trainer_subscriptions ts
                  ON ts.trainer_id = t.id
                 AND ts.status = :s_active
                 AND ts.expires_at > CURRENT_TIMESTAMP
                LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
                LEFT JOIN LATERAL (
                    SELECT MAX(s.slot_date) AS last_slot
                    FROM bookings b
                    JOIN slots s ON s.id = b.slot_id
                    WHERE b.trainer_id = t.id
                      AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                      AND NOT b.is_sandbox
                ) lb ON true
                WHERE t.status <> 'deactivated'
                  AND (lb.last_slot IS NULL OR lb.last_slot < CURRENT_DATE - INTERVAL '14 days')
                ORDER BY lb.last_slot ASC NULLS FIRST, t.id
                LIMIT 20
                """
            ),
            {"s_active": SUBSCRIPTION_STATUS_ACTIVE},
        )
        today = date.today()
        for tid, name, last_slot in r.fetchall():
            sleeping_paid_list.append(
                {
                    "trainer_id": int(tid),
                    "display_name": (name or f"Тренер #{tid}").strip(),
                    "last_booking_date": last_slot.isoformat() if last_slot else None,
                    "days_since": (today - last_slot).days if last_slot else None,
                }
            )
    except ProgrammingError:
        pass

    return {
        "today": date.today().isoformat(),
        "paying_count": paying,
        "trial_count": trial,
        "live_7d_count": live_7d,
        "sleeping_paid_count": sleeping_paid,
        "onboarding_count": onboarding,
        "ghost_count": ghosts,
        "trial_starts_90d": trial_starts_90d,
        "trial_paid_90d": trial_paid_90d,
        "trial_to_paid_pct": _pct(trial_paid_90d, trial_starts_90d),
        "expiring_paid": expiring_paid,
        "top_by_bookings": top_by_bookings,
        "sleeping_paid": sleeping_paid_list,
    }
