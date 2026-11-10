"""
Advanced platform analytics for the admin bot dashboard.

Read-only use cases behind the admin «Деньги» and «Тренеры» tabs, built on raw SQL for
predictable performance on production-sized data:

* :func:`get_admin_money_stats`        — MRR/ARR, GMV trend, revenue, pending invoices, top paying trainers, subscription mix.
* :func:`get_admin_trainers_hub_stats` — who pays, who works, who is silent.

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


# ──────────────────────────────────────────────────────────────────────────
# 🔁 RETENTION
# ──────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────
# 🎯 ENGAGEMENT
# ──────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────
# 👥 CLIENTS
# ──────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────
# 🔬 PRODUCT ANALYTICS — where activation breaks, what predicts payment
# ──────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────
# 👥 TRAINERS HUB — one screen instead of growth / retention / engagement
# ──────────────────────────────────────────────────────────────────────────

async def get_admin_trainers_hub_stats(session: AsyncSession) -> dict:
    """Segments, trial→paid, expiring paid, top by bookings, sleeping payers.

    Trainer population filters use ``status <> 'deactivated'`` — ``status = 'active'`` means
    catalog-published, not working; a paying/trial trainer
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
