"""
Stats for trainers (subscription value) and platform (admin).
Read-only aggregates; no side effects.
"""
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_schedule_use_cases import this_week_monday

# Short day names for charts (Mon–Sun)
STATS_DAY_NAMES = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _month_end(d: date) -> date:
    if d.month == 12:
        return d.replace(day=31)
    return (d.replace(month=d.month + 1, day=1)) - timedelta(days=1)


async def get_trainer_stats(session: AsyncSession, trainer_id: int) -> dict:
    """
    Aggregates for trainer dashboard: week/month bookings, load, new clients, rating.
    Periods: this week (Mon–Sun), this month, last 30 days for new clients.
    """
    today = date.today()
    week_start = this_week_monday()
    week_end = week_start + timedelta(days=6)
    month_start = _month_start(today)
    month_end = _month_end(today)

    # Bookings this week (non-cancelled): count and split into completed vs upcoming
    r = await session.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE (s.slot_date + s.end_time) < CURRENT_TIMESTAMP OR b.status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE (s.slot_date + s.end_time) >= CURRENT_TIMESTAMP AND b.status != 'cancelled') AS upcoming
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.status != 'cancelled'
              AND s.slot_date >= :ws AND s.slot_date <= :we
        """),
        {"tid": trainer_id, "ws": week_start, "we": week_end},
    )
    row = r.fetchone()
    week_completed = row[0] or 0
    week_upcoming = row[1] or 0
    week_total = week_completed + week_upcoming

    # Bookings this month
    r = await session.execute(
        text("""
            SELECT COUNT(*)
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.status != 'cancelled'
              AND s.slot_date >= :ms AND s.slot_date <= :me
        """),
        {"tid": trainer_id, "ms": month_start, "me": month_end},
    )
    month_total = (r.fetchone() or (0,))[0]

    # Load this week: slots total vs booked (only slots in week range)
    r = await session.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'booked') AS booked
            FROM slots
            WHERE trainer_id = :tid AND slot_date >= :ws AND slot_date <= :we
              AND status IN ('available', 'booked')
        """),
        {"tid": trainer_id, "ws": week_start, "we": week_end},
    )
    row = r.fetchone()
    week_slots_total = row[0] or 0
    week_slots_booked = row[1] or 0
    load_pct = round(100 * week_slots_booked / week_slots_total, 0) if week_slots_total else None

    # New clients in last 30 days: first booking with this trainer in the period
    r = await session.execute(
        text("""
            SELECT COUNT(DISTINCT b.client_id)
            FROM bookings b
            WHERE b.trainer_id = :tid
              AND b.created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
              AND NOT EXISTS (
                  SELECT 1 FROM bookings b2
                  WHERE b2.trainer_id = b.trainer_id AND b2.client_id = b.client_id
                    AND b2.created_at < CURRENT_TIMESTAMP - INTERVAL '30 days'
              )
        """),
        {"tid": trainer_id},
    )
    new_clients_30d = (r.fetchone() or (0,))[0]

    # Rating from profile
    r = await session.execute(
        text("SELECT rating_avg, rating_count FROM trainer_profiles WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    rating_avg = float(row[0]) if row and row[0] is not None else None
    rating_count = (row[1] or 0) if row else 0

    # Passes: active count (with sessions left), issued in last 30 days
    r = await session.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE pi.status = 'active' AND pi.sessions_remaining > 0) AS active,
                COUNT(*) FILTER (WHERE pi.issued_at >= CURRENT_TIMESTAMP - INTERVAL '30 days') AS issued_30d
            FROM pass_instances pi
            JOIN trainer_pass_products tpp ON tpp.id = pi.pass_product_id
            WHERE tpp.trainer_id = :tid
        """),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    passes_active = (row[0] or 0) if row else 0
    passes_issued_30d = (row[1] or 0) if row else 0

    # Certificates: issued total, with balance (activated), balance sum, redeemed in 30d
    r = await session.execute(
        text("""
            SELECT
                COUNT(*) AS issued_total,
                COUNT(*) FILTER (WHERE status IN ('issued', 'activated') AND COALESCE(amount_remaining_cents, 0) > 0) AS with_balance,
                COALESCE(SUM(amount_remaining_cents) FILTER (WHERE status IN ('issued', 'activated') AND amount_remaining_cents > 0), 0) AS balance_cents,
                COUNT(*) FILTER (WHERE status = 'redeemed' AND redeemed_at >= CURRENT_TIMESTAMP - INTERVAL '30 days') AS redeemed_30d
            FROM certificate_instances
            WHERE trainer_id = :tid
        """),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    certificates_issued_total = (row[0] or 0) if row else 0
    certificates_with_balance = (row[1] or 0) if row else 0
    certificate_balance_cents = (row[2] or 0) if row else 0
    certificates_redeemed_30d = (row[3] or 0) if row else 0

    return {
        "week_total": week_total,
        "week_completed": week_completed,
        "week_upcoming": week_upcoming,
        "month_total": month_total,
        "week_slots_total": week_slots_total,
        "week_slots_booked": week_slots_booked,
        "load_pct": load_pct,
        "new_clients_30d": new_clients_30d,
        "rating_avg": rating_avg,
        "rating_count": rating_count,
        "week_start": week_start,
        "week_end": week_end,
        "month_start": month_start,
        "month_end": month_end,
        "passes_active": passes_active,
        "passes_issued_30d": passes_issued_30d,
        "certificates_issued_total": certificates_issued_total,
        "certificates_with_balance": certificates_with_balance,
        "certificate_balance_cents": certificate_balance_cents,
        "certificates_redeemed_30d": certificates_redeemed_30d,
    }


async def get_trainer_stats_dashboard(session: AsyncSession, trainer_id: int) -> dict:
    """
    Rich stats for trainer Mini App dashboard: base stats + trends, by-day, by-week,
    insights (busiest day, comparison to last period). All dates/times in server TZ.
    """
    base = await get_trainer_stats(session, trainer_id)
    today = date.today()
    week_start = base["week_start"]
    week_end = base["week_end"]
    month_start = base["month_start"]
    month_end = base["month_end"]

    # Last week (same Mon–Sun structure) for comparison
    last_week_start = week_start - timedelta(days=7)
    last_week_end = week_end - timedelta(days=7)
    last_month_start = (month_start.replace(day=1) - timedelta(days=1)).replace(day=1)
    last_month_end = month_start - timedelta(days=1)

    # Last week total
    r = await session.execute(
        text("""
            SELECT COUNT(*)
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.status != 'cancelled'
              AND s.slot_date >= :ws AND s.slot_date <= :we
        """),
        {"tid": trainer_id, "ws": last_week_start, "we": last_week_end},
    )
    last_week_total = (r.fetchone() or (0,))[0]

    # Last month total
    r = await session.execute(
        text("""
            SELECT COUNT(*)
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.status != 'cancelled'
              AND s.slot_date >= :ms AND s.slot_date <= :me
        """),
        {"tid": trainer_id, "ms": last_month_start, "me": last_month_end},
    )
    last_month_total = (r.fetchone() or (0,))[0]

    # Bookings by day of this week (Mon=0 .. Sun=6), count per day
    r = await session.execute(
        text("""
            SELECT s.slot_date, COUNT(*)
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.status != 'cancelled'
              AND s.slot_date >= :ws AND s.slot_date <= :we
            GROUP BY s.slot_date
            ORDER BY s.slot_date
        """),
        {"tid": trainer_id, "ws": week_start, "we": week_end},
    )
    by_date = {row[0]: row[1] for row in r.fetchall()}
    max_day_count = max(by_date.values()) if by_date else 1
    bookings_by_day = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        cnt = by_date.get(d, 0)
        bookings_by_day.append({
            "day_label": STATS_DAY_NAMES[i],
            "date": d.isoformat(),
            "count": cnt,
            "pct": round(100 * cnt / max_day_count, 0) if max_day_count else 0,
        })

    # Weekly trend: last 6 weeks (each Mon–Sun)
    weekly_trend = []
    for w in range(5, -1, -1):
        ws = week_start - timedelta(days=7 * (w + 1))
        we = ws + timedelta(days=6)
        r = await session.execute(
            text("""
                SELECT COUNT(*)
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid AND b.status != 'cancelled'
                  AND s.slot_date >= :ws AND s.slot_date <= :we
            """),
            {"tid": trainer_id, "ws": ws, "we": we},
        )
        cnt = (r.fetchone() or (0,))[0]
        weekly_trend.append({
            "week_start": ws.isoformat(),
            "week_label": f"{ws.day:02d}.{ws.month:02d}",
            "count": cnt,
        })
    trend_max = max((t["count"] for t in weekly_trend), default=1)

    # Busiest weekday (0=Mon .. 6=Sun) over last 4 weeks
    r = await session.execute(
        text("""
            SELECT EXTRACT(DOW FROM s.slot_date)::int AS dow, COUNT(*)
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.status != 'cancelled'
              AND s.slot_date >= :since
            GROUP BY EXTRACT(DOW FROM s.slot_date)
            ORDER BY COUNT(*) DESC
            LIMIT 1
        """),
        {"tid": trainer_id, "since": today - timedelta(days=28)},
    )
    row = r.fetchone()
    # PostgreSQL DOW: 0=Sun, 1=Mon, ... 6=Sat → convert to Mon=0
    busiest_dow = (int(row[0]) - 1) % 7 if row else None
    busiest_weekday = STATS_DAY_NAMES[busiest_dow] if busiest_dow is not None else None
    # Last occurrence of that weekday in the period (for "14.03 (Пт)" display)
    busiest_date = None
    if busiest_dow is not None:
        days_back = (today.weekday() - busiest_dow) % 7
        busiest_date = today - timedelta(days=days_back)

    # Unique clients this month
    r = await session.execute(
        text("""
            SELECT COUNT(DISTINCT b.client_id)
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.status != 'cancelled'
              AND s.slot_date >= :ms AND s.slot_date <= :me
        """),
        {"tid": trainer_id, "ms": month_start, "me": month_end},
    )
    unique_clients_month = (r.fetchone() or (0,))[0]

    # Percent change vs last period (for "wow" copy)
    week_change_pct = None
    if last_week_total and base["week_total"] != last_week_total:
        week_change_pct = round(100 * (base["week_total"] - last_week_total) / last_week_total, 0)
    month_change_pct = None
    if last_month_total and base["month_total"] != last_month_total:
        month_change_pct = round(100 * (base["month_total"] - last_month_total) / last_month_total, 0)

    # Revenue from actual booking prices: join bookings with trainer_services on (trainer_id, service_id).
    r = await session.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE s.slot_date >= CURRENT_DATE - INTERVAL '7 days') AS cnt_7d,
                COUNT(*) FILTER (WHERE s.slot_date >= CURRENT_DATE - INTERVAL '30 days') AS cnt_30d,
                COALESCE(SUM(ts.price_cents) FILTER (WHERE s.slot_date >= CURRENT_DATE - INTERVAL '7 days'), 0) AS rev_7d,
                COALESCE(SUM(ts.price_cents) FILTER (WHERE s.slot_date >= CURRENT_DATE - INTERVAL '30 days'), 0) AS rev_30d
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
            WHERE b.trainer_id = :tid AND b.status != 'cancelled'
              AND s.status = 'booked'
              AND s.slot_date >= CURRENT_DATE - INTERVAL '30 days'
            """
        ),
        {"tid": trainer_id},
    )
    row = r.fetchone() or (0, 0, 0, 0)
    revenue_7d_cents = row[2] or 0
    revenue_30d_cents = row[3] or 0

    # Cancellations: count of cancelled bookings in period (by slot date).
    r = await session.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE s.slot_date >= CURRENT_DATE - INTERVAL '7 days') AS cancel_7d,
                COUNT(*) FILTER (WHERE s.slot_date >= CURRENT_DATE - INTERVAL '30 days') AS cancel_30d
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.status = 'cancelled'
              AND s.slot_date >= CURRENT_DATE - INTERVAL '30 days'
            """
        ),
        {"tid": trainer_id},
    )
    cancel_row = r.fetchone() or (0, 0)
    cancellations_7d = cancel_row[0] or 0
    cancellations_30d = cancel_row[1] or 0

    free_slots_week = max(0, (base["week_slots_total"] or 0) - (base["week_slots_booked"] or 0))

    # Top clients: by count of non-cancelled bookings in last 30 days.
    r = await session.execute(
        text(
            """
            SELECT
                c.id,
                COALESCE(TRIM(c.first_name || ' ' || c.last_name), 'Клиент') AS name,
                COALESCE(c.phone, '') AS phone,
                COUNT(*) AS cnt
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid
              AND b.status != 'cancelled'
              AND s.slot_date >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY c.id, name, phone
            ORDER BY cnt DESC, name
            LIMIT 5
            """
        ),
        {"tid": trainer_id},
    )
    top_clients = [
        {"client_id": row[0], "name": row[1], "phone": row[2], "sessions": row[3]}
        for row in r.fetchall()
    ]

    return {
        **base,
        "last_week_total": last_week_total,
        "last_month_total": last_month_total,
        "week_change_pct": week_change_pct,
        "month_change_pct": month_change_pct,
        "bookings_by_day": bookings_by_day,
        "weekly_trend": weekly_trend,
        "trend_max": trend_max,
        "busiest_weekday": busiest_weekday,
        "busiest_date": busiest_date,
        "unique_clients_month": unique_clients_month,
        "week_start_iso": week_start.isoformat(),
        "week_end_iso": week_end.isoformat(),
        "revenue_7d_cents": revenue_7d_cents,
        "revenue_30d_cents": revenue_30d_cents,
        "cancellations_7d": cancellations_7d,
        "cancellations_30d": cancellations_30d,
        "free_slots_week": free_slots_week,
        "top_clients": top_clients,
    }


async def get_platform_stats(session: AsyncSession) -> dict:
    """
    Full platform stats for admin: current state, 7d/30d periods, trainers breakdown,
    conversion and signals for business decisions.
    """
    today = date.today()
    week_start = this_week_monday()
    week_end = week_start + timedelta(days=6)

    # --- Trainers: by status + totals ---
    r = await session.execute(
        text("""
            SELECT status, COUNT(*) FROM trainers GROUP BY status ORDER BY status
        """),
    )
    trainers_by_status = {row[0]: row[1] for row in r.fetchall()}
    trainers_total = sum(trainers_by_status.values())
    trainers_pending_moderation = trainers_by_status.get("pending_profile", 0)
    trainers_active = trainers_by_status.get("active", 0)
    trainers_with_telegram = 0  # active and linked
    if trainers_active:
        r = await session.execute(
            text("SELECT COUNT(*) FROM trainers WHERE status = 'active' AND telegram_id IS NOT NULL"),
        )
        trainers_with_telegram = (r.fetchone() or (0,))[0]

    # --- Current state: today & this week ---
    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.status != 'cancelled' AND s.slot_date = :d
        """),
        {"d": today},
    )
    bookings_today = (r.fetchone() or (0,))[0]

    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.status != 'cancelled'
              AND s.slot_date >= :ws AND s.slot_date <= :we
              AND (s.slot_date + s.end_time) >= CURRENT_TIMESTAMP
        """),
        {"ws": week_start, "we": week_end},
    )
    bookings_upcoming_week = (r.fetchone() or (0,))[0]

    r = await session.execute(
        text("SELECT COUNT(*) FROM client_requests WHERE status = 'new'"),
    )
    requests_open_now = (r.fetchone() or (0,))[0]

    # --- Last 7 days ---
    r = await session.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE status != 'cancelled') AS non_cancelled,
                COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled
            FROM bookings
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
        """),
    )
    row = r.fetchone() or (0, 0)
    bookings_7d = (row[0] or 0) + (row[1] or 0)
    cancelled_7d = row[1] or 0

    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM client_requests
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
        """),
    )
    requests_7d = (r.fetchone() or (0,))[0]

    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM trainers
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
        """),
    )
    trainers_created_7d = (r.fetchone() or (0,))[0]

    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM client_request_responses
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
        """),
    )
    responses_7d = (r.fetchone() or (0,))[0]

    # --- Last 30 days ---
    r = await session.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE status != 'cancelled') AS non_cancelled,
                COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled
            FROM bookings
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        """),
    )
    row = r.fetchone() or (0, 0)
    bookings_30d = (row[0] or 0) + (row[1] or 0)
    cancelled_30d = row[1] or 0

    r = await session.execute(
        text("""
            SELECT COUNT(*), COUNT(*) FILTER (WHERE status = 'new') AS new_count
            FROM client_requests
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        """),
    )
    row = r.fetchone()
    requests_30d = row[0] or 0
    requests_new_30d = row[1] or 0

    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM trainers
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        """),
    )
    trainers_created_30d = (r.fetchone() or (0,))[0]

    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM client_request_responses
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        """),
    )
    responses_30d = (r.fetchone() or (0,))[0]

    # --- Conversion: requests that got at least one response (30d) ---
    r = await session.execute(
        text("""
            SELECT COUNT(DISTINCT r.id)
            FROM client_requests r
            INNER JOIN client_request_responses resp ON resp.client_request_id = r.id
            WHERE r.created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        """),
    )
    requests_with_response_30d = (r.fetchone() or (0,))[0]
    conversion_pct = round(100 * requests_with_response_30d / requests_30d, 0) if requests_30d else None

    # --- Requests still open (created 7+ days ago) — signal "stale" ---
    r = await session.execute(
        text("""
            SELECT COUNT(*) FROM client_requests
            WHERE status = 'new' AND created_at < CURRENT_TIMESTAMP - INTERVAL '7 days'
        """),
    )
    requests_stale = (r.fetchone() or (0,))[0]

    # --- Support: new messages (for admin dashboard) ---
    support_new = 0
    try:
        r = await session.execute(
            text("SELECT COUNT(*) FROM support_messages WHERE status = 'new'"),
        )
        support_new = (r.fetchone() or (0,))[0]
    except Exception:
        pass

    # --- Passes & certificates (platform-wide) ---
    r = await session.execute(
        text("""
            SELECT
                (SELECT COUNT(*) FROM pass_instances pi
                 JOIN trainer_pass_products tpp ON tpp.id = pi.pass_product_id
                 WHERE pi.status = 'active' AND pi.sessions_remaining > 0) AS passes_active,
                (SELECT COUNT(*) FROM pass_instances WHERE issued_at >= CURRENT_TIMESTAMP - INTERVAL '30 days') AS passes_issued_30d,
                (SELECT COUNT(*) FROM certificate_instances) AS certs_issued,
                (SELECT COUNT(*) FROM certificate_instances WHERE status IN ('issued', 'activated') AND COALESCE(amount_remaining_cents, 0) > 0) AS certs_with_balance,
                (SELECT COALESCE(SUM(amount_remaining_cents), 0) FROM certificate_instances WHERE status IN ('issued', 'activated') AND amount_remaining_cents > 0) AS cert_balance_cents,
                (SELECT COUNT(*) FROM certificate_instances WHERE status = 'redeemed' AND redeemed_at >= CURRENT_TIMESTAMP - INTERVAL '30 days') AS certs_redeemed_30d
            FROM (SELECT 1) _one
        """),
    )
    row = r.fetchone()
    passes_active_total = (row[0] or 0) if row else 0
    passes_issued_30d_total = (row[1] or 0) if row else 0
    certs_issued_total = (row[2] or 0) if row else 0
    certs_with_balance_total = (row[3] or 0) if row else 0
    cert_balance_cents_total = (row[4] or 0) if row else 0
    certs_redeemed_30d_total = (row[5] or 0) if row else 0

    # --- Alerts: reasons to take action ---
    alerts: list[dict] = []
    # High cancellation rate (as signal, not strict error)
    cancel_rate_7d = round(100 * cancelled_7d / bookings_7d, 0) if bookings_7d else None
    cancel_rate_30d = round(100 * cancelled_30d / bookings_30d, 0) if bookings_30d else None

    if trainers_pending_moderation > 0:
        alerts.append({"type": "moderation", "title": "Модерация", "description": f"{trainers_pending_moderation} тренеров ждут проверки"})
    if requests_open_now > 0:
        alerts.append({"type": "requests", "title": "Заявки", "description": f"{requests_open_now} заявок без отклика"})
    if requests_stale > 0:
        alerts.append({"type": "stale", "title": "Старые заявки", "description": f"{requests_stale} заявок без ответа более 7 дней"})
    if support_new > 0:
        alerts.append({"type": "support", "title": "Поддержка", "description": f"{support_new} новых обращений"})
    if bookings_7d == 0 and trainers_active > 0:
        alerts.append({"type": "no_bookings", "title": "Нет записей", "description": "За 7 дней ни одной записи при активных тренерах"})
    if conversion_pct is not None and requests_30d >= 3 and conversion_pct < 50:
        alerts.append({"type": "conversion", "title": "Низкая конверсия", "description": f"Заявки → отклик: {int(conversion_pct)}%"})
    if cancel_rate_7d is not None and bookings_7d >= 5 and cancel_rate_7d >= 30:
        alerts.append({"type": "cancellations_high_7d", "title": "Много отмен (7 дней)", "description": f"Отменено {cancelled_7d} занятий за 7 дней ({int(cancel_rate_7d)}% всех записей)"})
    if cancel_rate_30d is not None and bookings_30d >= 10 and cancel_rate_30d >= 30:
        alerts.append({"type": "cancellations_high_30d", "title": "Много отмен (30 дней)", "description": f"Отменено {cancelled_30d} занятий за 30 дней ({int(cancel_rate_30d)}%)"})

    return {
        "trainers_by_status": trainers_by_status,
        "trainers_total": trainers_total,
        "trainers_pending_moderation": trainers_pending_moderation,
        "trainers_active": trainers_active,
        "trainers_with_telegram": trainers_with_telegram,
        "bookings_today": bookings_today,
        "bookings_upcoming_week": bookings_upcoming_week,
        "requests_open_now": requests_open_now,
        "bookings_7d": bookings_7d,
        "cancelled_7d": cancelled_7d,
        "requests_7d": requests_7d,
        "trainers_created_7d": trainers_created_7d,
        "responses_7d": responses_7d,
        "bookings_30d": bookings_30d,
        "cancelled_30d": cancelled_30d,
        "requests_30d": requests_30d,
        "requests_new_30d": requests_new_30d,
        "trainers_created_30d": trainers_created_30d,
        "responses_30d": responses_30d,
        "requests_with_response_30d": requests_with_response_30d,
        "conversion_pct": conversion_pct,
        "requests_stale": requests_stale,
        "support_new_count": support_new,
        "alerts": alerts,
        "today": today,
        "week_start": week_start,
        "week_end": week_end,
        "passes_active_total": passes_active_total,
        "passes_issued_30d_total": passes_issued_30d_total,
        "certs_issued_total": certs_issued_total,
        "certs_with_balance_total": certs_with_balance_total,
        "cert_balance_cents_total": cert_balance_cents_total,
        "certs_redeemed_30d_total": certs_redeemed_30d_total,
    }
