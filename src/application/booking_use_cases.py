"""
Booking use cases: create booking (slot + client_id, comment), list for trainer, pending notifications.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.certificate_use_cases import redeem_certificate_for_booking, redeem_certificate_balance_for_booking
from src.application.pass_product_use_cases import redeem_pass_session_for_booking
from src.shared.notification_hours import NOTIFICATION_TZ

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

# Correlated subquery for trainer-facing "Арена" text (alias `b` = bookings row).
# Prefer booking.arena_id when set; otherwise aggregate trainer_arenas (legacy rows).
SQL_BOOKING_ARENA_DISPLAY = """COALESCE(
    (SELECT a.name FROM arenas a WHERE a.id = b.arena_id),
    (
        SELECT string_agg(a.name, ', ' ORDER BY a.name)
        FROM trainer_arenas ta
        JOIN arenas a ON a.id = ta.arena_id
        WHERE ta.trainer_id = b.trainer_id
    )
)"""


def _normalize_trainer_arenas_display(raw: str | None) -> str | None:
    """Single normalization for arenas_str / venue_label (matches list_bookings_for_trainer output)."""
    s = (raw or "").strip()
    return s if s else None


async def get_first_service_id_for_trainer(session: AsyncSession, trainer_id: int) -> int | None:
    """First service_id from trainer_services for this trainer (by service_id). Used when no explicit service (e.g. recurring)."""
    r = await session.execute(
        text("""
            SELECT service_id FROM trainer_services
            WHERE trainer_id = :tid
            ORDER BY service_id
            LIMIT 1
        """),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    return row[0] if row else None


async def get_trainer_default_city_and_service(
    session: AsyncSession, trainer_id: int
) -> tuple[int | None, int | None]:
    """City and first service for trainer (for welcome-link onboarding: prefill client session)."""
    r = await session.execute(
        text("""
            SELECT p.city_id,
                   (SELECT ts.service_id FROM trainer_services ts WHERE ts.trainer_id = :tid ORDER BY ts.service_id LIMIT 1)
            FROM trainer_profiles p
            WHERE p.trainer_id = :tid
        """),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return (None, None)
    city_id = row[0] if row[0] is not None else None
    service_id = row[1] if row[1] is not None else None
    return (city_id, service_id)


async def create_booking(
    session: AsyncSession,
    slot_id: int,
    trainer_id: int,
    client_id: int,
    service_id: int,
    client_comment: str | None = None,
    client_request_id: int | None = None,
    created_by_trainer: bool = False,
    arena_id: int | None = None,
) -> int | None:
    """
    Create booking: insert row and set slot status to 'booked'. service_id required (must be in trainer_services).
    Status semantics:
    - Client-initiated bookings start as 'pending' (trainer should confirm/decline).
    - Trainer-initiated bookings (created_by_trainer=True) start as 'confirmed'.

    If client_request_id is set, link booking to that request and archive the request.
    When created_by_trainer=True and client_request_id is set, leave client_notified_trainer_booked_at
    null so client bot sends "trainer booked you"; when False (client booked themselves) set it to now()
    to avoid duplicate notification.

    Returns booking id or None if slot not available / wrong trainer / service not offered by trainer.

    Concurrency: two parallel bookings on the same slot are serialized with FOR UPDATE on the slot row
    (pessimistic lock until commit). The second transaction waits, then sees status != 'available' and
    returns None — no reliance on unique constraint errors for the happy path. (Unique on slot_id remains
    defense in depth.)
    """
    r = await session.execute(
        text("""
            SELECT id FROM slots
            WHERE id = :sid AND trainer_id = :tid AND status = 'available'
            FOR UPDATE
        """),
        {"sid": slot_id, "tid": trainer_id},
    )
    if not r.fetchone():
        return None
    r = await session.execute(
        text("""
            SELECT 1 FROM trainer_services
            WHERE trainer_id = :tid AND service_id = :sid
        """),
        {"tid": trainer_id, "sid": service_id},
    )
    if not r.fetchone():
        return None
    resolved_arena: int | None = arena_id
    if resolved_arena is None:
        rpa = await session.execute(
            text("SELECT primary_arena_id FROM trainers WHERE id = :tid"),
            {"tid": trainer_id},
        )
        row_pa = rpa.fetchone()
        resolved_arena = row_pa[0] if row_pa else None
        if resolved_arena is None:
            rmin = await session.execute(
                text("SELECT MIN(arena_id) FROM trainer_arenas WHERE trainer_id = :tid"),
                {"tid": trainer_id},
            )
            resolved_arena = rmin.scalar()
    else:
        rchk = await session.execute(
            text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
            {"tid": trainer_id, "aid": resolved_arena},
        )
        if not rchk.fetchone():
            return None
    try:
        r = await session.execute(
            text("""
                INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, client_comment, client_request_id, status, arena_id)
                VALUES (:sid, :tid, :cid, :svc_id, :comment, :req_id, :status, :arena_id)
                RETURNING id
            """),
            {
                "sid": slot_id,
                "tid": trainer_id,
                "cid": client_id,
                "svc_id": service_id,
                "comment": (client_comment or "").strip() or None,
                "req_id": client_request_id,
                "status": "confirmed" if created_by_trainer else "pending",
                "arena_id": resolved_arena,
            },
        )
        (booking_id,) = r.fetchone()
    except IntegrityError:
        # Rare: unique(slot_id) if lock was bypassed; keep API predictable (no 500 on race).
        await session.rollback()
        return None
    await session.execute(
        text("UPDATE slots SET status = 'booked' WHERE id = :id"),
        {"id": slot_id},
    )
    if client_request_id is not None:
        await session.execute(
            text("UPDATE client_requests SET status = 'archived' WHERE id = :id"),
            {"id": client_request_id},
        )
    if client_request_id is not None and not created_by_trainer:
        await session.execute(
            text("UPDATE bookings SET client_notified_trainer_booked_at = NOW() WHERE id = :id"),
            {"id": booking_id},
        )
    await session.commit()
    return booking_id


async def get_trainer_primary_arena_resolved(session: AsyncSession, trainer_id: int) -> int | None:
    """primary_arena_id from trainers, or MIN(arena_id) from trainer_arenas as fallback."""
    r = await session.execute(
        text("SELECT primary_arena_id FROM trainers WHERE id = :tid"),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    primary = row[0] if row else None
    if primary is not None:
        return primary
    r2 = await session.execute(
        text("SELECT MIN(arena_id) FROM trainer_arenas WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    return r2.scalar()


async def resolve_arena_for_client_self_booking(
    session: AsyncSession,
    trainer_id: int,
    session_arena_id: int | None,
) -> tuple[int | None, str | None, bool]:
    """
    Self-booking from catalog: online slot always resolves to the trainer's primary venue.
    - «Любая арена» or null session → primary.
    - Filter by primary → primary.
    - Filter by another trainer's arena (secondary): still book on primary; third flag True so UI
      can explain that non-primary venues require a client request, not self-booking.

    Returns (arena_id, error_code, used_primary_despite_non_primary_filter).
    error_code: no_venue | invalid_arena | None.
    """
    primary = await get_trainer_primary_arena_resolved(session, trainer_id)
    if primary is None:
        return None, "no_venue", False
    if session_arena_id is not None:
        r = await session.execute(
            text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
            {"tid": trainer_id, "aid": session_arena_id},
        )
        if not r.fetchone():
            return None, "invalid_arena", False
        if session_arena_id != primary:
            return primary, None, True
    return primary, None, False


async def generate_reminders_for_booking(session: AsyncSession, booking_id: int) -> None:
    """
    Create reminder rows for a booking according to strategy:
    - If booking created earlier than slot_date: try 24h and 2h reminders.
    - If booking created in the same day as slot: only 2h reminder, и только если осталось >2 часов.
    - Никогда не создаём напоминания в ночные часы (0–7); такие кандидаты просто пропускаем.
    """
    r = await session.execute(
        text(
            """
            SELECT b.id, c.telegram_id, b.created_at, s.slot_date, s.start_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :id
            """
        ),
        {"id": booking_id},
    )
    row = r.fetchone()
    if not row:
        return
    client_telegram_id = row[1]
    if client_telegram_id is None:
        # Client added by trainer without Telegram — no push reminders
        return

    bid = row[0]
    created_at: datetime = row[2]
    slot_date = row[3]
    start_time = row[4]

    # Treat slot_date/start_time as local (Europe/Minsk) time, and compare in that timezone.
    local_tz = ZoneInfo(NOTIFICATION_TZ)
    # created_at comes from DB as UTC (timestamptz) – normalize and convert to local tz.
    if created_at.tzinfo is None:
        created_local = created_at.replace(tzinfo=timezone.utc).astimezone(local_tz)
    else:
        created_local = created_at.astimezone(local_tz)
    slot_dt_local = datetime.combine(slot_date, start_time).replace(tzinfo=local_tz)

    # If slot already started or in the past relative to creation – no reminders.
    if slot_dt_local <= created_local:
        return

    def is_quiet_hours(dt: datetime) -> bool:
        # Simple rule: 0:00–7:59 считаем ночными, туда ничего не шлём.
        return 0 <= dt.hour < 8

    reminders: list[tuple[str, datetime]] = []

    t24 = slot_dt_local - timedelta(hours=24)
    t2 = slot_dt_local - timedelta(hours=2)

    # Booking created before slot calendar day → потенциально 24h + 2h.
    if created_local.date() < slot_date:
        if t24 > created_local and t24 < slot_dt_local and not is_quiet_hours(t24):
            reminders.append(("before_24h", t24))
        if t2 > created_local and t2 < slot_dt_local and not is_quiet_hours(t2):
            reminders.append(("before_2h", t2))
    else:
        # Booking created in the same calendar day as slot.
        # Если до слота осталось больше 2 часов, создаём только 2h-напоминание.
        if created_local < t2 and t2 < slot_dt_local and not is_quiet_hours(t2):
            reminders.append(("before_2h", t2))
        # Если клиент записался позже, чем за 2 часа до начала, дополнительных напоминаний не создаём.

    for kind, send_at in reminders:
        # Store send_at in UTC so comparison with NOW() in DB is correct.
        send_at_utc = send_at.astimezone(timezone.utc)
        await session.execute(
            text(
                """
                INSERT INTO reminders (booking_id, client_telegram_id, kind, send_at, status)
                VALUES (:bid, :ctid, :kind, :send_at, 'pending')
                """
            ),
            {
                "bid": bid,
                "ctid": client_telegram_id,
                "kind": kind,
                "send_at": send_at_utc,
            },
        )
    # Напоминания можно коммитить отдельно от самой брони (create_booking уже сделал commit).
    await session.commit()


async def get_pending_trainer_booked_notifications(session: AsyncSession, limit: int = 50) -> list[dict]:
    """
    Bookings created by trainer with client_request_id, client not yet notified.
    Returns: booking_id, client_telegram_id, trainer_name, slot_date, start_time.
    """
    r = await session.execute(
        text("""
            SELECT b.id, c.telegram_id,
                   COALESCE(TRIM(CONCAT(tp.first_name, ' ', tp.last_name)), 'Тренер'),
                   s.slot_date, s.start_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            JOIN trainers t ON t.id = b.trainer_id
            LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
            WHERE b.client_request_id IS NOT NULL
              AND b.client_notified_trainer_booked_at IS NULL
              AND c.telegram_id IS NOT NULL
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "booking_id": row[0],
            "client_telegram_id": row[1],
            "trainer_name": (row[2] or "Тренер").strip(),
            "slot_date": row[3],
            "start_time": row[4],
        }
        for row in rows
    ]


async def mark_trainer_booked_notified(session: AsyncSession, booking_id: int) -> None:
    """Mark that we sent the client the 'trainer booked you' notification."""
    await session.execute(
        text("UPDATE bookings SET client_notified_trainer_booked_at = NOW() WHERE id = :id"),
        {"id": booking_id},
    )
    await session.commit()


async def list_pending_reminders(session: AsyncSession, limit: int = 100) -> list[dict]:
    """
    Reminders due to send: status=pending, send_at <= now.
    Only for non-cancelled bookings. Returns list of dicts with id, client_telegram_id, kind, slot_date, start_time.
    """
    r = await session.execute(
        text("""
            SELECT r.id, r.client_telegram_id, r.kind, s.slot_date, s.start_time, s.end_time
            FROM reminders r
            JOIN bookings b ON b.id = r.booking_id
            JOIN slots s ON s.id = b.slot_id
            WHERE r.status = 'pending'
              AND r.send_at <= now()
              AND b.status NOT IN ('cancelled', 'declined')
            ORDER BY r.send_at
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "client_telegram_id": row[1],
            "kind": row[2],
            "slot_date": row[3],
            "start_time": row[4],
            "end_time": row[5],
        }
        for row in rows
    ]


async def mark_reminder_sent(session: AsyncSession, reminder_id: int) -> None:
    await session.execute(
        text(
            "UPDATE reminders SET status = 'sent', sent_at = now() WHERE id = :id"
        ),
        {"id": reminder_id},
    )
    await session.commit()


async def mark_reminder_failed(session: AsyncSession, reminder_id: int, error: str) -> None:
    await session.execute(
        text(
            "UPDATE reminders SET status = 'failed', error = :err WHERE id = :id"
        ),
        {"id": reminder_id, "err": (error or "")[:500]},
    )
    await session.commit()


async def get_booking_with_slot(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> dict | None:
    """Load booking by id with slot date/time, client_id, service_id/service_name; None if not found or wrong trainer."""
    r = await session.execute(
        text("""
            SELECT b.id, b.slot_id, b.client_id, b.service_id, c.telegram_id, c.phone, b.client_comment, b.created_at,
                   s.slot_date, s.start_time, s.end_time, COALESCE(b.status, 'confirmed'),
                   srv.name AS service_name
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            JOIN services srv ON srv.id = b.service_id
            WHERE b.id = :id AND b.trainer_id = :tid
        """),
        {"id": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "slot_id": row[1],
        "client_id": row[2],
        "service_id": row[3],
        "client_telegram_id": row[4],
        "client_phone": row[5] or "",
        "client_comment": row[6],
        "created_at": row[7],
        "slot_date": row[8],
        "start_time": row[9],
        "end_time": row[10],
        "status": (row[11] or "confirmed").strip(),
        "service_name": (row[12] or "").strip() or "—",
    }


async def list_bookings_for_trainer(
    session: AsyncSession,
    trainer_id: int,
    limit: int = 100,
) -> list[dict]:
    """
    List active upcoming bookings for trainer (slot_date >= today, slot still booked).
    Sorted nearest first (slot_date ASC, start_time ASC) so first page = today, next = tomorrow, etc.
    No past days — trainer sees only current day and future.
    """
    # session_num = ordinal among all (past + upcoming) non-cancelled sessions for this trainer+client
    r = await session.execute(
        text("""
            WITH upcoming AS (
                SELECT b.id, b.slot_id, b.client_id,
                       c.telegram_id, c.phone, c.first_name AS client_first_name, c.last_name AS client_last_name,
                       b.client_comment, b.created_at,
                       s.slot_date, s.start_time, s.end_time,
                       (SELECT COUNT(*) + 1
                        FROM bookings b2
                        JOIN slots s2 ON s2.id = b2.slot_id
                        WHERE b2.trainer_id = b.trainer_id AND b2.client_id = b.client_id
                          AND b2.status NOT IN ('cancelled', 'declined')
                          AND (s2.slot_date < s.slot_date OR (s2.slot_date = s.slot_date AND s2.start_time < s.start_time))
                       ) AS session_num,
                       COALESCE(b.status, 'confirmed') AS status,
                       srv.name AS services_str,
                       """
            + SQL_BOOKING_ARENA_DISPLAY
            + """ AS arenas_str
                FROM bookings b
                JOIN clients c ON c.id = b.client_id
                JOIN slots s ON s.id = b.slot_id
                JOIN services srv ON srv.id = b.service_id
                WHERE b.trainer_id = :tid AND s.status = 'booked' AND s.slot_date >= CURRENT_DATE
                  AND b.status IN ('pending', 'confirmed')
            )
            SELECT id, slot_id, telegram_id, phone, client_first_name, client_last_name,
                   client_comment, created_at, slot_date, start_time, end_time,
                   session_num, services_str, arenas_str, status
            FROM upcoming
            ORDER BY slot_date ASC, start_time ASC
            LIMIT :lim
        """),
        {"tid": trainer_id, "lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "slot_id": row[1],
            "client_telegram_id": row[2],
            "client_phone": row[3] or "",
            "client_first_name": row[4],
            "client_last_name": row[5],
            "client_comment": row[6],
            "created_at": row[7],
            "slot_date": row[8],
            "start_time": row[9],
            "end_time": row[10],
            "session_num": row[11],
            "services_str": (row[12] or "").strip() or None,
            "arenas_str": _normalize_trainer_arenas_display(row[13] if len(row) > 13 else None),
            "status": (row[14] or "confirmed").strip() if len(row) > 14 else "confirmed",
        }
        for row in rows
    ]


async def active_booking_summaries_by_slot_for_trainer_range(
    session: AsyncSession,
    trainer_id: int,
    from_date: date,
    to_date: date,
) -> dict[int, dict]:
    """
    For booked slots in a date range: slot_id -> display fields for schedule UI.
    Uses SQL_BOOKING_ARENA_DISPLAY so venue_label matches booking detail arenas_str.
    """
    r = await session.execute(
        text(
            """
            SELECT b.slot_id, b.id,
                   COALESCE(b.status, 'confirmed') AS status,
                   srv.name AS services_str,
                   """
            + SQL_BOOKING_ARENA_DISPLAY
            + """ AS arenas_str,
                   c.first_name AS client_first_name, c.last_name AS client_last_name, c.phone AS client_phone
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN clients c ON c.id = b.client_id
            JOIN services srv ON srv.id = b.service_id
            WHERE b.trainer_id = :tid
              AND s.slot_date >= :from_d AND s.slot_date <= :to_d
              AND s.status = 'booked'
              AND b.status IN ('pending', 'confirmed')
        """),
        {"tid": trainer_id, "from_d": from_date, "to_d": to_date},
    )
    out: dict[int, dict] = {}
    for row in r.fetchall():
        slot_id = int(row[0])
        first = (row[5] or "").strip() if row[5] else ""
        last = (row[6] or "").strip() if row[6] else ""
        phone = (row[7] or "").strip() if row[7] else ""
        name = " ".join(p for p in (first, last) if p).strip()
        client_preview = name or phone or "Клиент"
        out[slot_id] = {
            "booking_id": int(row[1]),
            "status": (row[2] or "confirmed").strip(),
            "services_str": ((row[3] or "").strip() or None),
            "venue_label": _normalize_trainer_arenas_display(row[4]),
            "client_preview": client_preview,
        }
    return out


async def list_trainer_clients(
    session: AsyncSession,
    trainer_id: int,
    limit: int = 50,
) -> list[dict]:
    """
    Distinct clients that have at least one non-cancelled booking with this trainer.
    Sorted by last session date/time (most recent first).
    last_date/last_start are from the same booking (the most recent one).
    """
    r = await session.execute(
        text(
            """
            WITH last_per_client AS (
                SELECT
                    b.client_id,
                    s.slot_date AS last_date,
                    s.start_time AS last_start,
                    ROW_NUMBER() OVER (
                        PARTITION BY b.client_id
                        ORDER BY s.slot_date DESC, s.start_time DESC
                    ) AS rn
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid
                  AND b.status NOT IN ('cancelled', 'declined')
            )
            SELECT
                c.id,
                c.telegram_id,
                c.telegram_username,
                c.phone,
                c.first_name,
                c.last_name,
                l.last_date,
                l.last_start,
                (SELECT MIN(s2.slot_date)
                 FROM bookings b2
                 JOIN slots s2 ON s2.id = b2.slot_id
                 WHERE b2.client_id = c.id
                   AND b2.trainer_id = :tid
                   AND b2.status NOT IN ('cancelled', 'declined')) AS first_date
            FROM last_per_client l
            JOIN clients c ON c.id = l.client_id
            WHERE l.rn = 1
            ORDER BY l.last_date DESC, l.last_start DESC NULLS LAST
            LIMIT :lim
            """
        ),
        {"tid": trainer_id, "lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "telegram_id": row[1],
            "telegram_username": row[2] or "",
            "phone": row[3] or "",
            "first_name": row[4] or "",
            "last_name": row[5] or "",
            "last_date": row[6],
            "last_start": row[7],
            "first_date": row[8],
        }
        for row in rows
    ]


async def list_bookings_for_client(
    session: AsyncSession,
    client_telegram_id: int,
    limit: int = 50,
) -> list[dict]:
    """List client's active (upcoming) bookings only — pending, not completed/cancelled; slot still booked.
    Includes arena (one per trainer): name, address, map_link (Yandex) from coords; place_display for bot."""
    r = await session.execute(
        text("""
            SELECT b.id, b.slot_id, b.trainer_id, b.service_id, b.client_comment, b.status,
                   s.slot_date, s.start_time, s.end_time,
                   (EXTRACT(EPOCH FROM (s.end_time - s.start_time)) / 60)::int AS duration_minutes,
                   COALESCE(TRIM(p.first_name || ' ' || p.last_name), 'Тренер') AS trainer_name,
                   t.telegram_id AS trainer_telegram_id,
                   NULLIF(TRIM(COALESCE(t.telegram_username, '')), '') AS trainer_telegram_username,
                   NULLIF(TRIM(COALESCE(p.phone, '')), '') AS trainer_phone,
                   srv.name AS service_name,
                   a.name AS arena_name,
                   a.address AS arena_address,
                   a.latitude AS arena_lat,
                   a.longitude AS arena_lon
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            JOIN trainers t ON t.id = b.trainer_id
            JOIN services srv ON srv.id = b.service_id
            LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
            LEFT JOIN LATERAL (
                SELECT a2.name, a2.address, a2.latitude, a2.longitude
                FROM trainer_arenas ta
                JOIN arenas a2 ON a2.id = ta.arena_id
                WHERE ta.trainer_id = b.trainer_id
                LIMIT 1
            ) a ON true
            WHERE c.telegram_id = :ctid
              AND s.status = 'booked'
              AND b.status IN ('pending', 'confirmed')
            ORDER BY s.slot_date ASC, s.start_time ASC
            LIMIT :lim
        """),
        {"ctid": client_telegram_id, "lim": limit},
    )
    rows = r.fetchall()
    out = []
    for row in rows:
        arena_name = (row[15] or "").strip() if row[15] else ""
        arena_address = (row[16] or "").strip() if row[16] else ""
        lat, lon = row[17], row[18]
        if lat is not None and lon is not None:
            map_link = f"https://yandex.ru/maps/?pt={lon},{lat}&z=16"
        else:
            map_link = None
        if not arena_name:
            place_display = "Уточните у тренера"
        else:
            place_display = f"Площадка: {arena_name}"
        out.append({
            "id": row[0],
            "slot_id": row[1],
            "trainer_id": row[2],
            "service_id": row[3],
            "service_name": (row[14] or "").strip() or "—",
            "client_comment": row[4],
            "status": row[5],
            "slot_date": row[6],
            "start_time": row[7],
            "end_time": row[8],
            "duration_minutes": row[9] if row[9] is not None else 45,
            "trainer_name": (row[10] or "").strip() or "Тренер",
            "trainer_telegram_id": row[11],
            "trainer_telegram_username": (row[12] or "").strip() or None,
            "trainer_phone": (row[13] or "").strip() or None,
            "place_display": place_display,
            "arena_name": arena_name or None,
            "arena_address": arena_address or None,
            "map_link": map_link,
        })
    return out


async def list_trainer_client_history(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    limit: int = 20,
) -> list[dict]:
    """
    Last N non-cancelled bookings for this trainer and client.
    Includes date, time, arena (best-effort), duration, service_name and status.
    """
    r = await session.execute(
        text(
            """
            SELECT
                b.id,
                s.slot_date,
                s.start_time,
                s.end_time,
                (EXTRACT(EPOCH FROM (s.end_time - s.start_time)) / 60)::int AS duration_minutes,
                COALESCE(a2.name, '') AS arena_name,
                COALESCE(srv.name, '—') AS service_name,
                b.status
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN services srv ON srv.id = b.service_id
            LEFT JOIN LATERAL (
                SELECT a.name
                FROM trainer_arenas ta
                JOIN arenas a ON a.id = ta.arena_id
                WHERE ta.trainer_id = b.trainer_id
                ORDER BY ta.arena_id
                LIMIT 1
            ) a2 ON true
            WHERE b.trainer_id = :tid
              AND b.client_id = :cid
              AND b.status NOT IN ('cancelled', 'declined')
            ORDER BY s.slot_date DESC, s.start_time DESC
            LIMIT :lim
            """
        ),
        {"tid": trainer_id, "cid": client_id, "lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "slot_date": row[1],
            "start_time": row[2],
            "end_time": row[3],
            "duration_minutes": row[4] if row[4] is not None else 45,
            "arena_name": (row[5] or "").strip() or None,
            "service_name": (row[6] or "").strip() or "—",
            "status": (row[7] or "").strip() or "confirmed",
        }
        for row in rows
    ]


async def count_trainer_client_sessions(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> int:
    """Total number of non-cancelled bookings for this trainer and client (for stats in client card)."""
    r = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM bookings b
            WHERE b.trainer_id = :tid
              AND b.client_id = :cid
              AND b.status NOT IN ('cancelled', 'declined')
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    row = r.fetchone()
    return row[0] if row else 0


async def get_trainer_client_next_booking(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> dict | None:
    """Next upcoming (pending/confirmed) booking for this trainer and client; slot in the future. One row."""
    r = await session.execute(
        text(
            """
            SELECT
                b.id,
                s.slot_date,
                s.start_time,
                s.end_time,
                (EXTRACT(EPOCH FROM (s.end_time - s.start_time)) / 60)::int AS duration_minutes,
                COALESCE(a2.name, '') AS arena_name,
                COALESCE(srv.name, '—') AS service_name
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN services srv ON srv.id = b.service_id
            LEFT JOIN LATERAL (
                SELECT a.name FROM trainer_arenas ta
                JOIN arenas a ON a.id = ta.arena_id
                WHERE ta.trainer_id = b.trainer_id
                ORDER BY ta.arena_id LIMIT 1
            ) a2 ON true
            WHERE b.trainer_id = :tid
              AND b.client_id = :cid
              AND b.status IN ('pending', 'confirmed')
              AND (s.slot_date > CURRENT_DATE OR (s.slot_date = CURRENT_DATE AND s.start_time > CURRENT_TIME))
            ORDER BY s.slot_date ASC, s.start_time ASC
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "slot_date": row[1],
        "start_time": row[2],
        "end_time": row[3],
        "duration_minutes": row[4] if row[4] is not None else 45,
        "arena_name": (row[5] or "").strip() or None,
        "service_name": (row[6] or "").strip() or "—",
    }


async def count_trainer_client_upcoming(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> int:
    """Count of upcoming (pending/confirmed, future slot) bookings for this trainer and client."""
    r = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid
              AND b.client_id = :cid
              AND b.status IN ('pending', 'confirmed')
              AND (s.slot_date > CURRENT_DATE OR (s.slot_date = CURRENT_DATE AND s.start_time > CURRENT_TIME))
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    row = r.fetchone()
    return row[0] if row else 0


async def get_bookings_pending_notification(session: AsyncSession) -> list[dict]:
    """Bookings where notified_at is null and status is pending (client-initiated online booking).

    Trainer-created bookings are inserted as confirmed and must not appear here — no confirm/decline push.
    """
    r = await session.execute(
        text("""
            SELECT b.id, b.trainer_id, b.slot_id, c.telegram_id, c.phone, b.client_comment,
                   s.slot_date, s.start_time, s.end_time,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                   COALESCE(srv.name, '—') AS service_name,
                   COALESCE(ci.name, ci2.name, '—') AS city_name,
                   (SELECT string_agg(a.name, ', ' ORDER BY a.name)
                    FROM trainer_arenas ta
                    JOIN arenas a ON a.id = ta.arena_id
                    WHERE ta.trainer_id = b.trainer_id) AS arenas_str
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN services srv ON srv.id = b.service_id
            LEFT JOIN client_requests cr ON cr.id = b.client_request_id
            LEFT JOIN cities ci ON ci.id = cr.city_id
            LEFT JOIN client_sessions cs ON cs.telegram_id = c.telegram_id
            LEFT JOIN cities ci2 ON ci2.id = cs.city_id
            WHERE b.notified_at IS NULL
              AND b.status = 'pending'
            ORDER BY b.created_at ASC
        """),
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "trainer_id": row[1],
            "slot_id": row[2],
            "client_telegram_id": row[3],
            "client_phone": row[4] or "",
            "client_comment": row[5],
            "slot_date": row[6],
            "start_time": row[7],
            "end_time": row[8],
            "client_name": (row[9] or "").strip() or "Клиент",
            "service_name": (row[10] or "—").strip(),
            "city_name": (row[11] or "—").strip(),
            "arenas_str": (row[12] or "").strip() or "—",
        }
        for row in rows
    ]


async def mark_booking_notified(session: AsyncSession, booking_id: int) -> None:
    await session.execute(
        text("UPDATE bookings SET notified_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": booking_id},
    )
    await session.commit()


async def cancel_booking(session: AsyncSession, booking_id: int, trainer_id: int) -> bool:
    """
    Cancel booking: set slot back to 'available', booking status to 'cancelled', cancel reminders, enqueue client notification.
    Returns True if booking was found and cancelled.
    """
    r = await session.execute(
        text("""
            UPDATE slots s
            SET status = 'available'
            FROM bookings b
            WHERE b.slot_id = s.id AND b.id = :bid AND b.trainer_id = :tid AND s.status = 'booked'
            RETURNING s.id
        """),
        {"bid": booking_id, "tid": trainer_id},
    )
    if not r.fetchone():
        return False
    await session.execute(
        text("UPDATE bookings SET status = 'cancelled' WHERE id = :bid"),
        {"bid": booking_id},
    )
    await session.execute(
        text("UPDATE reminders SET status = 'cancelled' WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    await _schedule_booking_cancel_notification(session, booking_id)
    await session.commit()
    return True


async def cancel_booking_by_client(
    session: AsyncSession,
    booking_id: int,
    client_telegram_id: int,
    reason: str | None = None,
) -> dict | None:
    """
    Cancel booking by client: slot freed, status cancelled, reminders cancelled, reason stored.
    Returns payload for trainer notification (trainer_telegram_id, slot_date, start_time, client_name, reason)
    or None if booking not found / not owned by client.
    """
    reason_val = (reason or "").strip() or None
    # Load trainer + slot + client for notification before updating
    r = await session.execute(
        text("""
            SELECT t.telegram_id, s.slot_date, s.start_time,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name
            FROM bookings b
            JOIN clients c ON c.id = b.client_id AND c.telegram_id = :ctid
            JOIN slots s ON s.id = b.slot_id
            JOIN trainers t ON t.id = b.trainer_id
            WHERE b.id = :bid AND b.status IN ('pending', 'confirmed') AND s.status = 'booked'
        """),
        {"bid": booking_id, "ctid": client_telegram_id},
    )
    row = r.fetchone()
    if not row:
        return None
    trainer_telegram_id, slot_date, start_time, client_name = row[0], row[1], row[2], (row[3] or "").strip() or "Клиент"

    r = await session.execute(
        text("""
            UPDATE slots s
            SET status = 'available'
            FROM bookings b
            JOIN clients c ON c.id = b.client_id AND c.telegram_id = :ctid
            WHERE b.slot_id = s.id AND b.id = :bid AND s.status = 'booked'
              AND b.status IN ('pending', 'confirmed')
            RETURNING s.id
        """),
        {"bid": booking_id, "ctid": client_telegram_id},
    )
    if not r.fetchone():
        return None
    await session.execute(
        text("""
            UPDATE bookings
            SET status = 'cancelled', client_cancel_comment = :reason
            WHERE id = :bid
        """),
        {"bid": booking_id, "reason": reason_val},
    )
    await session.execute(
        text("UPDATE reminders SET status = 'cancelled' WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    await session.commit()
    return {
        "trainer_telegram_id": trainer_telegram_id,
        "slot_date": slot_date,
        "start_time": start_time,
        "client_name": client_name,
        "reason": reason_val,
    }


async def confirm_booking(session: AsyncSession, booking_id: int, trainer_id: int) -> dict | None:
    """
    Confirm booking by trainer.
    Preconditions (enforced in SQL):
    - booking belongs to trainer;
    - booking status is 'pending';
    - slot is still booked.

    On success set status='confirmed' and return booking + slot + client contact info
    for notification flows. Returns None when booking is not confirmable (not found / wrong trainer / wrong status).
    """
    # PostgreSQL: UPDATE ... FROM ... RETURNING can only return columns from the updated table
    r = await session.execute(
        text(
            """
            UPDATE bookings b
            SET status = 'confirmed'
            FROM slots s
            WHERE b.slot_id = s.id
              AND b.id = :bid
              AND b.trainer_id = :tid
              AND s.status = 'booked'
              AND b.status = 'pending'
            RETURNING b.id
            """
        ),
        {"bid": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    # Load full row for notifications
    r2 = await session.execute(
        text(
            """
            SELECT b.id, b.slot_id, b.client_id, c.telegram_id, COALESCE(c.phone, '') AS client_phone,
                   b.client_comment, b.created_at, s.slot_date, s.start_time, s.end_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid
            """
        ),
        {"bid": booking_id},
    )
    row2 = r2.fetchone()
    await session.commit()
    if not row2:
        return None
    return {
        "id": row2[0],
        "slot_id": row2[1],
        "client_id": row2[2],
        "client_telegram_id": row2[3],
        "client_phone": row2[4] or "",
        "client_comment": row2[5],
        "created_at": row2[6],
        "slot_date": row2[7],
        "start_time": row2[8],
        "end_time": row2[9],
    }


async def decline_booking(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> dict | None:
    """
    Decline booking: set slot back to 'available', booking status to 'declined',
    cancel reminders. Returns booking + slot + client contact info for notifications,
    or None if booking not found / not pending / slot already not booked.
    """
    # Load current state and validate that we can still decline.
    r = await session.execute(
        text(
            """
            SELECT b.id,
                   c.telegram_id,
                   COALESCE(c.phone, '') AS client_phone,
                   s.slot_date,
                   s.start_time,
                   s.end_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid
              AND b.trainer_id = :tid
              AND b.status = 'pending'
              AND s.status = 'booked'
            """
        ),
        {"bid": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None

    await session.execute(
        text(
            """
            UPDATE slots s
            SET status = 'available'
            FROM bookings b
            WHERE b.slot_id = s.id
              AND b.id = :bid
              AND b.trainer_id = :tid
              AND s.status = 'booked'
            """
        ),
        {"bid": booking_id, "tid": trainer_id},
    )
    await session.execute(
        text("UPDATE bookings SET status = 'declined' WHERE id = :bid"),
        {"bid": booking_id},
    )
    await session.execute(
        text("UPDATE reminders SET status = 'cancelled' WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    await session.commit()
    return {
        "id": row[0],
        "client_telegram_id": row[1],
        "client_phone": row[2] or "",
        "slot_date": row[3],
        "start_time": row[4],
        "end_time": row[5],
    }


async def _schedule_booking_cancel_notification(session: AsyncSession, booking_id: int) -> None:
    """Enqueue one row for client bot to send 'trainer cancelled your booking' message."""
    await session.execute(
        text("""
            INSERT INTO booking_cancel_notifications (booking_id, client_telegram_id, slot_date, start_time, trainer_display_name)
            SELECT b.id, c.telegram_id, s.slot_date, s.start_time,
                   TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, '')))
            FROM bookings b
            JOIN clients c ON c.id = b.client_id AND c.telegram_id IS NOT NULL
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
            WHERE b.id = :bid
            ON CONFLICT (booking_id) DO NOTHING
        """),
        {"bid": booking_id},
    )
    # No RETURNING needed; client bot will poll by sent_at IS NULL


async def get_trainer_telegram_id(session: AsyncSession, trainer_id: int) -> int | None:
    """Trainer telegram_id for sending notification."""
    r = await session.execute(
        text("SELECT telegram_id FROM trainers WHERE id = :id"),
        {"id": trainer_id},
    )
    row = r.fetchone()
    return row[0] if row and row[0] is not None else None


async def list_bookings_pending_confirm_reminder(
    session: AsyncSession,
    limit: int = 50,
) -> list[dict]:
    """
    Bookings that are still pending confirmation and start within the next 2 hours,
    for which we have not yet sent a 'please confirm/decline' reminder to the trainer.
    Returns: booking_id, trainer_id, client_phone, slot_date, start_time.
    """
    r = await session.execute(
        text(
            """
            SELECT
                b.id,
                b.trainer_id,
                COALESCE(c.phone, '') AS client_phone,
                s.slot_date,
                s.start_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.status = 'pending'
              AND s.status = 'booked'
              AND (s.slot_date + s.start_time) > CURRENT_TIMESTAMP
              AND (s.slot_date + s.start_time) <= CURRENT_TIMESTAMP + INTERVAL '2 hours'
              AND b.trainer_confirm_reminder_sent_at IS NULL
            ORDER BY s.slot_date, s.start_time
            LIMIT :lim
            """
        ),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "booking_id": row[0],
            "trainer_id": row[1],
            "client_phone": row[2] or "",
            "slot_date": row[3],
            "start_time": row[4],
        }
        for row in rows
    ]


async def mark_confirm_reminder_sent(session: AsyncSession, booking_id: int) -> None:
    """Mark that trainer confirmation reminder was sent for this booking."""
    await session.execute(
        text(
            "UPDATE bookings SET trainer_confirm_reminder_sent_at = CURRENT_TIMESTAMP WHERE id = :id"
        ),
        {"id": booking_id},
    )
    await session.commit()


async def get_pending_booking_cancel_notifications(session: AsyncSession, limit: int = 50) -> list[dict]:
    """Rows where sent_at IS NULL for client bot to send 'trainer cancelled' message."""
    r = await session.execute(
        text("""
            SELECT id, booking_id, client_telegram_id, slot_date, start_time, trainer_display_name
            FROM booking_cancel_notifications
            WHERE sent_at IS NULL
            ORDER BY created_at ASC
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "booking_id": row[1],
            "client_telegram_id": row[2],
            "slot_date": row[3],
            "start_time": row[4],
            "trainer_display_name": row[5] or "Тренер",
        }
        for row in rows
    ]


async def mark_booking_cancel_notification_sent(session: AsyncSession, notification_id: int) -> None:
    await session.execute(
        text("UPDATE booking_cancel_notifications SET sent_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": notification_id},
    )
    await session.commit()


# --- Auto-complete: mark booking completed when slot end has passed; enqueue feedback notifications ---
# Rule (3.1): One pass session is redeemed when booking status becomes completed. All code paths
# that set status to 'completed' must call redeem_pass_session_for_booking in the same transaction.

async def list_bookings_to_complete(session: AsyncSession, limit: int = 50) -> list[dict]:
    """Bookings with status in ('pending', 'confirmed') and slot (date + end_time) already in the past."""
    r = await session.execute(
        text("""
            SELECT b.id, c.telegram_id, b.trainer_id,
                   s.slot_date, s.start_time, s.end_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.status IN ('pending', 'confirmed') AND s.status = 'booked'
              AND (s.slot_date + s.end_time) < CURRENT_TIMESTAMP
            ORDER BY s.slot_date, s.end_time
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "client_telegram_id": row[1],
            "trainer_id": row[2],
            "slot_date": row[3],
            "start_time": row[4],
            "end_time": row[5],
        }
        for row in rows
    ]


async def list_bookings_pending_client_completion_push(
    session: AsyncSession, limit: int = 50
) -> list[dict]:
    """
    Completed bookings where the client «занятие завершено» Telegram push was not yet acknowledged.
    Used to retry after a failed send (outbox-style without a separate table).
    """
    r = await session.execute(
        text("""
            SELECT b.id, c.telegram_id, b.trainer_id,
                   s.slot_date, s.start_time, s.end_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.status = 'completed'
              AND b.client_booking_completed_push_sent_at IS NULL
              AND c.telegram_id IS NOT NULL
            ORDER BY b.id
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "client_telegram_id": row[1],
            "trainer_id": row[2],
            "slot_date": row[3],
            "start_time": row[4],
            "end_time": row[5],
        }
        for row in rows
    ]


async def mark_client_booking_completion_push_sent(
    session: AsyncSession, booking_id: int
) -> None:
    await session.execute(
        text(
            "UPDATE bookings SET client_booking_completed_push_sent_at = CURRENT_TIMESTAMP "
            "WHERE id = :bid"
        ),
        {"bid": booking_id},
    )
    await session.commit()


async def mark_booking_completed_and_notify(
    session: AsyncSession,
    booking_id: int,
) -> bool:
    """Set booking status to completed, redeem one pass session if applicable, insert row for trainer feedback notification. Returns True if a pass was redeemed."""
    await session.execute(
        text("UPDATE bookings SET status = 'completed' WHERE id = :bid"),
        {"bid": booking_id},
    )
    # Rule 3.1: deduct one pass session when booking becomes completed (best-effort; no raise if no pass)
    pass_redeemed = await redeem_pass_session_for_booking(session, booking_id)
    # If no pass was used, try to deduct from certificate monetary balance for this client+trainer
    if not pass_redeemed:
        await redeem_certificate_balance_for_booking(session, booking_id)
    await session.execute(
        text("""
            INSERT INTO booking_completed_notifications (booking_id, client_telegram_id, trainer_id)
            SELECT b.id, c.telegram_id, b.trainer_id FROM bookings b
            JOIN clients c ON c.id = b.client_id AND c.telegram_id IS NOT NULL WHERE b.id = :bid
            ON CONFLICT (booking_id) DO NOTHING
        """),
        {"bid": booking_id},
    )
    await session.commit()
    return pass_redeemed


async def get_booking_no_pass_notify_payload(
    session: AsyncSession,
    booking_id: int,
) -> dict | None:
    """Payload for trainer 'no pass for this service' notification: trainer_telegram_id, client_name, service_name, date, time. Booking must exist (typically just completed)."""
    r = await session.execute(
        text("""
            SELECT t.telegram_id,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')),
                   COALESCE(srv.name, '—'),
                   s.slot_date,
                   s.start_time
            FROM bookings b
            JOIN trainers t ON t.id = b.trainer_id
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN services srv ON srv.id = b.service_id
            WHERE b.id = :bid
        """),
        {"bid": booking_id},
    )
    row = r.fetchone()
    if not row or row[0] is None:
        return None
    slot_date, start_time = row[3], row[4]
    date_str = slot_date.strftime("%d.%m") if hasattr(slot_date, "strftime") else str(slot_date)
    _days = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
    day_str = (_days[slot_date.weekday()] if hasattr(slot_date, "weekday") else "") if slot_date else ""
    time_str = start_time.strftime("%H:%M") if start_time and hasattr(start_time, "strftime") else str(start_time or "")[:5]
    return {
        "trainer_telegram_id": row[0],
        "client_name": (row[1] or "").strip() or "Клиент",
        "service_name": (row[2] or "—").strip(),
        "date": date_str,
        "day": day_str,
        "time": time_str,
    }


async def mark_booking_completed_by_trainer(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> dict | None:
    """
    Trainer marks booking as conducted. Booking must be trainer's and status 'confirmed'.
    Sets status to completed, redeems one pass session if applicable, enqueues client/trainer notifications.
    Returns {"success": True, "pass_redeemed": bool} or None if booking not found / not confirmed.
    """
    r = await session.execute(
        text("""
            SELECT id, status FROM bookings
            WHERE id = :bid AND trainer_id = :tid
        """),
        {"bid": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row or (row[1] or "").strip() != "confirmed":
        return None
    await session.execute(
        text("UPDATE bookings SET status = 'completed' WHERE id = :bid"),
        {"bid": booking_id},
    )
    pass_redeemed = await redeem_pass_session_for_booking(session, booking_id)
    if not pass_redeemed:
        await redeem_certificate_balance_for_booking(session, booking_id)
    await session.execute(
        text("""
            INSERT INTO booking_completed_notifications (booking_id, client_telegram_id, trainer_id)
            SELECT b.id, c.telegram_id, b.trainer_id FROM bookings b
            JOIN clients c ON c.id = b.client_id AND c.telegram_id IS NOT NULL WHERE b.id = :bid
            ON CONFLICT (booking_id) DO NOTHING
        """),
        {"bid": booking_id},
    )
    await session.commit()
    return {"success": True, "pass_redeemed": pass_redeemed}


async def get_pending_completed_for_trainer(session: AsyncSession, limit: int = 50) -> list[dict]:
    """Rows where trainer has not yet been notified (trainer_sent_at IS NULL)."""
    r = await session.execute(
        text("""
            SELECT n.id, n.booking_id, n.trainer_id, n.client_telegram_id,
                   b.client_id,
                   s.slot_date, s.start_time
            FROM booking_completed_notifications n
            JOIN bookings b ON b.id = n.booking_id
            JOIN slots s ON s.id = b.slot_id
            WHERE n.trainer_sent_at IS NULL
            ORDER BY n.id
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "booking_id": row[1],
            "trainer_id": row[2],
            "client_telegram_id": row[3],
            "client_id": row[4],
            "slot_date": row[5],
            "start_time": row[6],
        }
        for row in rows
    ]


async def mark_trainer_completed_sent(session: AsyncSession, notification_id: int) -> None:
    await session.execute(
        text("UPDATE booking_completed_notifications SET trainer_sent_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": notification_id},
    )
    await session.commit()


async def get_booking_for_client_feedback(
    session: AsyncSession,
    booking_id: int,
    client_telegram_id: int,
) -> dict | None:
    """Booking by id and client; must be completed. Returns trainer_id and slot info for feedback flow."""
    r = await session.execute(
        text("""
            SELECT b.id, b.trainer_id, s.slot_date, s.start_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid AND c.telegram_id = :ctid AND b.status = 'completed'
        """),
        {"bid": booking_id, "ctid": client_telegram_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {"id": row[0], "trainer_id": row[1], "slot_date": row[2], "start_time": row[3]}


async def get_completed_booking_for_repeat(
    session: AsyncSession,
    booking_id: int,
    client_telegram_id: int,
) -> dict | None:
    """Completed booking by id and client; for repeat/recurring flows. Returns trainer_id, client_id, service_id, slot_date, start_time, end_time."""
    r = await session.execute(
        text("""
            SELECT b.id, b.trainer_id, b.client_id, b.service_id, s.slot_date, s.start_time, s.end_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid AND c.telegram_id = :ctid AND b.status = 'completed'
        """),
        {"bid": booking_id, "ctid": client_telegram_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "trainer_id": row[1],
        "client_id": row[2],
        "service_id": row[3],
        "slot_date": row[4],
        "start_time": row[5],
        "end_time": row[6],
    }


async def get_booking_for_trainer_feedback(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> dict | None:
    """Completed booking by id and trainer; for trainer to leave review. None if not found or not completed."""
    r = await session.execute(
        text("""
            SELECT b.id FROM bookings b
            WHERE b.id = :bid AND b.trainer_id = :tid AND b.status = 'completed'
        """),
        {"bid": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {"id": row[0]}


async def set_booking_trainer_review(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
    review_text: str,
) -> bool:
    """Save trainer's optional review text for a completed booking. Returns True if updated."""
    r = await session.execute(
        text("""
            UPDATE bookings SET trainer_review_text = :text
            WHERE id = :bid AND trainer_id = :tid AND status = 'completed'
            RETURNING id
        """),
        {"bid": booking_id, "tid": trainer_id, "text": (review_text or "").strip()[:2000]},
    )
    if not r.fetchone():
        return False
    await session.commit()
    return True


# --- Inactive client notifications (10 / 30 days since last session) ---

INACTIVE_KIND_10_DAYS = "10_days"
INACTIVE_KIND_30_DAYS = "30_days"


async def get_clients_for_inactive_notification(
    session: AsyncSession,
    kind: str,
    limit: int = 200,
) -> list[dict]:
    """
    Clients whose last session (slot ended) was exactly 10 or 30 days ago and who haven't received this notification yet.
    kind: INACTIVE_KIND_10_DAYS or INACTIVE_KIND_30_DAYS. Returns client_id, telegram_id, first_name.
    """
    days = 10 if kind == INACTIVE_KIND_10_DAYS else 30
    r = await session.execute(
        text("""
            WITH last_session AS (
                SELECT b.client_id, MAX(s.slot_date) AS last_slot_date
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE (s.slot_date + s.end_time) < CURRENT_TIMESTAMP
                  AND b.status NOT IN ('cancelled', 'declined')
                GROUP BY b.client_id
            ),
            candidates AS (
                SELECT c.id AS client_id, c.telegram_id, c.first_name, ls.last_slot_date
                FROM clients c
                JOIN last_session ls ON ls.client_id = c.id
                WHERE (CURRENT_DATE - ls.last_slot_date) = :days
            )
            SELECT ca.client_id, ca.telegram_id, ca.first_name
            FROM candidates ca
            WHERE NOT EXISTS (
                SELECT 1 FROM client_inactive_notifications n
                WHERE n.client_id = ca.client_id AND n.kind = :kind
            )
            LIMIT :lim
        """),
        {"days": days, "kind": kind, "lim": limit},
    )
    rows = r.fetchall()
    return [
        {"client_id": row[0], "telegram_id": row[1], "first_name": (row[2] or "").strip() or None}
        for row in rows
    ]


async def mark_inactive_notification_sent(
    session: AsyncSession,
    client_id: int,
    kind: str,
) -> None:
    """Record that we sent this inactive notification to the client (so we don't send again)."""
    await session.execute(
        text("""
            INSERT INTO client_inactive_notifications (client_id, kind)
            VALUES (:cid, :kind)
            ON CONFLICT (client_id, kind) DO NOTHING
        """),
        {"cid": client_id, "kind": kind},
    )
    await session.commit()
