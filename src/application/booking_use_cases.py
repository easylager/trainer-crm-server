"""
Booking use cases: create booking (slot + client_id, comment), list for trainer, pending notifications.
"""
import json
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from src.infrastructure.repositories.client_trainer_edge_repository import ClientTrainerEdgeRepository

from src.application.client_use_cases import get_client_id_by_telegram_id
from src.application.family_access_use_cases import list_family_access_telegram_ids_for_reminders
from src.application.pass_product_use_cases import redeem_pass_session_for_booking
from src.application.certificate_use_cases import redeem_certificate_balance_for_booking
from src.shared.notification_hours import NOTIFICATION_TZ
from src.shared.price_tier_kind import (
    PRICE_TIER_ADULT,
    PRICE_TIER_CHILD,
    normalize_price_tier_kind,
    price_tier_label_ru,
    sql_order_case_tier_kind,
)
from src.shared.ttl_cache import invalidate_slots_for_trainer
from src.application.trainer_first_booking_milestone import try_claim_first_booking_milestones

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

# Seats counted toward slot capacity (group lessons).
BOOKING_STATUSES_OCCUPYING_SEAT = ("pending", "confirmed")

# Trainer removed a past booking from schedule/reported stats (soft purge; ledger reversed when applicable).
BOOKING_STATUS_TRAINER_REMOVED = "trainer_removed"

# Set when status → cancelled; stats exclude system bulk cancels (recurring rule off, roster detach).
BOOKING_CANCELLATION_SOURCE_TRAINER = "trainer"
BOOKING_CANCELLATION_SOURCE_CLIENT = "client"
BOOKING_CANCELLATION_SOURCE_RECURRING_DETACH = "recurring_detach"
BOOKING_CANCELLATION_SOURCE_ROSTER_DETACH = "roster_detach"

# Hub / reminders: slot_date + start_time|end_time are Europe/Minsk wall clock (not DB session TZ).
# Client push times: never 00:00–07:59; early-morning targets snap to 08:00 same local day if still before the slot.
_REMINDER_NIGHT_END_HOUR = 8
_REMINDER_EVENING_PRIOR_HOUR = 20
_REMINDER_MIN_GAP_SEC = 120
# Bookings in these statuses do not receive new reminder rows (day-level resync skips them).
_REMINDER_SCHEDULE_EXCLUDED_STATUSES = (
    "cancelled",
    "declined",
    "trainer_removed",
    "completed",
    "no_show",
    "payment_dispute",
)
_REMINDER_SCHEDULE_EXCLUDED_SQL = ", ".join(f"'{s}'" for s in _REMINDER_SCHEDULE_EXCLUDED_STATUSES)
_SQL_SLOT_START_TS = f"((s.slot_date + s.start_time) AT TIME ZONE '{NOTIFICATION_TZ}')"
_SQL_SLOT_END_TS = f"((s.slot_date + s.end_time) AT TIME ZONE '{NOTIFICATION_TZ}')"
# Booking rows for this trainer already delivered via trainer_bot pending-booking notifier (notified_at set).
_SQL_PRIOR_TRAINER_NOTIFIED_BOOKING_COUNT = """(
    SELECT COUNT(*)::int FROM bookings b0
    WHERE b0.trainer_id = b.trainer_id
      AND b0.id < b.id
      AND b0.notified_at IS NOT NULL
)"""

# Trainer-reported problem terminal outcomes (PRD E4); not «successful» completed sessions for analytics/notifications.
BOOKING_STATUS_NO_SHOW = "no_show"
BOOKING_STATUS_PAYMENT_DISPUTE = "payment_dispute"

# Correlated subquery for trainer-facing "Арена" text (aliases `b` = booking, `s` = slot).
# Prefer booking.arena_id, then slot.arena_id (group / fixed-venue slots), else all trainer_arenas (legacy).
class ServicePriceVariantRequired(Exception):
    """Trainer has multiple price tiers for this service; client must choose service_price_variant_id."""


async def _resolve_service_booking_price(
    session: AsyncSession,
    trainer_id: int,
    service_id: int,
    service_price_variant_id: int | None,
    *,
    strict_variant: bool,
) -> tuple[int | None, int | None, str | None]:
    """
    Pick tier and snapshot price for a new booking; returns (variant_id, price_cents, tier_kind snapshot).
    strict_variant=True (client self-booking): multiple tiers without explicit id -> raises ServicePriceVariantRequired.
    """
    r = await session.execute(
        text(
            f"""
            SELECT id, price_cents, tier_kind FROM trainer_service_price_variants
            WHERE trainer_id = :tid AND service_id = :sid
            ORDER BY {sql_order_case_tier_kind("tier_kind")},
                     sort_order, id
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    rows = r.fetchall()
    if rows:
        if service_price_variant_id is not None:
            for row in rows:
                if int(row[0]) == int(service_price_variant_id):
                    ptk = normalize_price_tier_kind(row[2])
                    return (int(row[0]), int(row[1]), ptk)
            return (None, None, None)
        if len(rows) == 1:
            ptk = normalize_price_tier_kind(rows[0][2])
            return (int(rows[0][0]), int(rows[0][1]), ptk)
        if strict_variant:
            raise ServicePriceVariantRequired()
        # Trainer-side / non-strict: ambiguous tier — prefer single adult seat over display order (child first).
        adult_row = next(
            (row for row in rows if normalize_price_tier_kind(row[2]) == PRICE_TIER_ADULT),
            None,
        )
        pick = adult_row if adult_row is not None else rows[0]
        ptk0 = normalize_price_tier_kind(pick[2])
        return (int(pick[0]), int(pick[1]), ptk0)
    r2 = await session.execute(
        text(
            """
            SELECT price_cents FROM trainer_services
            WHERE trainer_id = :tid AND service_id = :sid
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    row2 = r2.fetchone()
    if row2 and row2[0] is not None:
        return (None, int(row2[0]), None)
    return (None, None, None)


async def _resolve_trainer_group_slot_booking_price(
    session: AsyncSession,
    trainer_id: int,
    service_id: int,
) -> tuple[int | None, int | None, str | None]:
    """
    Group slot (capacity>1): no child/adult tier on the booking row — per-seat snapshot is
    COALESCE(group_price_cents, price_cents) on trainer_services (optional group override, else anchor).
    """
    r = await session.execute(
        text(
            """
            SELECT price_cents, group_price_cents FROM trainer_services
            WHERE trainer_id = :tid AND service_id = :sid
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    row = r.fetchone()
    if not row:
        return (None, None, None)
    anchor = row[0]
    group_pc = row[1] if len(row) > 1 else None
    effective = group_pc if group_pc is not None else anchor
    booking_price_cents = int(effective) if effective is not None else None
    return (None, booking_price_cents, None)


SQL_BOOKING_ARENA_DISPLAY = """COALESCE(
    (SELECT a.name FROM arenas a WHERE a.id = b.arena_id),
    (SELECT a.name FROM arenas a WHERE a.id = s.arena_id),
    (
        SELECT string_agg(a.name, ', ' ORDER BY a.name)
        FROM trainer_arenas ta
        JOIN arenas a ON a.id = ta.arena_id
        WHERE ta.trainer_id = b.trainer_id
    )
)"""

# Single arena id for venue/map: booking override, then slot (fixed-venue / group), then trainer defaults.
SQL_BOOKING_RESOLVED_ARENA_ID = """COALESCE(
    b.arena_id,
    s.arena_id,
    (SELECT t.primary_arena_id FROM trainers t WHERE t.id = b.trainer_id),
    (SELECT MIN(ta.arena_id) FROM trainer_arenas ta WHERE ta.trainer_id = b.trainer_id)
)"""


def _normalize_trainer_arenas_display(raw: str | None) -> str | None:
    """Single normalization for arenas_str / venue_label (matches list_bookings_for_trainer output)."""
    s = (raw or "").strip()
    return s if s else None


async def _count_occupying_bookings(session: AsyncSession, slot_id: int) -> int:
    """How many pending/confirmed bookings currently hold a seat on this slot (group-capacity)."""
    r = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM bookings
            WHERE slot_id = :sid AND status IN ('pending', 'confirmed')
            """
        ),
        {"sid": slot_id},
    )
    row = r.fetchone()
    return int(row[0]) if row else 0


async def sync_slot_status_for_occupancy(session: AsyncSession, slot_id: int) -> None:
    """
    Set slot to 'booked' when pending+confirmed count >= capacity, else 'available'.
    Call after booking create/cancel/decline within the same transaction.
    """
    r = await session.execute(
        text("SELECT capacity FROM slots WHERE id = :sid"),
        {"sid": slot_id},
    )
    row = r.fetchone()
    if not row:
        return
    cap = max(1, int(row[0]))
    cnt = await _count_occupying_bookings(session, slot_id)
    if cnt >= cap:
        await session.execute(text("UPDATE slots SET status = 'booked' WHERE id = :id"), {"id": slot_id})
    else:
        await session.execute(text("UPDATE slots SET status = 'available' WHERE id = :id"), {"id": slot_id})


def is_slot_end_in_past_local(slot_date: date | None, end_time: time | None) -> bool:
    """
    True when slot end (calendar date + end_time interpreted in NOTIFICATION_TZ) is not after "now"
    in that zone. Used to skip reminders and «trainer booked you» push for retroactive bookings.
    """
    if slot_date is None or end_time is None:
        return False
    local_tz = ZoneInfo(NOTIFICATION_TZ)
    end_local = datetime.combine(slot_date, end_time).replace(tzinfo=local_tz)
    return end_local <= datetime.now(local_tz)


def is_slot_start_in_past_local(slot_date: date | None, start_time: time | None) -> bool:
    """
    True when slot start (wall clock in NOTIFICATION_TZ) is strictly before "now".
    Used so "new slot" pushes ignore retro openings that are not actionable as new availability.
    """
    if slot_date is None or start_time is None:
        return False
    st = start_time.replace(second=0, microsecond=0) if hasattr(start_time, "replace") else start_time
    local_tz = ZoneInfo(NOTIFICATION_TZ)
    start_local = datetime.combine(slot_date, st).replace(tzinfo=local_tz)
    return start_local < datetime.now(local_tz)


async def trainer_has_future_available_slot_wall_clock(
    session: AsyncSession,
    trainer_id: int,
) -> bool:
    """At least one available slot whose local start is still in the future (NOTIFICATION_TZ)."""
    r = await session.execute(
        text(
            f"""
            SELECT 1 FROM slots s
            WHERE s.trainer_id = :tid AND s.status = 'available'
              AND ((s.slot_date + s.start_time) AT TIME ZONE '{NOTIFICATION_TZ}')
                  > (CURRENT_TIMESTAMP AT TIME ZONE '{NOTIFICATION_TZ}')
            LIMIT 1
            """
        ),
        {"tid": trainer_id},
    )
    return r.fetchone() is not None


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


async def coerce_service_id_and_name_for_trainer_catalog(
    session: AsyncSession,
    trainer_id: int,
    preferred_service_id: int | None,
) -> tuple[int | None, str | None]:
    """
    If preferred_service_id is offered by trainer, return it and display name; else first offered service.
    Keeps hub primary service aligned with trainer's catalog offers.
    """
    if preferred_service_id is not None:
        r = await session.execute(
            text(
                """
                SELECT s.id, s.name FROM services s
                INNER JOIN trainer_services ts ON ts.service_id = s.id AND ts.trainer_id = :tid
                WHERE s.id = :sid
                LIMIT 1
                """
            ),
            {"tid": trainer_id, "sid": preferred_service_id},
        )
        row = r.fetchone()
        if row:
            return int(row[0]), (row[1] or "").strip() or None
    fid = await get_first_service_id_for_trainer(session, trainer_id)
    if fid is None:
        return None, None
    r2 = await session.execute(
        text("SELECT name FROM services WHERE id = :id"),
        {"id": fid},
    )
    row2 = r2.fetchone()
    return fid, ((row2[0] or "").strip() or None) if row2 else None


async def _trainer_offers_service(
    session: AsyncSession, trainer_id: int, service_id: int
) -> bool:
    r = await session.execute(
        text(
            """
            SELECT 1 FROM trainer_services
            WHERE trainer_id = :tid AND service_id = :sid
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    return r.fetchone() is not None


async def _service_display_name(session: AsyncSession, service_id: int) -> str | None:
    r = await session.execute(
        text("SELECT name FROM services WHERE id = :id"),
        {"id": service_id},
    )
    row = r.fetchone()
    return ((row[0] or "").strip() or None) if row else None


async def resolve_client_catalog_service_for_trainer(
    session: AsyncSession,
    trainer_id: int,
    session_row: dict[str, Any] | None,
    *service_hint_ids: int | None,
) -> tuple[int | None, str | None]:
    """
    Service offered by this trainer for catalog / self-booking on this trainer's card.
    Uses client_sessions.selected_service_id only when selected_trainer_id matches
    this trainer — otherwise global session service (e.g. primary trainer's ОФП) is ignored.
    """
    tid = int(trainer_id)
    preferred: int | None = None
    if session_row:
        raw_tid = session_row.get("selected_trainer_id")
        if raw_tid is not None:
            try:
                if int(raw_tid) == tid:
                    raw_sid = session_row.get("selected_service_id")
                    if raw_sid is not None:
                        preferred = int(raw_sid)
            except (TypeError, ValueError):
                preferred = None
    if preferred is not None and await _trainer_offers_service(session, tid, preferred):
        return preferred, await _service_display_name(session, preferred)

    seen: set[int] = set()
    chain: list[int] = []
    for raw in service_hint_ids:
        if raw is None:
            continue
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            continue
        if sid <= 0 or sid in seen:
            continue
        seen.add(sid)
        chain.append(sid)
    for sid in chain:
        if await _trainer_offers_service(session, tid, sid):
            return sid, await _service_display_name(session, sid)
    return await coerce_service_id_and_name_for_trainer_catalog(session, tid, None)


async def list_trainer_service_price_variants(
    session: AsyncSession,
    trainer_id: int,
    service_id: int,
) -> list[dict]:
    """Ordered price tiers for trainer service (first row is default)."""
    r = await session.execute(
        text(
            f"""
            SELECT id, price_cents, tier_kind, label
            FROM trainer_service_price_variants
            WHERE trainer_id = :tid AND service_id = :sid
            ORDER BY {sql_order_case_tier_kind("tier_kind")},
                     sort_order, id
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    out: list[dict] = []
    for row in r.fetchall():
        tier_kind = normalize_price_tier_kind(row[2])
        human_label = (
            price_tier_label_ru(tier_kind)
            or ((row[3] or "").strip() if row[3] is not None else "")
            or "Тариф"
        )
        out.append(
            {
                "id": int(row[0]),
                "price_cents": int(row[1]) if row[1] is not None else None,
                "tier_kind": tier_kind,
                "label": human_label,
            }
        )
    return out


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


async def count_trainer_services(session: AsyncSession, trainer_id: int) -> int:
    """Number of services on the trainer's roster (for book URL: multi-service → service picker)."""
    r = await session.execute(
        text("SELECT COUNT(*)::int FROM trainer_services WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


async def resolve_welcome_session_city_service(
    session: AsyncSession,
    trainer_id: int,
    *,
    preferred_service_id: int | None,
) -> tuple[int | None, int | None]:
    """
    Prefill city from profile; use preferred_service_id when the trainer offers it, else first service.
    Used for one-time welcome tokens (legacy tokens have no preferred id).
    """
    city_id, default_service_id = await get_trainer_default_city_and_service(session, trainer_id)
    if preferred_service_id is None:
        return (city_id, default_service_id)
    chk = await session.execute(
        text(
            "SELECT 1 FROM trainer_services WHERE trainer_id = :tid AND service_id = :sid"
        ),
        {"tid": trainer_id, "sid": preferred_service_id},
    )
    if chk.fetchone():
        return (city_id, preferred_service_id)
    return (city_id, default_service_id)


async def list_trainer_services_for_welcome_link(
    session: AsyncSession, trainer_id: int
) -> list[dict]:
    """Ordered id+name for generic welcome-link UI when trainer offers multiple services."""
    r = await session.execute(
        text("""
            SELECT ts.service_id, s.name
            FROM trainer_services ts
            JOIN services s ON s.id = ts.service_id
            WHERE ts.trainer_id = :tid
            ORDER BY ts.service_id
        """),
        {"tid": trainer_id},
    )
    return [{"id": row[0], "name": (row[1] or "").strip() or f"Услуга #{row[0]}"} for row in r.fetchall()]


async def resolve_service_id_for_generic_welcome_link(
    session: AsyncSession,
    trainer_id: int,
    requested_service_id: int | None,
) -> tuple[int | None, str | None]:
    """
    Choose which service_id to embed in a new generic welcome token.
    Returns (service_id, error_key) where error_key is None, or no_services / invalid_service.
    When trainer has multiple services and ``requested_service_id`` is omitted, uses the first
    catalog service (same order as ``list_trainer_services_for_welcome_link``) so links work without UI.
    """
    rows = await list_trainer_services_for_welcome_link(session, trainer_id)
    ids = [r["id"] for r in rows]
    if not ids:
        return None, "no_services"
    if len(ids) == 1:
        only = ids[0]
        if requested_service_id is not None and requested_service_id != only:
            return None, "invalid_service"
        return only, None
    if requested_service_id is None:
        return ids[0], None
    if requested_service_id not in ids:
        return None, "invalid_service"
    return requested_service_id, None


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
    service_price_variant_id: int | None = None,
    strict_service_price_variant: bool = False,
    *,
    allow_overbook: bool = False,
    is_sandbox: bool = False,
    recurring_client_slot_id: int | None = None,
) -> tuple[int | None, tuple[bool, bool]]:
    """
    Create booking: insert row; slot becomes 'booked' only when pending+confirmed count reaches capacity.
    service_id required (must be in trainer_services).
    Status semantics:
    - Client-initiated bookings start as 'pending' (trainer should confirm/decline).
    - Trainer-initiated bookings (created_by_trainer=True) start as 'confirmed'.
    is_sandbox=True: onboarding demo booking — excluded from stats/revenue, but still counts for the
    one-time first-booking celebration (Telegram) so TTV step 2 matches a real booking UX.

    If client_request_id is set, link booking to that request and archive the request.
    When created_by_trainer=True and client_request_id is set, leave client_notified_trainer_booked_at
    null so client bot sends "trainer booked you"; when False (client booked themselves) set it to now()
    to avoid duplicate notification.

    Returns (booking_id, (first_booking_milestone_claimed, share_catalog_tip_claimed)).
    Milestone flags are True only when this insert was the trainer's first confirmed/completed booking
    and profile timestamps were claimed in the follow-up commit.

    Concurrency: two parallel bookings on the same slot are serialized with FOR UPDATE on the slot row
    (pessimistic lock until commit). Second client waits, then sees full capacity and returns None.
    """
    r = await session.execute(
        text("""
            SELECT id, capacity, status, service_id, arena_id FROM slots
            WHERE id = :sid AND trainer_id = :tid AND status != 'cancelled'
            FOR UPDATE
        """),
        {"sid": slot_id, "tid": trainer_id},
    )
    slot_row = r.fetchone()
    if not slot_row:
        return (None, (False, False))
    capacity = max(1, int(slot_row[1]))
    if (slot_row[2] or "").strip().lower() == "cancelled":
        return (None, (False, False))
    slot_service_id = slot_row[3]
    slot_arena_id: int | None = int(slot_row[4]) if slot_row[4] is not None else None
    if capacity > 1:
        if slot_service_id is None:
            return (None, (False, False))
        if int(service_id) != int(slot_service_id):
            return (None, (False, False))
    cnt = await _count_occupying_bookings(session, slot_id)
    if cnt >= capacity:
        if not (allow_overbook and created_by_trainer and capacity > 1):
            return (None, (False, False))
    r = await session.execute(
        text("""
            SELECT 1 FROM trainer_services
            WHERE trainer_id = :tid AND service_id = :sid
        """),
        {"tid": trainer_id, "sid": service_id},
    )
    if not r.fetchone():
        return (None, (False, False))
    try:
        if capacity > 1:
            # Group slot: per-seat price from COALESCE(group_price_cents, anchor); catalog tiers do not apply.
            variant_id_resolved, booking_price_cents, price_tier_kind = (
                await _resolve_trainer_group_slot_booking_price(session, trainer_id, service_id)
            )
        else:
            variant_id_resolved, booking_price_cents, price_tier_kind = await _resolve_service_booking_price(
                session,
                trainer_id,
                service_id,
                service_price_variant_id,
                strict_variant=strict_service_price_variant,
            )
    except ServicePriceVariantRequired:
        raise
    if not (created_by_trainer and capacity > 1):
        if service_price_variant_id is not None and variant_id_resolved is None:
            return (None, (False, False))
    # Group slots: venue is fixed on the slot (set when the trainer created the slot); ignore request arena/session.
    if capacity > 1:
        resolved_arena = slot_arena_id
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
                return (None, (False, False))
    else:
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
                return (None, (False, False))
    if (
        created_by_trainer
        and capacity == 1
        and cnt == 0
        and resolved_arena is not None
        and slot_arena_id != resolved_arena
    ):
        # Trainer picked another venue on an empty individual slot — keep schedule row in sync.
        await session.execute(
            text("UPDATE slots SET arena_id = :aid WHERE id = :sid AND trainer_id = :tid"),
            {"aid": resolved_arena, "sid": slot_id, "tid": trainer_id},
        )
    try:
        r = await session.execute(
            text("""
                INSERT INTO bookings (
                    slot_id, trainer_id, client_id, service_id, client_comment, client_request_id,
                    status, arena_id, service_price_variant_id, booking_price_cents, price_tier_kind,
                    is_sandbox, recurring_client_slot_id
                )
                VALUES (
                    :sid, :tid, :cid, :svc_id, :comment, :req_id, :status, :arena_id, :vvid, :bpc, :ptk,
                    :is_sandbox, :rcs_id
                )
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
                "vvid": variant_id_resolved,
                "bpc": booking_price_cents,
                "ptk": price_tier_kind,
                "is_sandbox": is_sandbox,
                "rcs_id": recurring_client_slot_id,
            },
        )
        (booking_id,) = r.fetchone()
    except IntegrityError:
        await session.rollback()
        return (None, (False, False))
    await sync_slot_status_for_occupancy(session, slot_id)
    r_sd = await session.execute(
        text("SELECT slot_date, end_time FROM slots WHERE id = :sid"),
        {"sid": slot_id},
    )
    row_sd = r_sd.fetchone()
    if (
        row_sd
        and client_request_id is not None
        and created_by_trainer
        and is_slot_end_in_past_local(row_sd[0], row_sd[1])
    ):
        # Retro booking from request: skip client «trainer booked you» push for a past session.
        await session.execute(
            text("UPDATE bookings SET client_notified_trainer_booked_at = NOW() WHERE id = :id"),
            {"id": booking_id},
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
    # Client catalog caches GET /client/slots; pending bookings still use status=booked on slot.
    mile_flags: tuple[bool, bool] = (False, False)
    if created_by_trainer:
        ms, tip = await try_claim_first_booking_milestones(session, trainer_id)
        if ms or tip:
            await session.commit()
        mile_flags = (ms, tip)
    invalidate_slots_for_trainer(trainer_id)
    return (booking_id, mile_flags)


async def create_trainer_quick_booking(
    session: AsyncSession,
    trainer_id: int,
    slot_date: date,
    start_minutes: int,
    duration_minutes: int,
    client_id: int,
    service_id: int,
    *,
    arena_id: int | None = None,
    service_price_variant_id: int | None = None,
    is_sandbox: bool = False,
    allow_off_grid_interval: bool = True,
) -> tuple[int, int, bool, bool] | None:
    """
    Create an individual slot at date/start_minutes if needed, then a trainer-initiated booking.

    ``allow_off_grid_interval``: skip arena start grid (trainers may pick :15, :45, etc. in quick-book UI).

    ValueError is raised by ensure_individual_slot_for_quick_book (caller maps to HTTP 400).
    ServicePriceVariantRequired is re-raised after rollback.
    """
    from src.application.trainer_schedule_use_cases import ensure_individual_slot_for_quick_book

    slot_id = await ensure_individual_slot_for_quick_book(
        session,
        trainer_id,
        slot_date,
        start_minutes,
        duration_minutes,
        allow_off_grid_interval=allow_off_grid_interval,
        arena_id=arena_id,
    )
    try:
        booking_id, mile = await create_booking(
            session,
            slot_id=slot_id,
            trainer_id=trainer_id,
            client_id=client_id,
            service_id=service_id,
            client_comment=None,
            client_request_id=None,
            created_by_trainer=True,
            arena_id=arena_id,
            service_price_variant_id=service_price_variant_id,
            strict_service_price_variant=False,
            allow_overbook=False,
            is_sandbox=is_sandbox,
        )
    except ServicePriceVariantRequired:
        await session.rollback()
        raise
    if booking_id is None:
        await session.rollback()
        return None
    m1, m2 = mile
    return (booking_id, slot_id, m1, m2)


def _booking_interval_duration_minutes(start_time: time, end_time: time) -> int:
    """Length of [start, end) on the same calendar day (match slot interval when repeating)."""
    try:
        if start_time and end_time and hasattr(start_time, "hour") and hasattr(end_time, "hour"):
            delta = datetime.combine(date.today(), end_time) - datetime.combine(date.today(), start_time)
            return max(15, int(delta.total_seconds() // 60))
    except (TypeError, ValueError):
        pass
    return 45


async def can_trainer_repeat_booking_same_time_next_week(
    session: AsyncSession,
    *,
    trainer_id: int,
    slot_date: date,
    start_time: time,
    end_time: time | None = None,
) -> bool:
    """
    Whether «Записать на то же время» (+7 days) can succeed for this interval.
    Uses pending/confirmed occupancy vs capacity — not raw slots.status (stale 'booked' without bookings still allows repeat).
    """
    from src.application.recurring_use_cases import trainer_calendar_interval_clear

    slot_d = slot_date.date() if hasattr(slot_date, "date") else slot_date
    target_d = slot_d + timedelta(days=7)
    st = start_time.replace(second=0, microsecond=0) if hasattr(start_time, "replace") else start_time

    r = await session.execute(
        text(
            """
            SELECT id, capacity
            FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND start_time = :st
              AND status <> 'cancelled'
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "d": target_d, "st": st},
    )
    row = r.fetchone()
    if row:
        slot_id, cap = int(row[0]), max(1, int(row[1]))
        cnt = await _count_occupying_bookings(session, slot_id)
        return cnt < cap

    duration_minutes = _booking_interval_duration_minutes(st, end_time) if end_time is not None else 45
    start_minutes = st.hour * 60 + st.minute
    end_minutes = start_minutes + duration_minutes
    interval_end = time(end_minutes // 60, end_minutes % 60)
    return await trainer_calendar_interval_clear(session, trainer_id, target_d, st, interval_end)


def _map_link(latitude: object, longitude: object) -> str | None:
    """Build a stable external map URL from arena coordinates."""
    try:
        if latitude is None or longitude is None:
            return None
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return None
    return f"https://maps.google.com/?q={lat},{lon}"


def _arena_yandex_map_link(
    arena_lat: object,
    arena_lon: object,
    arena_address: str | None,
    arena_name: str | None,
) -> str | None:
    """Trainer-facing map deep link (same rules as post-confirm notifications)."""
    if arena_lat is not None and arena_lon is not None:
        try:
            return f"https://yandex.ru/maps/?pt={float(arena_lon)},{float(arena_lat)}&z=16"
        except (TypeError, ValueError):
            pass
    aa = (arena_address or "").strip()
    if aa:
        return f"https://yandex.ru/maps/?text={quote(aa)}"
    an = (arena_name or "").strip()
    if an:
        return f"https://yandex.ru/maps/?text={quote(an)}"
    return None


def _slot_wall_duration_minutes(start_t: object, end_t: object) -> int | None:
    """Calendar length of [start, end) on one day; None if times unusable."""
    try:
        if start_t is not None and end_t is not None and hasattr(start_t, "hour") and hasattr(end_t, "hour"):
            delta = datetime.combine(date.today(), end_t) - datetime.combine(date.today(), start_t)
            return max(0, int(delta.total_seconds() // 60))
    except (TypeError, ValueError):
        return None
    return None


async def trainer_repeat_booking_same_time_next_week(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> dict:
    """
    Trainer taps «same time next week» from wrap-up or after a session: book same client on slot_date+7
    at the same clock interval, creating an individual slot via create_trainer_quick_booking if needed.

    Accepts active bookings (``confirmed`` / ``pending``) — same rows as ``list_bookings_for_trainer_session_wrapup`` —
    plus ``completed`` so the action keeps working after the slot is closed.

    Returns:
        {"success": True, "new_booking_id": int, "slot_date": date, "start_time": time}
        {"success": False, "error": str, ...} — not_found, slot_booked, no_service,
        create_failed, price_tier_required, schedule_error (optional "message" for ValueError text).
    """
    r = await session.execute(
        text("""
            SELECT b.client_id, b.service_id, b.service_price_variant_id, b.arena_id,
                   s.slot_date, s.start_time, s.end_time, s.arena_id AS slot_arena_id
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid AND b.trainer_id = :tid
              AND b.status IN ('completed', 'confirmed', 'pending')
        """),
        {"bid": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return {"success": False, "error": "not_found"}

    client_id = int(row[0])
    service_id = int(row[1]) if row[1] is not None else None
    spv_id = int(row[2]) if row[2] is not None else None
    booking_arena = int(row[3]) if row[3] is not None else None
    slot_date_val = row[4]
    start_time = row[5]
    end_time = row[6]
    slot_arena_id = int(row[7]) if row[7] is not None else None

    if hasattr(slot_date_val, "date"):
        slot_d = slot_date_val.date()
    else:
        slot_d = slot_date_val

    st = start_time.replace(second=0, microsecond=0) if hasattr(start_time, "replace") else start_time
    target_date = slot_d + timedelta(days=7)

    if not await can_trainer_repeat_booking_same_time_next_week(
        session,
        trainer_id=trainer_id,
        slot_date=slot_d,
        start_time=st,
        end_time=end_time,
    ):
        return {"success": False, "error": "slot_booked"}

    if service_id is None:
        service_id = await get_first_service_id_for_trainer(session, trainer_id)
    if service_id is None:
        return {"success": False, "error": "no_service"}

    start_minutes = st.hour * 60 + st.minute
    duration_minutes = _booking_interval_duration_minutes(st, end_time)

    resolved_arena = booking_arena if booking_arena is not None else slot_arena_id

    try:
        result = await create_trainer_quick_booking(
            session,
            trainer_id,
            target_date,
            start_minutes,
            duration_minutes,
            client_id,
            service_id,
            arena_id=resolved_arena,
            service_price_variant_id=spv_id,
            allow_off_grid_interval=True,
        )
    except ServicePriceVariantRequired:
        return {"success": False, "error": "price_tier_required"}
    except ValueError as e:
        return {"success": False, "error": "schedule_error", "message": str(e)}

    if not result:
        return {"success": False, "error": "create_failed"}

    new_booking_id = result[0]
    await generate_reminders_for_booking(session, new_booking_id)
    r2 = await session.execute(
        text("""
            SELECT s.slot_date, s.start_time
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid
        """),
        {"bid": new_booking_id},
    )
    row2 = r2.fetchone()
    slot_out = row2[0] if row2 else target_date
    time_out = row2[1] if row2 else st
    return {
        "success": True,
        "new_booking_id": new_booking_id,
        "slot_date": slot_out,
        "start_time": time_out,
    }


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


def compute_booking_reminder_schedule(
    *,
    anchor_local: datetime,
    slot_date: date,
    start_time: time,
) -> list[tuple[str, datetime]]:
    """
    Planned client reminder send times (local wall clock), shared by persistence and trainer-facing copy.

    anchor_local: booking creation instant in DB, or "now" for a live preview right after booking.
    """
    local_tz = ZoneInfo(NOTIFICATION_TZ)
    if anchor_local.tzinfo is None:
        anchor = anchor_local.replace(tzinfo=timezone.utc).astimezone(local_tz)
    else:
        anchor = anchor_local.astimezone(local_tz)

    slot_dt_local = datetime.combine(slot_date, start_time).replace(tzinfo=local_tz)
    if slot_dt_local <= anchor:
        return []

    def effective_send_time(raw: datetime) -> datetime | None:
        """Drop night 00:00–07:59 by moving to same day _REMINDER_NIGHT_END_HOUR if still inside (anchor, slot)."""
        if raw <= anchor or raw >= slot_dt_local:
            return None
        if 0 <= raw.hour < _REMINDER_NIGHT_END_HOUR:
            snapped = datetime.combine(
                raw.date(),
                time(_REMINDER_NIGHT_END_HOUR, 0),
                tzinfo=local_tz,
            )
            if snapped <= anchor or snapped >= slot_dt_local:
                return None
            return snapped
        return raw

    planned: list[tuple[str, datetime]] = []

    def append_kind(kind: str, raw_candidate: datetime) -> None:
        send_at = effective_send_time(raw_candidate)
        if send_at is None:
            return
        for _, existing in planned:
            if abs((send_at - existing).total_seconds()) < _REMINDER_MIN_GAP_SEC:
                return
        planned.append((kind, send_at))

    t24 = slot_dt_local - timedelta(hours=24)
    t2 = slot_dt_local - timedelta(hours=2)

    if anchor.date() < slot_date:
        append_kind("before_24h", t24)
        append_kind("before_2h", t2)
        if not planned:
            eve = datetime.combine(
                slot_date - timedelta(days=1),
                time(_REMINDER_EVENING_PRIOR_HOUR, 0),
                tzinfo=local_tz,
            )
            append_kind("before_evening_prior", eve)
    else:
        if anchor < t2:
            append_kind("before_2h", t2)

    return planned


def format_reminder_plan_ru(plan: list[tuple[str, datetime]]) -> str:
    """Trainer-visible summary; must match compute_booking_reminder_schedule."""
    labels = {
        "before_24h": "за 24 ч",
        "before_2h": "за 2 ч",
        "before_evening_prior": "накануне вечером",
    }
    return ", ".join(f"{dt.strftime('%d.%m %H:%M')} ({labels.get(k, k)})" for k, dt in plan)


def _parse_merged_booking_ids(raw: object) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [int(x) for x in raw]
    if isinstance(raw, str):
        return [int(x) for x in json.loads(raw)]
    return []


async def resync_pending_reminders_for_client_day(
    session: AsyncSession,
    client_id: int,
    slot_date: date,
    *,
    do_commit: bool = True,
) -> None:
    """Drop pending reminders for this client's calendar day and insert merged rows (earliest slot drives timing)."""
    local_tz = ZoneInfo(NOTIFICATION_TZ)

    await session.execute(
        text(
            """
            UPDATE reminders r SET status = 'cancelled'
            WHERE r.status = 'pending'
              AND r.booking_id IN (
                SELECT b.id FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.client_id = :cid AND s.slot_date = :d
              )
            """
        ),
        {"cid": client_id, "d": slot_date},
    )

    r = await session.execute(
        text(
            f"""
            SELECT b.id, b.created_at, s.start_time
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.client_id = :cid AND s.slot_date = :d
              AND b.status NOT IN ({_REMINDER_SCHEDULE_EXCLUDED_SQL})
            ORDER BY s.start_time ASC, b.id ASC
            """
        ),
        {"cid": client_id, "d": slot_date},
    )
    rows = r.fetchall()
    if not rows:
        if do_commit:
            await session.commit()
        return

    primary_id = int(rows[0][0])
    extra_ids = [int(row[0]) for row in rows[1:]]

    created_locals: list[datetime] = []
    for _bid, created_at, _st in rows:
        if created_at.tzinfo is None:
            cl = created_at.replace(tzinfo=timezone.utc).astimezone(local_tz)
        else:
            cl = created_at.astimezone(local_tz)
        created_locals.append(cl)
    anchor_local = min(created_locals)
    first_start: time = rows[0][2]

    reminders = compute_booking_reminder_schedule(
        anchor_local=anchor_local,
        slot_date=slot_date,
        start_time=first_start,
    )

    tids = await list_family_access_telegram_ids_for_reminders(session, client_id)
    if not tids:
        if do_commit:
            await session.commit()
        return

    for kind, send_at in reminders:
        send_at_utc = send_at.astimezone(timezone.utc)
        for ctid in tids:
            if extra_ids:
                await session.execute(
                    text(
                        """
                        INSERT INTO reminders (booking_id, client_telegram_id, kind, send_at, status, merged_booking_ids)
                        VALUES (:bid, :ctid, :kind, :send_at, 'pending', CAST(:merged AS jsonb))
                        """
                    ),
                    {
                        "bid": primary_id,
                        "ctid": int(ctid),
                        "kind": kind,
                        "send_at": send_at_utc,
                        "merged": json.dumps(extra_ids),
                    },
                )
            else:
                await session.execute(
                    text(
                        """
                        INSERT INTO reminders (booking_id, client_telegram_id, kind, send_at, status)
                        VALUES (:bid, :ctid, :kind, :send_at, 'pending')
                        """
                    ),
                    {
                        "bid": primary_id,
                        "ctid": int(ctid),
                        "kind": kind,
                        "send_at": send_at_utc,
                    },
                )

    if do_commit:
        await session.commit()


async def format_trainer_reminder_plan_for_client_day(
    session: AsyncSession,
    *,
    client_id: int,
    slot_date: date,
    client_has_telegram: bool,
) -> str:
    """Trainer-facing copy; includes merge hint when the client has several bookings that day."""
    if not client_has_telegram:
        return "не запланированы: у клиента не привязан Telegram"
    local_tz = ZoneInfo(NOTIFICATION_TZ)
    now_local = datetime.now(local_tz)
    r = await session.execute(
        text(
            f"""
            SELECT COUNT(*)::int, MIN(s.start_time), MIN(b.created_at)
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.client_id = :cid AND s.slot_date = :d
              AND b.status NOT IN ({_REMINDER_SCHEDULE_EXCLUDED_SQL})
            """
        ),
        {"cid": client_id, "d": slot_date},
    )
    row = r.fetchone()
    if not row or int(row[0] or 0) == 0:
        return "запланируем автоматически после синхронизации слота"
    n_day = int(row[0])
    min_start = row[1]
    min_created = row[2]
    if min_start is None or min_created is None:
        return "запланируем автоматически по правилам напоминаний"
    slot_dt_local = datetime.combine(slot_date, min_start).replace(tzinfo=local_tz)
    if slot_dt_local <= now_local:
        return "не ставим: слот уже начался или в прошлом"
    if min_created.tzinfo is None:
        anchor = min_created.replace(tzinfo=timezone.utc).astimezone(local_tz)
    else:
        anchor = min_created.astimezone(local_tz)
    plan = compute_booking_reminder_schedule(
        anchor_local=anchor,
        slot_date=slot_date,
        start_time=min_start,
    )
    if not plan:
        return "не планируются: поздняя запись или нет окна до начала слота"
    base = format_reminder_plan_ru(plan)
    if n_day > 1:
        return f"объединённо для всех записей на этот день ({n_day}): {base}"
    return base


async def fetch_reminder_session_cards_map(
    session: AsyncSession,
    booking_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """
    Display payloads for client reminder Telegram (supports merged same-day rows).

    Reads live ``bookings.service_id`` / ``booking_price_cents`` so trainer edits before
    ``send_at`` appear in the standard reminder without resync or a separate client push.
    """
    if not booking_ids:
        return {}
    # Deduplicate while preserving order.
    ordered_unique: list[int] = list(dict.fromkeys(int(x) for x in booking_ids))
    r = await session.execute(
        text(
            """
            SELECT b.id, s.slot_date, s.start_time, s.end_time,
                   srv.name AS service_name,
                   COALESCE(b.booking_price_cents, spv.price_cents, ts.price_cents) AS price_cents_effective,
                   a.name AS arena_name, a.address AS arena_address, a.latitude, a.longitude,
                   t.telegram_id AS trainer_telegram_id,
                   b.trainer_id
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN services srv ON srv.id = b.service_id
            JOIN trainers t ON t.id = b.trainer_id
            LEFT JOIN trainer_service_price_variants spv ON spv.id = b.service_price_variant_id
            LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
            LEFT JOIN arenas a ON a.id = COALESCE(b.arena_id, s.arena_id)
            WHERE b.id = ANY(CAST(:ids AS INTEGER[]))
              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
            ORDER BY s.start_time ASC, b.id ASC
            """
        ),
        {"ids": ordered_unique},
    )
    out: dict[int, dict[str, Any]] = {}
    for row in r.fetchall():
        bid = int(row[0])
        st, et = row[2], row[3]
        out[bid] = {
            "booking_id": bid,
            "slot_date": row[1],
            "start_time": st,
            "end_time": et,
            "service_name": (row[4] or "").strip() or None,
            "booking_price_cents": int(row[5]) if row[5] is not None else None,
            "arena_name": (row[6] or "").strip() or None,
            "arena_address": (row[7] or "").strip() or None,
            "arena_latitude": row[8],
            "arena_longitude": row[9],
            "trainer_telegram_id": int(row[10]) if row[10] is not None else None,
            "trainer_id": int(row[11]) if row[11] is not None else None,
            "duration_minutes": _booking_interval_duration_minutes(st, et),
        }
    return out


async def generate_reminders_for_booking(session: AsyncSession, booking_id: int) -> None:
    """
    Rebuild same-day pending reminders for this client's calendar date (merged when several bookings).

    Sandbox bookings are silently skipped — a demo client must never receive automated reminders,
    even if a caller forgets the ``is_sandbox`` branch.
    """
    r = await session.execute(
        text(
            """
            SELECT b.is_sandbox, b.client_id, s.slot_date
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :id
            """
        ),
        {"id": booking_id},
    )
    row = r.fetchone()
    if not row:
        return
    if bool(row[0]):
        return
    client_row_id = int(row[1]) if row[1] is not None else None
    if client_row_id is None:
        return
    tids = await list_family_access_telegram_ids_for_reminders(session, client_row_id)
    if not tids:
        return
    slot_d = row[2]
    await resync_pending_reminders_for_client_day(session, client_row_id, slot_d, do_commit=True)


def _trainer_booked_notification_row_to_dict(row) -> dict:
    return {
        "booking_id": row[0],
        "client_telegram_id": row[1],
        "trainer_name": (row[2] or "Тренер").strip(),
        "trainer_id": int(row[3]) if row[3] is not None else None,
        "slot_date": row[4],
        "start_time": row[5],
        "end_time": row[6],
        "service_name": (row[7] or "").strip() or None,
        "booking_price_cents": row[8],
        "price_tier_label": price_tier_label_ru(row[9]),
        "arena_name": (row[10] or "").strip() or None,
        "arena_address": (row[11] or "").strip() or None,
        "map_link": _map_link(row[12], row[13]),
        "duration_minutes": _booking_interval_duration_minutes(row[5], row[6]),
    }


_TRAINER_BOOKED_NOTIFY_SELECT_SQL = """
    SELECT b.id, c.telegram_id,
           COALESCE(TRIM(CONCAT(tp.first_name, ' ', tp.last_name)), 'Тренер') AS trainer_name,
           b.trainer_id,
           s.slot_date, s.start_time, s.end_time,
           srv.name AS service_name,
           COALESCE(b.booking_price_cents, spv.price_cents, ts.price_cents) AS price_cents_effective,
           price_tier_kind,
           a.name AS arena_name, a.address AS arena_address,
           a.latitude, a.longitude
    FROM bookings b
    JOIN clients c ON c.id = b.client_id
    JOIN slots s ON s.id = b.slot_id
    JOIN trainers t ON t.id = b.trainer_id
    LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
    LEFT JOIN services srv ON srv.id = b.service_id
    LEFT JOIN trainer_service_price_variants spv ON spv.id = b.service_price_variant_id
    LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
    LEFT JOIN arenas a ON a.id = COALESCE(b.arena_id, s.arena_id)
"""


async def fetch_trainer_booked_notification_payload(
    session: AsyncSession,
    booking_id: int,
) -> dict | None:
    """Load display payload for «Вас записали…» after the booking row was claimed for send."""
    r = await session.execute(
        text(_TRAINER_BOOKED_NOTIFY_SELECT_SQL + " WHERE b.id = :bid"),
        {"bid": int(booking_id)},
    )
    row = r.fetchone()
    return _trainer_booked_notification_row_to_dict(row) if row else None


async def claim_client_trainer_booked_notification(
    session: AsyncSession,
    booking_id: int,
) -> bool:
    """
    Atomically reserve the client push so API and notification_service cannot both deliver it.
    """
    r = await session.execute(
        text("""
            UPDATE bookings b
            SET client_notified_trainer_booked_at = NOW()
            FROM clients c
            WHERE b.id = :id
              AND b.client_id = c.id
              AND b.client_notified_trainer_booked_at IS NULL
              AND b.notified_at IS NULL
              AND b.recurring_client_slot_id IS NULL
              AND c.telegram_id IS NOT NULL
              AND NOT b.is_sandbox
              AND NOT c.is_sandbox
              AND b.status = 'confirmed'
            RETURNING b.id
        """),
        {"id": int(booking_id)},
    )
    claimed = r.fetchone() is not None
    if claimed:
        await session.commit()
    return claimed


async def release_client_trainer_booked_notification_claim(
    session: AsyncSession,
    booking_id: int,
) -> None:
    """Undo claim when Telegram send failed so the backup loop can retry."""
    await session.execute(
        text("UPDATE bookings SET client_notified_trainer_booked_at = NULL WHERE id = :id"),
        {"id": int(booking_id)},
    )
    await session.commit()


async def get_pending_trainer_booked_notifications(
    session: AsyncSession,
    limit: int = 50,
    *,
    booking_id: int | None = None,
) -> list[dict]:
    """
    Client not yet sent the rich «Вас записали…» push (notification_service loop).

    Intended for **trainer-initiated** confirmed rows: ``notified_at`` stays NULL because the booking
    never entered the trainer_bot «new pending request» queue. Online client bookings get
    ``notified_at`` when that push is delivered; they must not also receive «Вас записали…» after
    «Ваша запись подтверждена!» — ``confirm_booking`` sets ``client_notified_trainer_booked_at``;
    ``notified_at IS NULL`` is an extra guard if that column was not backfilled on older deploys.

    Bookings created by recurring materialization (``recurring_client_slot_id`` set) are excluded: the
    client receives one CRM «постоянное время» message instead of one push per auto-booked week.
    """
    booking_filter_sql = "AND b.id = :bid" if booking_id is not None else ""
    r = await session.execute(
        text(
            _TRAINER_BOOKED_NOTIFY_SELECT_SQL
            + f"""
            WHERE b.client_notified_trainer_booked_at IS NULL
              AND b.notified_at IS NULL
              AND b.recurring_client_slot_id IS NULL
              AND c.telegram_id IS NOT NULL
              AND NOT b.is_sandbox -- Sandbox bookings never push to clients (demo identity).
              AND NOT c.is_sandbox
              AND b.status = 'confirmed' -- Only confirmed bookings get this push.
              {booking_filter_sql}
            LIMIT :lim
        """
        ),
        {"lim": limit, **({"bid": int(booking_id)} if booking_id is not None else {})},
    )
    return [_trainer_booked_notification_row_to_dict(row) for row in r.fetchall()]


async def mark_trainer_booked_notified(session: AsyncSession, booking_id: int) -> None:
    """Mark that we sent the client the 'trainer booked you' notification."""
    await claim_client_trainer_booked_notification(session, int(booking_id))


_PENDING_BOOKING_CONFIRMED_NOTIFY_SQL = """
    SELECT b.id, b.trainer_id, c.telegram_id, s.slot_date, s.start_time, s.end_time,
           srv.name AS service_name,
           COALESCE(b.booking_price_cents, spv.price_cents, ts.price_cents) AS price_cents_effective,
           price_tier_kind,
           a.name AS arena_name, a.address AS arena_address,
           a.latitude, a.longitude,
           (SELECT t.telegram_id FROM trainers t WHERE t.id = b.trainer_id) AS trainer_telegram_id
    FROM bookings b
    JOIN clients c ON c.id = b.client_id
    JOIN slots s ON s.id = b.slot_id
    JOIN trainers t ON t.id = b.trainer_id
    LEFT JOIN services srv ON srv.id = b.service_id
    LEFT JOIN trainer_service_price_variants spv ON spv.id = b.service_price_variant_id
    LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
    LEFT JOIN arenas a ON a.id = COALESCE(b.arena_id, s.arena_id)
    WHERE b.status = 'confirmed'
      AND b.client_notified_trainer_booked_at IS NULL
      AND b.notified_at IS NOT NULL
      AND c.telegram_id IS NOT NULL
      AND NOT b.is_sandbox
      AND NOT c.is_sandbox
    ORDER BY b.id
    LIMIT :lim
"""


async def get_pending_booking_confirmed_notifications(
    session: AsyncSession, limit: int = 50
) -> list[dict]:
    """
    Confirmed bookings (trainer confirmed a client's self-book request) whose «Ваша запись
    подтверждена!» push has not been delivered yet — retry target for
    ``run_booking_confirmed_notifier_loop``.

    ``confirm_booking`` no longer sets ``client_notified_trainer_booked_at`` itself: only a
    successful send does (see ``notify_client_booking_confirmed_by_trainer``). Without this
    retry a single failed send (rate limit, transient network blip) meant the client was
    silently never notified — the flag would still block both this push and the separate
    «Вас записали…» fallback forever. ``notified_at IS NOT NULL`` scopes this to bookings that
    went through the pending-request trainer-notify step, i.e. actually reached ``confirm_booking``.
    """
    r = await session.execute(
        text(_PENDING_BOOKING_CONFIRMED_NOTIFY_SQL),
        {"lim": limit},
    )
    out: list[dict] = []
    for row in r.fetchall():
        ptk = normalize_price_tier_kind(row[8])
        out.append(
            {
                "id": row[0],
                "trainer_id": int(row[1]),
                "client_telegram_id": row[2],
                "slot_date": row[3],
                "start_time": row[4],
                "end_time": row[5],
                "service_name": (row[6] or "").strip() or None,
                "booking_price_cents": row[7],
                "price_tier_label": price_tier_label_ru(ptk) if ptk else None,
                "arena_name": (row[9] or "").strip() or None,
                "arena_address": (row[10] or "").strip() or None,
                "map_link": _map_link(row[11], row[12]),
                "trainer_telegram_id": int(row[13]) if row[13] is not None else None,
                "first_booking_milestone": False,
            }
        )
    return out


async def mark_booking_confirmed_notified(session: AsyncSession, booking_id: int) -> None:
    """Mark that the «Ваша запись подтверждена!» push was delivered for this booking."""
    await session.execute(
        text(
            "UPDATE bookings SET client_notified_trainer_booked_at = NOW() "
            "WHERE id = :id AND client_notified_trainer_booked_at IS NULL"
        ),
        {"id": int(booking_id)},
    )
    await session.commit()


async def list_pending_reminders(session: AsyncSession, limit: int = 100) -> list[dict]:
    """
    Reminders due to send: status=pending, send_at <= now.
    Only for non-cancelled primary bookings.
    ``sessions`` lists one or more booking cards when same-day merges apply.
    """
    r = await session.execute(
        text("""
            SELECT r.id, r.client_telegram_id, r.kind, r.booking_id, r.merged_booking_ids
            FROM reminders r
            JOIN bookings b ON b.id = r.booking_id
            WHERE r.status = 'pending'
              AND r.send_at <= now()
              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
            ORDER BY r.send_at
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    if not rows:
        return []

    parsed: list[tuple[int, int, str, list[int]]] = []
    all_bids: set[int] = set()
    for row in rows:
        rid = int(row[0])
        ctg = int(row[1])
        kind = row[2] or ""
        bid = int(row[3])
        merged = _parse_merged_booking_ids(row[4])
        bids = [bid] + merged
        parsed.append((rid, ctg, kind, bids))
        for x in bids:
            all_bids.add(x)

    snap = await fetch_reminder_session_cards_map(session, list(all_bids))
    from src.application.booking_payment_notice import enrich_booking_dicts_with_expected_payment_class

    await enrich_booking_dicts_with_expected_payment_class(
        session,
        list(snap.values()),
        booking_id_key="booking_id",
    )
    out: list[dict[str, Any]] = []
    for rid, ctg, kind, bids in parsed:
        sessions = [snap[b] for b in bids if b in snap]
        if not sessions:
            continue
        head = sessions[0]
        trainer_tid = next((s["trainer_telegram_id"] for s in sessions if s.get("trainer_telegram_id")), None)
        out.append(
            {
                "id": rid,
                "client_telegram_id": ctg,
                "kind": kind,
                "sessions": sessions,
                "slot_date": head["slot_date"],
                "start_time": head["start_time"],
                "end_time": head["end_time"],
                "service_name": head.get("service_name"),
                "booking_price_cents": head.get("booking_price_cents"),
                "arena_name": head.get("arena_name"),
                "arena_address": head.get("arena_address"),
                "arena_latitude": head.get("arena_latitude"),
                "arena_longitude": head.get("arena_longitude"),
                "trainer_telegram_id": int(trainer_tid) if trainer_tid is not None else None,
            }
        )
    return out


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
              AND b.status <> :purged_status
        """),
        {"id": booking_id, "tid": trainer_id, "purged_status": BOOKING_STATUS_TRAINER_REMOVED},
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


async def get_booking_milestone_display_for_trainer(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> dict | None:
    """
    Read-only row for trainer milestone card (same projection as post-confirm notify payload).
    """
    r2 = await session.execute(
        text(
            """
            SELECT b.id, b.slot_id, b.client_id, c.telegram_id, COALESCE(c.phone, '') AS client_phone,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                   b.client_comment, b.created_at, s.slot_date, s.start_time, s.end_time,
                   COALESCE(NULLIF(TRIM(srv.name), ''), '') AS service_name,
                   COALESCE(b.booking_price_cents, ts.price_cents) AS price_cents_effective,
                   b.price_tier_kind,
                   ar.name AS arena_name,
                   ar.address AS arena_address,
                   ar.latitude AS arena_lat,
                   ar.longitude AS arena_lon,
                   ar.arena_city_name,
                   (SELECT t.telegram_id FROM trainers t WHERE t.id = b.trainer_id) AS trainer_telegram_id,
                   COALESCE(b.is_sandbox, false) AS is_sandbox,
                   COALESCE(c.is_sandbox, false) AS client_is_sandbox
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            JOIN services srv ON srv.id = b.service_id
            LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
            LEFT JOIN LATERAL (
                SELECT a.name, a.address, a.latitude, a.longitude, ac.name AS arena_city_name
                FROM arenas a
                LEFT JOIN cities ac ON ac.id = a.city_id
                WHERE a.id = COALESCE(
                    b.arena_id,
                    s.arena_id,
                    (SELECT t.primary_arena_id FROM trainers t WHERE t.id = b.trainer_id),
                    (SELECT MIN(ta.arena_id) FROM trainer_arenas ta WHERE ta.trainer_id = b.trainer_id)
                )
            ) ar ON true
            WHERE b.id = :bid AND b.trainer_id = :tid
              AND b.status <> :purged_status
            """
        ),
        {"bid": booking_id, "tid": trainer_id, "purged_status": BOOKING_STATUS_TRAINER_REMOVED},
    )
    row2 = r2.fetchone()
    if not row2:
        return None
    ptk = normalize_price_tier_kind(row2[13])
    tier_label = price_tier_label_ru(ptk) if ptk else None
    sn = (row2[11] or "").strip() if row2[11] else ""
    price_cents = row2[12]
    cn_raw = (row2[5] or "").strip() if row2[5] else ""
    an = (row2[14] or "").strip() if row2[14] else ""
    aa = (row2[15] or "").strip() if row2[15] else ""
    arena_lat, arena_lon = row2[16], row2[17]
    city_raw = (row2[18] or "").strip() if row2[18] else ""
    trainer_tid = row2[19]
    duration_minutes = _slot_wall_duration_minutes(row2[9], row2[10])
    map_link = _arena_yandex_map_link(arena_lat, arena_lon, aa or None, an or None)
    from src.application.booking_payment_notice import classify_booking_expected_payment_class

    expected_payment_class = await classify_booking_expected_payment_class(
        session, booking_id, trainer_id
    )
    return {
        "id": row2[0],
        "slot_id": row2[1],
        "client_id": row2[2],
        "client_telegram_id": row2[3],
        "client_phone": row2[4] or "",
        "client_name": cn_raw or None,
        "client_comment": row2[6],
        "created_at": row2[7],
        "slot_date": row2[8],
        "start_time": row2[9],
        "end_time": row2[10],
        "duration_minutes": duration_minutes,
        "service_name": sn or None,
        "booking_price_cents": int(price_cents) if price_cents is not None else None,
        "price_tier_label": tier_label,
        "arena_name": an or None,
        "arena_address": aa or None,
        "arena_city_name": city_raw or None,
        "map_link": map_link,
        "trainer_telegram_id": int(trainer_tid) if trainer_tid is not None else None,
        "is_sandbox": bool(row2[20]),
        "client_is_sandbox": bool(row2[21]),
        "expected_payment_class": expected_payment_class,
    }


async def get_trainer_booking_detail_payload(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> dict | None:
    """
    One booking for trainer detail API (GET /trainer/bookings/:id).
    Same core fields as hub list rows, plus ``booking_price_cents`` and ``price_tier_label`` when resolvable.
    Includes past slots and statuses (e.g. completed); excludes wrong trainer.
    """
    r = await session.execute(
        text(
            """
            SELECT b.id, b.slot_id, b.client_id,
                   c.telegram_id, c.telegram_username, c.phone, c.first_name AS client_first_name, c.last_name AS client_last_name,
                   b.client_comment, b.created_at,
                   s.slot_date, s.start_time, s.end_time,
                   (SELECT COUNT(*) + 1
                    FROM bookings b2
                    JOIN slots s2 ON s2.id = b2.slot_id
                    WHERE b2.trainer_id = b.trainer_id AND b2.client_id = b.client_id
                      AND b2.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                      AND (s2.slot_date < s.slot_date
                           OR (s2.slot_date = s.slot_date AND s2.start_time < s.start_time))
                   ) AS session_num,
                   COALESCE(b.status, 'confirmed') AS status,
                   srv.name AS services_str,
                   """
            + SQL_BOOKING_ARENA_DISPLAY
            + """ AS arenas_str,
                   b.service_id, b.service_price_variant_id,
                   """
            + SQL_BOOKING_RESOLVED_ARENA_ID
            + """ AS resolved_arena_id,
                   EXISTS (SELECT 1 FROM booking_problem_reports pr WHERE pr.booking_id = b.id) AS problem_reported,
                   EXISTS (SELECT 1 FROM booking_client_no_show cns WHERE cns.booking_id = b.id) AS client_no_show_recorded,
                   COALESCE(b.booking_price_cents, spv.price_cents, ts.price_cents) AS price_cents_effective,
                   COALESCE(spv.tier_kind, b.price_tier_kind) AS tier_kind_raw,
                   COALESCE(b.is_sandbox, false) AS is_sandbox
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            JOIN services srv ON srv.id = b.service_id
            LEFT JOIN trainer_service_price_variants spv ON spv.id = b.service_price_variant_id
            LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
            WHERE b.id = :bid AND b.trainer_id = :tid
              AND b.status <> :purged_status
            """
        ),
        {"bid": booking_id, "tid": trainer_id, "purged_status": BOOKING_STATUS_TRAINER_REMOVED},
    )
    row = r.fetchone()
    if not row:
        return None
    raw_tier = row[23] if len(row) > 23 else None
    ptk = normalize_price_tier_kind(raw_tier) if raw_tier else None
    tier_label = price_tier_label_ru(ptk) if ptk else None
    pc_eff = row[22] if len(row) > 22 else None
    return {
        "id": row[0],
        "slot_id": row[1],
        "client_id": int(row[2]) if row[2] is not None else None,
        "client_telegram_id": row[3],
        "client_telegram_username": (row[4] or "").strip() or None,
        "client_phone": row[5] or "",
        "client_first_name": row[6],
        "client_last_name": row[7],
        "client_comment": row[8],
        "created_at": row[9],
        "slot_date": row[10],
        "start_time": row[11],
        "end_time": row[12],
        "session_num": row[13],
        "status": (row[14] or "confirmed").strip(),
        "services_str": (row[15] or "").strip() or None,
        "arenas_str": _normalize_trainer_arenas_display(row[16] if len(row) > 16 else None),
        "service_id": int(row[17]) if row[17] is not None else None,
        "service_price_variant_id": int(row[18]) if row[18] is not None else None,
        "arena_id": int(row[19]) if row[19] is not None else None,
        "problem_reported": bool(row[20]),
        "client_no_show_recorded": bool(row[21]),
        "booking_price_cents": int(pc_eff) if pc_eff is not None else None,
        "price_tier_label": tier_label,
        "is_sandbox": bool(row[24]) if len(row) > 24 else False,
    }


# Trainer may change service/tariff/arena on individual bookings (not pass/cert-settled).
# Completed and past sessions are editable — stats read booking_price_cents snapshot at query time.
_BOOKING_SERVICE_EDIT_BLOCKED_STATUSES = frozenset({
    "cancelled",
    "declined",
    BOOKING_STATUS_TRAINER_REMOVED,
    BOOKING_STATUS_NO_SHOW,
    BOOKING_STATUS_PAYMENT_DISPUTE,
})


async def load_booking_service_edit_context(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> dict | None:
    """Booking + slot facts for service/tariff edit policy and PATCH handler."""
    r = await session.execute(
        text(
            """
            SELECT b.id, b.status, b.service_id, b.service_price_variant_id,
                   s.capacity, s.service_id AS slot_service_id, s.slot_date, s.end_time,
                   EXISTS (SELECT 1 FROM pass_redemptions pr WHERE pr.booking_id = b.id) AS has_pass,
                   EXISTS (SELECT 1 FROM certificate_booking_credits cbc WHERE cbc.booking_id = b.id) AS has_cert,
                   EXISTS (SELECT 1 FROM booking_problem_reports pr WHERE pr.booking_id = b.id) AS problem_reported,
                   EXISTS (SELECT 1 FROM booking_client_no_show cns WHERE cns.booking_id = b.id) AS client_no_show
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid AND b.trainer_id = :tid
              AND b.status <> :purged_status
            """
        ),
        {"bid": booking_id, "tid": trainer_id, "purged_status": BOOKING_STATUS_TRAINER_REMOVED},
    )
    row = r.fetchone()
    if not row:
        return None
    capacity = max(1, int(row[4] or 1))
    return {
        "booking_id": int(row[0]),
        "status": (row[1] or "").strip().lower(),
        "service_id": int(row[2]),
        "service_price_variant_id": int(row[3]) if row[3] is not None else None,
        "slot_capacity": capacity,
        "slot_service_id": int(row[5]) if row[5] is not None else None,
        "slot_date": row[6],
        "slot_end_time": row[7],
        "has_pass_redemption": bool(row[8]),
        "has_cert_credit": bool(row[9]),
        "problem_reported": bool(row[10]),
        "client_no_show_recorded": bool(row[11]),
    }


def booking_service_edit_policy(ctx: dict) -> dict:
    """
    UI/API hint: whether trainer can open service/tariff/arena editor on booking detail.
    Returns {allowed, reason, service_locked}.
    """
    st = ctx.get("status") or ""
    if st in _BOOKING_SERVICE_EDIT_BLOCKED_STATUSES:
        if st in ("cancelled", "declined", BOOKING_STATUS_TRAINER_REMOVED):
            return {
                "allowed": False,
                "reason": "Отменённую или отклонённую запись нельзя редактировать.",
                "service_locked": False,
            }
        return {
            "allowed": False,
            "reason": "Для этой записи услугу, тариф и площадку изменить нельзя.",
            "service_locked": False,
        }
    if ctx.get("has_pass_redemption") or ctx.get("has_cert_credit"):
        return {
            "allowed": False,
            "reason": "Нельзя менять: занятие уже списано с абонемента или сертификата.",
            "service_locked": False,
        }
    if ctx.get("problem_reported") or ctx.get("client_no_show_recorded"):
        return {
            "allowed": False,
            "reason": "После отчёта о проблеме услугу, тариф и площадку не меняют.",
            "service_locked": False,
        }
    capacity = max(1, int(ctx.get("slot_capacity") or 1))
    if capacity > 1:
        return {
            "allowed": False,
            "reason": "У группового слота услуга зафиксирована.",
            "service_locked": True,
        }
    if st not in ("pending", "confirmed", "completed"):
        return {
            "allowed": False,
            "reason": "Для этой записи услугу, тариф и площадку изменить нельзя.",
            "service_locked": False,
        }
    return {"allowed": True, "reason": None, "service_locked": False}


async def resolve_booking_service_edit_ui_flags(
    session: AsyncSession,
    trainer_id: int,
    ctx: dict | None,
) -> dict:
    """
    Extends ``booking_service_edit_policy`` with catalog-aware UI flags.

    ``can_edit_service`` / ``can_edit_tier`` are false when the trainer has nothing
    meaningful to pick (single service or single tier) — detail rows stay static.
    """
    empty = {
        "allowed": False,
        "reason": None,
        "service_locked": False,
        "can_edit_service": False,
        "can_edit_tier": False,
        "can_edit_arena": False,
    }
    if not ctx:
        return empty
    base = booking_service_edit_policy(ctx)
    out = {
        "allowed": bool(base.get("allowed")),
        "reason": base.get("reason"),
        "service_locked": bool(base.get("service_locked")),
        "can_edit_service": False,
        "can_edit_tier": False,
        "can_edit_arena": False,
    }
    if not out["allowed"]:
        return out
    r = await session.execute(
        text("SELECT COUNT(*)::int FROM trainer_services WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    svc_count = int(r.scalar() or 0)
    r_arena = await session.execute(
        text("SELECT COUNT(*)::int FROM trainer_arenas WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    arena_count = int(r_arena.scalar() or 0)
    can_edit_service = svc_count > 1
    tiers = await list_trainer_service_price_variants(
        session, trainer_id, int(ctx["service_id"])
    )
    can_edit_tier = len(tiers) > 1
    can_edit_arena = arena_count > 1
    if not can_edit_service and not can_edit_tier and not can_edit_arena:
        out["allowed"] = False
        return out
    out["can_edit_service"] = can_edit_service
    out["can_edit_tier"] = can_edit_tier
    out["can_edit_arena"] = can_edit_arena
    return out


async def update_trainer_booking_service(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
    service_id: int,
    service_price_variant_id: int | None = None,
) -> tuple[dict | None, str | None]:
    """
    Change service + price snapshot on an individual-slot booking.

    Intentionally silent for the client: no Telegram push, no ``generate_reminders_for_booking``.
    Pending reminders only store booking ids + send_at; ``list_pending_reminders`` loads
    service/price from the live ``bookings`` row at send time (``fetch_reminder_session_cards_map``).

    Returns (detail_payload, error_code). error_code is a machine key for HTTP mapping.
    """
    ctx = await load_booking_service_edit_context(session, booking_id, trainer_id)
    if not ctx:
        return (None, "not_found")
    policy = await resolve_booking_service_edit_ui_flags(session, trainer_id, ctx)
    if not policy.get("allowed"):
        code = "group_service_locked" if policy.get("service_locked") else "not_editable"
        return (None, code)
    r = await session.execute(
        text(
            """
            SELECT 1 FROM trainer_services
            WHERE trainer_id = :tid AND service_id = :sid
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    if not r.fetchone():
        return (None, "invalid_service")
    try:
        variant_id_resolved, booking_price_cents, price_tier_kind = await _resolve_service_booking_price(
            session,
            trainer_id,
            int(service_id),
            service_price_variant_id,
            strict_variant=True,
        )
    except ServicePriceVariantRequired:
        return (None, "tier_required")
    if service_price_variant_id is not None and variant_id_resolved is None:
        return (None, "invalid_tier")
    await session.execute(
        text(
            """
            UPDATE bookings
            SET service_id = :sid,
                service_price_variant_id = :vid,
                booking_price_cents = :bpc,
                price_tier_kind = :ptk
            WHERE id = :bid AND trainer_id = :tid
            """
        ),
        {
            "sid": int(service_id),
            "vid": variant_id_resolved,
            "bpc": booking_price_cents,
            "ptk": price_tier_kind,
            "bid": booking_id,
            "tid": trainer_id,
        },
    )
    await session.commit()
    detail = await get_trainer_booking_detail_payload(session, booking_id, trainer_id)
    return (detail, None)


async def update_trainer_booking_arena(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
    arena_id: int,
) -> tuple[dict | None, str | None]:
    """
    Change resolved venue on an individual-slot booking.

    Silent for the client — same contract as ``update_trainer_booking_service``:
    no Telegram push, reminders read live ``bookings.arena_id`` at send time.
    """
    ctx = await load_booking_service_edit_context(session, booking_id, trainer_id)
    if not ctx:
        return (None, "not_found")
    policy = booking_service_edit_policy(ctx)
    if not policy.get("allowed"):
        code = "group_service_locked" if policy.get("service_locked") else "not_editable"
        return (None, code)
    r = await session.execute(
        text(
            """
            SELECT 1 FROM trainer_arenas
            WHERE trainer_id = :tid AND arena_id = :aid
            """
        ),
        {"tid": trainer_id, "aid": int(arena_id)},
    )
    if not r.fetchone():
        return (None, "invalid_arena")
    await session.execute(
        text(
            """
            UPDATE bookings
            SET arena_id = :aid
            WHERE id = :bid AND trainer_id = :tid
            """
        ),
        {"aid": int(arena_id), "bid": booking_id, "tid": trainer_id},
    )
    await session.commit()
    detail = await get_trainer_booking_detail_payload(session, booking_id, trainer_id)
    return (detail, None)


async def list_bookings_for_trainer(
    session: AsyncSession,
    trainer_id: int,
    limit: int = 100,
) -> list[dict]:
    """
    Trainer hub: pending/confirmed bookings on open slots whose session end is still in the future.

    Session window compares slot_date + start/end as Europe/Minsk wall time (same as reminders / webapp).
    Rows where start_time <= now < end_time are sorted first (current slot), then by date/time.

    PRD E1: bookings stay listed until slot end, not merely until start_time.
    """
    # session_num = ordinal among all (past + upcoming) non-cancelled sessions for this trainer+client
    r = await session.execute(
        text("""
            WITH upcoming AS (
                SELECT b.id, b.slot_id, b.client_id,
                       c.telegram_id, c.telegram_username, c.phone, c.first_name AS client_first_name, c.last_name AS client_last_name,
                       b.client_comment, b.created_at,
                       s.slot_date, s.start_time, s.end_time,
                       (SELECT COUNT(*) + 1
                        FROM bookings b2
                        JOIN slots s2 ON s2.id = b2.slot_id
                        WHERE b2.trainer_id = b.trainer_id AND b2.client_id = b.client_id
                          AND b2.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                          AND (s2.slot_date < s.slot_date OR (s2.slot_date = s.slot_date AND s2.start_time < s.start_time))
                       ) AS session_num,
                       COALESCE(b.status, 'confirmed') AS status,
                       srv.name AS services_str,
                       """
            + SQL_BOOKING_ARENA_DISPLAY
            + """ AS arenas_str,
                       s.capacity AS slot_capacity,
                       (SELECT COUNT(*)::int FROM bookings bocc
                        WHERE bocc.slot_id = b.slot_id
                          AND bocc.status IN ('pending', 'confirmed')) AS slot_active_bookings,  -- hub group preview: occ/cap meter
                       CASE
                         WHEN """ + _SQL_SLOT_START_TS + """ <= CURRENT_TIMESTAMP
                          AND """ + _SQL_SLOT_END_TS + """ > CURRENT_TIMESTAMP
                         THEN 0
                         ELSE 1
                       END AS hub_sort_in_session,
                       (""" + _SQL_SLOT_START_TS + """ <= CURRENT_TIMESTAMP
                        AND """ + _SQL_SLOT_END_TS + """ > CURRENT_TIMESTAMP) AS hub_in_session,
                       EXISTS (SELECT 1 FROM booking_problem_reports pr WHERE pr.booking_id = b.id) AS problem_reported,
                       EXISTS (SELECT 1 FROM booking_client_no_show cns WHERE cns.booking_id = b.id) AS client_no_show_recorded,
                       (COALESCE(b.status, 'confirmed') = 'pending'
                        AND b.notified_at IS NULL
                        AND """
            + _SQL_PRIOR_TRAINER_NOTIFIED_BOOKING_COUNT
            + """ = 0) AS first_client_online_pending,
                       COALESCE(b.is_sandbox, false) AS is_sandbox,
                       b.service_id AS service_id
                FROM bookings b
                JOIN clients c ON c.id = b.client_id
                JOIN slots s ON s.id = b.slot_id
                JOIN services srv ON srv.id = b.service_id
                WHERE b.trainer_id = :tid
                  AND s.status IN ('available', 'booked')
                  AND b.status IN ('pending', 'confirmed')
                  AND """ + _SQL_SLOT_END_TS + """ > CURRENT_TIMESTAMP
            )
            SELECT id, slot_id, client_id, telegram_id, telegram_username, phone, client_first_name, client_last_name,
                   client_comment, created_at, slot_date, start_time, end_time,
                   session_num, services_str, arenas_str, status, slot_capacity, slot_active_bookings,
                   hub_in_session, problem_reported, client_no_show_recorded,
                   first_client_online_pending, is_sandbox, service_id
            FROM upcoming
            ORDER BY hub_sort_in_session ASC, slot_date ASC, start_time ASC
            LIMIT :lim
        """),
        {"tid": trainer_id, "lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "slot_id": row[1],
            "client_id": int(row[2]) if row[2] is not None else None,
            "client_telegram_id": row[3],
            "client_telegram_username": (row[4] or "").strip() or None,
            "client_phone": row[5] or "",
            "client_first_name": row[6],
            "client_last_name": row[7],
            "client_comment": row[8],
            "created_at": row[9],
            "slot_date": row[10],
            "start_time": row[11],
            "end_time": row[12],
            "session_num": row[13],
            "services_str": (row[14] or "").strip() or None,
            "arenas_str": _normalize_trainer_arenas_display(row[15] if len(row) > 15 else None),
            "status": (row[16] or "confirmed").strip() if len(row) > 16 else "confirmed",
            "slot_capacity": max(1, int(row[17])) if len(row) > 17 and row[17] is not None else 1,
            "slot_active_bookings": max(0, int(row[18])) if len(row) > 18 and row[18] is not None else 0,
            "hub_in_session": bool(row[19]) if len(row) > 19 else False,
            "problem_reported": bool(row[20]) if len(row) > 20 else False,
            "client_no_show_recorded": bool(row[21]) if len(row) > 21 else False,
            "first_client_online_pending": bool(row[22]) if len(row) > 22 else False,
            "is_sandbox": bool(row[23]) if len(row) > 23 else False,
            "service_id": int(row[24]) if len(row) > 24 and row[24] is not None else None,
        }
        for row in rows
    ]


# Hub/session summary: occurrences that «were on the calendar» (never cancelled/archived variants).
_SQL_HUB_BOOKING_STATUSES_SUMMARY = (
    "'pending', 'confirmed', 'completed', 'no_show', 'payment_dispute'"
)

_SQL_HUB_BOOKING_SCOPE = """b.trainer_id = :tid
                  AND s.status IN ('available', 'booked')
                  AND b.status IN (""" + _SQL_HUB_BOOKING_STATUSES_SUMMARY + """)
                  AND """ + _SQL_SLOT_END_TS + """ > CURRENT_TIMESTAMP"""

_SQL_HUB_BOOKING_SUMMARY_BASE = """b.trainer_id = :tid
                  AND s.status IN ('available', 'booked')
                  AND b.status IN (""" + _SQL_HUB_BOOKING_STATUSES_SUMMARY + """)"""


async def get_trainer_hub_session_summary_counts(session: AsyncSession, trainer_id: int) -> dict[str, int]:
    """
    Trainer-home summary tiles (today / calendar week Mon–Sun, Europe/Minsk).

    **Totals** («всего»): distinct slots with bookings on that calendar day / week —
    includes sessions that already **ended** (still «сегодня» / эта неделя).

    **Remaining** («осталось»): same scope but slot **start** is strictly in the future
    (`start > now`); in-progress and finished sessions do not count — matches hub tooltips.

    Status filter matches schedule «real sessions»: ``pending``, ``confirmed``, ``completed``,
    ``no_show``, ``payment_dispute`` (excludes cancelled / declined / ``trainer_removed``).
    This is **wider** than ``list_bookings_for_trainer`` (upcoming-only), so totals include
    past completed sessions on that calendar day/week.

    Counts **distinct slots** so group-capacity slots are one logical session.
    """
    sql = """
        WITH cal AS (
            SELECT
                (CURRENT_TIMESTAMP AT TIME ZONE '""" + NOTIFICATION_TZ + """')::date AS today_d,
                (CURRENT_TIMESTAMP AT TIME ZONE '""" + NOTIFICATION_TZ + """')::date
                    - (
                        (
                            EXTRACT(
                                ISODOW FROM (
                                    CURRENT_TIMESTAMP AT TIME ZONE '""" + NOTIFICATION_TZ + """'
                                )::date
                            )
                        )::int
                        - 1
                    ) AS week_monday_d
        )
        SELECT cal.today_d,
               cal.week_monday_d,
               cal.week_monday_d + 6 AS week_sunday_d,
               COALESCE((
                   SELECT COUNT(DISTINCT s.id)::int
                   FROM bookings b
                   JOIN slots s ON s.id = b.slot_id
                   JOIN clients c ON c.id = b.client_id
                   CROSS JOIN cal
                   WHERE """ + _SQL_HUB_BOOKING_SUMMARY_BASE + """
                     AND s.slot_date = cal.today_d
               ), 0) AS today_total,
               COALESCE((
                   SELECT COUNT(DISTINCT s.id)::int
                   FROM bookings b
                   JOIN slots s ON s.id = b.slot_id
                   JOIN clients c ON c.id = b.client_id
                   CROSS JOIN cal
                   WHERE """ + _SQL_HUB_BOOKING_SUMMARY_BASE + """
                     AND s.slot_date = cal.today_d
                     AND """ + _SQL_SLOT_START_TS + """ > CURRENT_TIMESTAMP
               ), 0) AS today_remaining,
               COALESCE((
                   SELECT COUNT(DISTINCT s.id)::int
                   FROM bookings b
                   JOIN slots s ON s.id = b.slot_id
                   JOIN clients c ON c.id = b.client_id
                   CROSS JOIN cal
                   WHERE """ + _SQL_HUB_BOOKING_SUMMARY_BASE + """
                     AND s.slot_date >= cal.week_monday_d
                     AND s.slot_date <= cal.week_monday_d + 6
               ), 0) AS week_total,
               COALESCE((
                   SELECT COUNT(DISTINCT s.id)::int
                   FROM bookings b
                   JOIN slots s ON s.id = b.slot_id
                   JOIN clients c ON c.id = b.client_id
                   CROSS JOIN cal
                   WHERE """ + _SQL_HUB_BOOKING_SUMMARY_BASE + """
                     AND s.slot_date >= cal.week_monday_d
                     AND s.slot_date <= cal.week_monday_d + 6
                     AND """ + _SQL_SLOT_START_TS + """ > CURRENT_TIMESTAMP
               ), 0) AS week_remaining
        FROM cal
    """
    r = await session.execute(text(sql), {"tid": trainer_id})
    row = r.fetchone()
    if not row:
        return {
            "today_total": 0,
            "today_remaining": 0,
            "week_total": 0,
            "week_remaining": 0,
        }
    return {
        "today_total": int(row[3] or 0),
        "today_remaining": int(row[4] or 0),
        "week_total": int(row[5] or 0),
        "week_remaining": int(row[6] or 0),
    }


def _booking_row_calendar_date(val: Any) -> date | None:
    """Normalize slot_date from DB/driver to a calendar date (Europe/Minsk wall date)."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if type(val) is date:
        return val
    return None


def _booking_slot_start_datetime(b: dict, tz: ZoneInfo) -> datetime | None:
    """Local start instant for hub row (Europe/Minsk wall clock)."""
    sd = _booking_row_calendar_date(b.get("slot_date"))
    st_raw = b.get("start_time")
    if sd is None or st_raw is None:
        return None
    if isinstance(st_raw, datetime):
        tm = st_raw.time()
    elif isinstance(st_raw, time):
        tm = st_raw
    else:
        return None
    try:
        return datetime.combine(sd, tm, tzinfo=tz)
    except (TypeError, ValueError):
        return None


def dedupe_trainer_hub_booking_rows(bookings: Sequence[dict]) -> list[dict]:
    """
    One logical «занятие» per hub row: merge group-slot participants (matches trainer-home-main.js).
    """
    seen_slot: dict[int, dict] = {}
    out: list[dict] = []
    for b in bookings:
        cap = max(1, int(b.get("slot_capacity") or 1))
        sid = b.get("slot_id")
        if cap > 1 and sid is not None:
            sk = int(sid)
            if sk in seen_slot:
                prev = seen_slot[sk]
                if str(b.get("status") or "").strip().lower() == "pending":
                    prev["status"] = "pending"
                if b.get("first_client_online_pending"):
                    prev["first_client_online_pending"] = True
                continue
            row = dict(b)
            seen_slot[sk] = row
            out.append(row)
            continue
        out.append(dict(b))
    return out


def compute_hub_bookings_summary(bookings: Sequence[dict]) -> dict[str, dict[str, int]]:
    """
    Pure-Python hub summary from an in-memory row list (tests / local tooling).

    **Totals** count every row after slot dedupe (including sessions that already ended today / this week).
    **Remaining** counts slots whose start is strictly in the future in Minsk (same rule as SQL).

    Production ``GET /trainer/bookings`` uses :func:`get_trainer_hub_session_summary_counts`; that list is
    usually upcoming-only — then Python totals match the capped list, not necessarily full-calendar totals.
    """
    tz = ZoneInfo(NOTIFICATION_TZ)
    now = datetime.now(tz)
    today_minsk = now.date()

    rows = dedupe_trainer_hub_booking_rows(bookings)
    today_rows = [
        b for b in rows if _booking_row_calendar_date(b.get("slot_date")) == today_minsk
    ]

    def remaining_for(booking_rows: list[dict]) -> int:
        n = 0
        for b in booking_rows:
            st_dt = _booking_slot_start_datetime(b, tz)
            if st_dt is not None and now < st_dt:
                n += 1
        return n

    return {
        "today_sessions": {
            "total": len(today_rows),
            "remaining": remaining_for(today_rows),
        },
        "week_sessions": {
            "total": len(rows),
            "remaining": remaining_for(rows),
        },
    }


async def get_trainer_group_slot_hub(
    session: AsyncSession,
    trainer_id: int,
    slot_id: int,
) -> dict | None:
    """
    One group slot (capacity > 1): occupancy + per-booking rows for hub / schedule group modal.
    Returns None if slot missing, wrong trainer, or capacity is 1.
    """
    r = await session.execute(
        text(
            """
            SELECT s.slot_date, s.start_time, s.end_time, s.capacity, s.service_id
            FROM slots s
            WHERE s.id = :sid AND s.trainer_id = :tid AND s.status IN ('available', 'booked')
            """
        ),
        {"sid": slot_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    cap = max(1, int(row[3] or 1))
    if cap <= 1:
        return None

    r2 = await session.execute(
        text(
            """
            SELECT b.id, COALESCE(b.status, 'confirmed'),
                   c.first_name, c.last_name, c.phone,
                   COALESCE(b.is_sandbox, false)
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            WHERE b.slot_id = :sid AND b.trainer_id = :tid
              AND b.status IN ('pending', 'confirmed')
            ORDER BY b.id
            """
        ),
        {"sid": slot_id, "tid": trainer_id},
    )
    booking_rows = r2.fetchall()
    entries: list[dict] = []
    for br in booking_rows:
        st_raw = (br[1] or "confirmed").strip()
        fn = (br[2] or "").strip() if br[2] else ""
        ln = (br[3] or "").strip() if br[3] else ""
        ph = (br[4] or "").strip() if br[4] else ""
        name = " ".join(p for p in (fn, ln) if p).strip()
        entries.append(
            {
                "booking_id": int(br[0]),
                "client_preview": name or ph or "Клиент",
                "status": st_raw,
                "is_sandbox": bool(br[5]),
            }
        )

    occ = len(entries)
    spots_left = max(0, cap - occ)
    sd = row[0]
    st_t = row[1]
    et_t = row[2]
    svc_id = row[4]

    def _hm(t: object) -> str:
        if hasattr(t, "strftime"):
            return t.strftime("%H:%M")  # type: ignore[union-attr]
        return str(t)[:5]

    return {
        "slot_id": slot_id,
        "slot_date": sd.isoformat() if hasattr(sd, "isoformat") else str(sd),
        "start_time": _hm(st_t),
        "end_time": _hm(et_t),
        "capacity": cap,
        "active_bookings": occ,
        "spots_left": spots_left,
        "service_id": int(svc_id) if svc_id is not None else None,
        "bookings": entries,
    }


async def active_booking_summaries_by_slot_for_trainer_range(
    session: AsyncSession,
    trainer_id: int,
    from_date: date,
    to_date: date,
) -> dict[int, dict]:
    """
    For slots with at least one booking in range: slot_id -> display fields for schedule UI.
    Group slots: aggregated client_preview and booking_count; booking_id is first id for drill-down.
    ``bookings`` lists pending/confirmed rows for the group hub UI (booking_id, client_preview, status).
    Slot-level ``has_sandbox_booking`` flags sandbox / trial bookings for UI badges.
    ``booking_service_id`` is catalog ``services.id`` from the first booking row (schedule UI accent when slot has no service_id).
    ``client_id`` / ``client_telegram_*`` / ``client_phone`` come from the first booking row (schedule mini-cards «Написать»).
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
                   c.first_name AS client_first_name, c.last_name AS client_last_name, c.phone AS client_phone,
                   s.capacity,
                   COALESCE(b.is_sandbox, false),
                   b.service_id,
                   c.id AS client_row_id,
                   c.telegram_id AS client_telegram_id,
                   NULLIF(TRIM(COALESCE(c.telegram_username, '')), '') AS client_telegram_username
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN clients c ON c.id = b.client_id
            JOIN services srv ON srv.id = b.service_id
            WHERE b.trainer_id = :tid
              AND s.slot_date >= :from_d AND s.slot_date <= :to_d
              AND s.status IN ('available', 'booked')
              AND b.status IN ('pending', 'confirmed', 'completed', 'no_show', 'payment_dispute')
            ORDER BY b.slot_id, b.id
        """),
        {"tid": trainer_id, "from_d": from_date, "to_d": to_date},
    )
    groups: dict[int, list] = defaultdict(list)
    for row in r.fetchall():
        groups[int(row[0])].append(row)

    out: dict[int, dict] = {}
    for slot_id, rows in groups.items():
        first_row = rows[0]
        capacity = max(1, int(first_row[8]))
        has_sandbox_booking = any(bool(r_[9]) for r_ in rows)
        booking_catalog_sid = (
            int(first_row[10]) if len(first_row) > 10 and first_row[10] is not None else None
        )
        previews: list[str] = []
        for r_ in rows:
            fn = (r_[5] or "").strip() if r_[5] else ""
            ln = (r_[6] or "").strip() if r_[6] else ""
            ph = (r_[7] or "").strip() if r_[7] else ""
            name = " ".join(p for p in (fn, ln) if p).strip()
            previews.append(name or ph or "Клиент")
        n = len(rows)
        if n <= 2:
            client_preview = ", ".join(previews)
        else:
            client_preview = ", ".join(previews[:2]) + f" (+{n - 2})"
        booking_entries: list[dict] = []
        for r_ in rows:
            st_raw = (r_[2] or "confirmed").strip()
            if st_raw.lower() not in ("pending", "confirmed", "no_show", "payment_dispute"):
                continue
            bid = int(r_[1])
            fn = (r_[5] or "").strip() if r_[5] else ""
            ln = (r_[6] or "").strip() if r_[6] else ""
            ph = (r_[7] or "").strip() if r_[7] else ""
            name = " ".join(p for p in (fn, ln) if p).strip()
            booking_entries.append(
                {
                    "booking_id": bid,
                    "client_preview": name or ph or "Клиент",
                    "status": st_raw,
                    "is_sandbox": bool(r_[9]),
                }
            )
        out[slot_id] = {
            "booking_id": int(first_row[1]),
            "status": (first_row[2] or "confirmed").strip(),
            "services_str": ((first_row[3] or "").strip() or None),
            "venue_label": _normalize_trainer_arenas_display(first_row[4]),
            "client_preview": client_preview,
            "booking_count": n,
            "capacity": capacity,
            "has_sandbox_booking": has_sandbox_booking,
            "bookings": booking_entries,
            # Catalog services.id from the primary booking row (schedule accent when slot.service_id is NULL).
            "booking_service_id": booking_catalog_sid,
            "client_id": int(first_row[11]) if len(first_row) > 11 and first_row[11] is not None else None,
            "client_telegram_id": int(first_row[12]) if len(first_row) > 12 and first_row[12] is not None else None,
            "client_telegram_username": ((first_row[13] or "").strip() or None) if len(first_row) > 13 else None,
            "client_phone": ((first_row[7] or "").strip() or None),
        }
    return out


def normalize_trainer_client_list_tier_filter(tier: str | None) -> str | None:
    """``child`` | ``adult`` | ``pair`` for trainer clients list filter."""
    if tier is None:
        return None
    t = str(tier).strip().lower()
    if t in ("child", "adult", "pair"):
        return t
    return None


def _trainer_client_list_tier_where_sql(tier: str | None) -> str:
    if tier == PRICE_TIER_CHILD:
        return " AND LOWER(TRIM(lbt.price_tier_kind)) = 'child' "
    if tier == PRICE_TIER_ADULT:
        return " AND LOWER(TRIM(lbt.price_tier_kind)) = 'adult' "
    if tier == "pair":
        return (
            " AND LOWER(TRIM(lbt.price_tier_kind)) IN "
            "('two_children', 'two_adults', 'adult_and_child') "
        )
    return ""


def _trainer_client_list_filter_sql(
    *,
    recurring_only: bool,
    in_bot: bool | None,
    min_bookings: int | None,
    has_active_pass: bool | None,
    tier: str | None,
) -> tuple[str, dict[str, object]]:
    """Build WHERE fragments; omit unset filters (asyncpg cannot bind untyped NULL)."""
    clauses = ["TRUE"]
    params: dict[str, object] = {}
    if recurring_only:
        clauses.append("COALESCE(rc.n, 0) > 0")
    if in_bot is not None:
        clauses.append("(c.telegram_id IS NOT NULL) = :in_bot")
        params["in_bot"] = bool(in_bot)
    if min_bookings is not None:
        clauses.append("COALESCE(bc.n, 0) >= :min_bookings")
        params["min_bookings"] = int(min_bookings)
    if has_active_pass is not None:
        clauses.append("(ap.client_id IS NOT NULL) = :has_active_pass")
        params["has_active_pass"] = bool(has_active_pass)
    tier_sql = _trainer_client_list_tier_where_sql(tier)
    if tier_sql.strip():
        clauses.append(tier_sql.strip().removeprefix("AND").strip())
    return "WHERE " + " AND ".join(clauses), params


async def list_trainer_clients(
    session: AsyncSession,
    trainer_id: int,
    limit: int = 50,
    *,
    recurring_only: bool = False,
    in_bot: bool | None = None,
    min_bookings: int | None = None,
    has_active_pass: bool | None = None,
    tier: str | None = None,
) -> list[dict]:
    """
    Distinct clients linked to this trainer: any non-cancelled booking or explicit CRM roster row.
    Sorted by most recent non-cancelled slot when present; roster-only clients follow by add time.
    last_date/last_start = last *completed* session only; NULL if none yet.
    """
    tier_norm = normalize_trainer_client_list_tier_filter(tier)
    has_filters = any(
        [
            recurring_only,
            in_bot is not None,
            min_bookings is not None,
            has_active_pass is not None,
            tier_norm is not None,
        ]
    )
    if has_filters or recurring_only:
        cap = max(50, int(limit))
        lim = min(cap, 500)
    else:
        lim = limit
    filter_sql, filter_params = _trainer_client_list_filter_sql(
        recurring_only=recurring_only,
        in_bot=in_bot,
        min_bookings=min_bookings,
        has_active_pass=has_active_pass,
        tier=tier_norm,
    )
    r = await session.execute(
        text(
            """
            WITH eligible_clients AS (
                SELECT DISTINCT client_id FROM (
                    SELECT b.client_id AS client_id
                    FROM bookings b
                    WHERE b.trainer_id = :tid
                      AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                    UNION
                    SELECT r.client_id
                    FROM trainer_client_roster r
                    WHERE r.trainer_id = :tid
                ) u
            ),
            recurring_counts AS (
                SELECT client_id, COUNT(*)::int AS n
                FROM recurring_client_slots
                WHERE trainer_id = :tid AND status = 'active'
                GROUP BY client_id
            ),
            booking_counts AS (
                SELECT b.client_id, COUNT(*)::int AS n
                FROM bookings b
                WHERE b.trainer_id = :tid
                  AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                GROUP BY b.client_id
            ),
            last_booking_tier AS (
                SELECT DISTINCT ON (b.client_id)
                    b.client_id,
                    b.price_tier_kind
                FROM bookings b
                WHERE b.trainer_id = :tid
                  AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                ORDER BY b.client_id, b.created_at DESC NULLS LAST, b.id DESC
            ),
            active_pass_clients AS (
                SELECT DISTINCT pi.client_id
                FROM pass_instances pi
                JOIN trainer_pass_products tpp ON tpp.id = pi.pass_product_id
                WHERE tpp.trainer_id = :tid
                  AND pi.status = 'active'
                  AND pi.sessions_remaining > 0
            ),
            last_completed_per_client AS (
                SELECT
                    b.client_id,
                    s.slot_date AS last_date,
                    s.start_time AS last_start,
                    ROW_NUMBER() OVER (
                        PARTITION BY b.client_id
                        ORDER BY s.slot_date DESC, s.start_time DESC NULLS LAST
                    ) AS rn
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid
                  AND b.status = 'completed'
            ),
            recent_booking_per_client AS (
                SELECT
                    b.client_id,
                    s.slot_date AS sort_date,
                    s.start_time AS sort_start,
                    ROW_NUMBER() OVER (
                        PARTITION BY b.client_id
                        ORDER BY s.slot_date DESC, s.start_time DESC NULLS LAST
                    ) AS rn
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid
                  AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
            ),
            roster_touch AS (
                SELECT client_id, created_at AS roster_added_at
                FROM trainer_client_roster
                WHERE trainer_id = :tid
            )
            SELECT
                c.id,
                c.telegram_id,
                c.telegram_username,
                c.phone,
                c.first_name,
                c.last_name,
                c.middle_name,
                lc.last_date,
                lc.last_start,
                (SELECT MIN(s2.slot_date)
                 FROM bookings b2
                 JOIN slots s2 ON s2.id = b2.slot_id
                 WHERE b2.client_id = c.id
                   AND b2.trainer_id = :tid
                   AND b2.status NOT IN ('cancelled', 'declined', 'trainer_removed')) AS first_date,
                c.is_sandbox,
                COALESCE(rc.n, 0) AS recurring_slots_count,
                COALESCE(bc.n, 0) AS bookings_count,
                (c.telegram_id IS NOT NULL) AS in_bot,
                lbt.price_tier_kind AS last_price_tier_kind,
                (ap.client_id IS NOT NULL) AS has_active_pass
            FROM eligible_clients e
            JOIN clients c ON c.id = e.client_id
            LEFT JOIN recent_booking_per_client rb ON rb.client_id = c.id AND rb.rn = 1
            LEFT JOIN last_completed_per_client lc ON lc.client_id = c.id AND lc.rn = 1
            LEFT JOIN roster_touch ro ON ro.client_id = c.id
            LEFT JOIN recurring_counts rc ON rc.client_id = c.id
            LEFT JOIN booking_counts bc ON bc.client_id = c.id
            LEFT JOIN last_booking_tier lbt ON lbt.client_id = c.id
            LEFT JOIN active_pass_clients ap ON ap.client_id = c.id
            """
            + filter_sql
            + """
            ORDER BY c.is_sandbox ASC,
                     rb.sort_date DESC NULLS LAST,
                     rb.sort_start DESC NULLS LAST,
                     ro.roster_added_at DESC NULLS LAST,
                     c.id DESC
            LIMIT :lim
            """
        ),
        {"tid": trainer_id, "lim": lim, **filter_params},
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
            "middle_name": row[6] or "",
            "last_date": row[7],
            "last_start": row[8],
            "first_date": row[9],
            "is_sandbox": bool(row[10]),
            "recurring_slots_count": int(row[11] or 0),
            "bookings_count": int(row[12] or 0),
            "in_bot": bool(row[13]),
            "last_price_tier_kind": normalize_price_tier_kind(row[14]),
            "has_active_pass": bool(row[15]),
        }
        for row in rows
    ]


def _last_meeting_phrase_ru(*, today: date, last_session_date: date) -> str:
    """Short phrase for «how long since last session» (avoid «0 дн. назад»)."""
    days = (today - last_session_date).days
    if days <= 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    return f"{days} дн. назад"


def _reason_line_for_fill_slots_invite(
    *,
    today: date,
    has_upcoming_booking: bool,
    last_session_date: date | None,
) -> str:
    if not has_upcoming_booking:
        if last_session_date is not None:
            ago = _last_meeting_phrase_ru(today=today, last_session_date=last_session_date)
            return f"Без следующей записи · последняя встреча {ago}"
        return "Без следующей записи · в истории ещё не было занятий"
    if last_session_date is not None:
        ago = _last_meeting_phrase_ru(today=today, last_session_date=last_session_date)
        return f"Уже есть будущая запись · можно напомнить про окна · последний раз {ago}"
    return "Уже есть будущая запись · мягкое напоминание про свободные слоты"


async def list_trainer_fill_slots_invite_candidates(
    session: AsyncSession,
    trainer_id: int,
    limit: int = 3,
    *,
    include_with_upcoming: bool = False,
) -> list[dict]:
    """
    Clients for hub «напомнить про слоты»: CRM scope (booking, explicit roster, or active/trial group), Telegram linked.

    By default excludes clients who already have a future pending/confirmed session (focused nudge).
    With ``include_with_upcoming=True``, returns everyone in scope (still sorted: без записи first).
    """
    cap = 250 if include_with_upcoming else 10
    lim = max(1, min(int(limit), cap))
    upcoming_filter_sql = "" if include_with_upcoming else "WHERE has_upcoming_flag = 0"
    # Sandbox isolation: drop demo identity at every CTE source — bookings (b.is_sandbox), roster
    # join, and the final clients filter. A sandbox client never has telegram_id, but we still belt-
    # and-suspenders the filter via c.is_sandbox to guard against future schema drift.
    r = await session.execute(
        text(
            """
            WITH rel AS (
                SELECT DISTINCT q.client_id
                FROM (
                    SELECT b.client_id
                    FROM bookings b
                    WHERE b.trainer_id = :tid
                      AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                      AND NOT b.is_sandbox
                    UNION
                    SELECT m.client_id
                    FROM training_group_members m
                    INNER JOIN training_groups g ON g.id = m.training_group_id
                    WHERE g.trainer_id = :tid
                      AND m.status IN ('active', 'trial')
                    UNION
                    SELECT r.client_id
                    FROM trainer_client_roster r
                    WHERE r.trainer_id = :tid
                ) q
            ),
            has_upcoming AS (
                SELECT DISTINCT b.client_id
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid
                  AND b.status IN ('pending', 'confirmed')
                  AND NOT b.is_sandbox
                  AND s.status IN ('available', 'booked')
                  AND """
            + _SQL_SLOT_END_TS
            + """
                  > CURRENT_TIMESTAMP
            ),
            last_sess AS (
                SELECT
                    b.client_id,
                    MAX("""
            + _SQL_SLOT_START_TS
            + """) AS last_ts,
                    MAX(s.slot_date) AS last_date
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid
                  AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                  AND NOT b.is_sandbox
                GROUP BY b.client_id
            ),
            scored AS (
                SELECT
                    c.id AS client_id,
                    COALESCE(NULLIF(TRIM(c.first_name), ''), '') AS first_name,
                    COALESCE(NULLIF(TRIM(c.last_name), ''), '') AS last_name,
                    c.telegram_id,
                    COALESCE(NULLIF(TRIM(c.telegram_username), ''), '') AS telegram_username,
                    CASE WHEN hu.client_id IS NULL THEN 0 ELSE 1 END AS has_upcoming_flag,
                    ls.last_date,
                    ls.last_ts
                FROM rel r
                INNER JOIN clients c ON c.id = r.client_id
                    AND c.telegram_id IS NOT NULL
                    AND NOT c.is_sandbox
                LEFT JOIN has_upcoming hu ON hu.client_id = c.id
                LEFT JOIN last_sess ls ON ls.client_id = c.id
            )
            SELECT
                client_id,
                first_name,
                last_name,
                telegram_id,
                telegram_username,
                has_upcoming_flag,
                last_date
            FROM scored
            """
            + upcoming_filter_sql
            + """
            ORDER BY has_upcoming_flag ASC,
                     last_ts ASC NULLS LAST,
                     client_id ASC
            LIMIT :lim
            """
        ),
        {"tid": trainer_id, "lim": lim},
    )
    rows = r.fetchall()
    today = date.today()
    out: list[dict] = []
    for row in rows:
        cid = int(row[0])
        fn = (row[1] or "").strip()
        ln = (row[2] or "").strip()
        tid_raw = row[3]
        uname = (row[4] or "").strip()
        has_up = int(row[5] or 0) == 1
        last_d = row[6]
        last_date: date | None
        if last_d is None:
            last_date = None
        elif hasattr(last_d, "isoformat"):
            last_date = last_d  # type: ignore[assignment]
        else:
            last_date = date.fromisoformat(str(last_d))
        display = (fn + " " + ln).strip() or "Клиент"
        out.append(
            {
                "id": cid,
                "first_name": fn,
                "last_name": ln,
                "display_name": display,
                "telegram_username": uname or None,
                "has_telegram": tid_raw is not None,
                "has_upcoming_booking": has_up,
                "last_session_date": last_date.isoformat() if last_date else None,
                "reason_line": _reason_line_for_fill_slots_invite(
                    today=today,
                    has_upcoming_booking=has_up,
                    last_session_date=last_date,
                ),
            }
        )
    return out


async def get_trainer_slot_for_mass_client_invite(
    session: AsyncSession, trainer_id: int, slot_id: int
) -> dict | None:
    """
    Slot must belong to trainer, not cancelled, end in the future, and have at least one free seat
    (for mass «запишитесь на это окно» client pushes).
    """
    tid = int(trainer_id)
    sid = int(slot_id)
    r = await session.execute(
        text(
            """
            SELECT s.id, s.slot_date, s.start_time, s.end_time, s.capacity, s.status,
                   NULLIF(TRIM(sv.name), '') AS service_name,
                   NULLIF(TRIM(ar.name), '') AS arena_name,
                   (
                       SELECT COUNT(*)::int FROM bookings b
                       WHERE b.slot_id = s.id AND b.status IN ('pending', 'confirmed')
                   ) AS occ
            FROM slots s
            LEFT JOIN services sv ON sv.id = s.service_id
            LEFT JOIN arenas ar ON ar.id = s.arena_id
            WHERE s.id = :sid AND s.trainer_id = :tid
            """
        ),
        {"sid": sid, "tid": tid},
    )
    row = r.fetchone()
    if not row:
        return None
    status = (row[5] or "").strip().lower()
    if status == "cancelled":
        return None
    cap = max(1, int(row[4] or 1))
    occ = int(row[8] or 0)
    if occ >= cap:
        return None
    slot_date = row[1]
    end_t = row[3]
    if slot_date is None or end_t is None:
        return None
    if is_slot_end_in_past_local(slot_date, end_t):
        return None
    svc = row[6]
    arn = row[7]
    return {
        "id": sid,
        "trainer_id": tid,
        "slot_date": slot_date,
        "start_time": row[2],
        "end_time": end_t,
        "capacity": cap,
        "occupancy": occ,
        "service_name": (str(svc).strip() if svc is not None else None) or None,
        "arena_name": (str(arn).strip() if arn is not None else None) or None,
    }


async def count_trainer_fill_slots_invite_candidates(session: AsyncSession, trainer_id: int) -> int:
    """Count clients matching ``list_trainer_fill_slots_invite_candidates`` (telegram + no upcoming).

    Mirrors ``list_trainer_fill_slots_invite_candidates`` sandbox isolation: demo identity is
    dropped at the bookings CTE and at the final clients join.
    """
    r = await session.execute(
        text(
            """
            WITH rel AS (
                SELECT DISTINCT q.client_id
                FROM (
                    SELECT b.client_id
                    FROM bookings b
                    WHERE b.trainer_id = :tid
                      AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                      AND NOT b.is_sandbox
                    UNION
                    SELECT m.client_id
                    FROM training_group_members m
                    INNER JOIN training_groups g ON g.id = m.training_group_id
                    WHERE g.trainer_id = :tid
                      AND m.status IN ('active', 'trial')
                    UNION
                    SELECT r.client_id
                    FROM trainer_client_roster r
                    WHERE r.trainer_id = :tid
                ) q
            ),
            has_upcoming AS (
                SELECT DISTINCT b.client_id
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid
                  AND b.status IN ('pending', 'confirmed')
                  AND NOT b.is_sandbox
                  AND s.status IN ('available', 'booked')
                  AND """
            + _SQL_SLOT_END_TS
            + """
                  > CURRENT_TIMESTAMP
            ),
            last_sess AS (
                SELECT
                    b.client_id,
                    MAX("""
            + _SQL_SLOT_START_TS
            + """) AS last_ts,
                    MAX(s.slot_date) AS last_date
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid
                  AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                  AND NOT b.is_sandbox
                GROUP BY b.client_id
            ),
            scored AS (
                SELECT
                    c.id AS client_id,
                    CASE WHEN hu.client_id IS NULL THEN 0 ELSE 1 END AS has_upcoming_flag,
                    ls.last_ts
                FROM rel r
                INNER JOIN clients c ON c.id = r.client_id
                    AND c.telegram_id IS NOT NULL
                    AND NOT c.is_sandbox
                LEFT JOIN has_upcoming hu ON hu.client_id = c.id
                LEFT JOIN last_sess ls ON ls.client_id = c.id
            )
            SELECT COUNT(*)::int
            FROM scored
            WHERE has_upcoming_flag = 0
            """
        ),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    return int(row[0] or 0) if row else 0


async def link_trainer_client_roster(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> bool:
    """Idempotent CRM link so the client appears under this trainer before any booking."""
    r = await session.execute(
        text(
            """
            INSERT INTO trainer_client_roster (trainer_id, client_id)
            VALUES (:tid, :cid)
            ON CONFLICT (trainer_id, client_id) DO NOTHING
            RETURNING id
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    return r.fetchone() is not None


async def trainer_client_roster_link_exists(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> bool:
    """True when this client is already explicitly present in trainer's CRM roster."""
    r = await session.execute(
        text(
            """
            SELECT 1
            FROM trainer_client_roster
            WHERE trainer_id = :tid AND client_id = :cid
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    return r.fetchone() is not None


async def trainer_has_access_to_client(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> bool:
    """
    True if this trainer may manage this client (non-cancelled booking, roster link, or active/trial group member).
    Same rule as get_trainer_client_for_card visibility.
    """
    r = await session.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM bookings b
                WHERE b.trainer_id = :tid AND b.client_id = :cid
                  AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
            )
            OR EXISTS (
                SELECT 1 FROM training_group_members m
                INNER JOIN training_groups g ON g.id = m.training_group_id
                WHERE g.trainer_id = :tid AND m.client_id = :cid
                  AND m.status IN ('active', 'trial')
            )
            OR EXISTS (
                SELECT 1 FROM trainer_client_roster r
                WHERE r.trainer_id = :tid AND r.client_id = :cid
            )
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    row = r.fetchone()
    return bool(row and row[0])


async def get_trainer_client_for_card(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> dict | None:
    """
    One client row for the trainer mini-app card when opened by id (e.g. from a training group).
    Allowed if booking (non-cancelled), roster link, or active/trial group member.
    last_date/last_start refer to the latest *completed* session only (NULL if none).
    """
    r = await session.execute(
        text(
            """
            SELECT
              (
                EXISTS (
                  SELECT 1 FROM bookings b
                  WHERE b.trainer_id = :tid AND b.client_id = :cid
                    AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                )
                OR EXISTS (
                  SELECT 1 FROM training_group_members m
                  INNER JOIN training_groups g ON g.id = m.training_group_id
                  WHERE g.trainer_id = :tid AND m.client_id = :cid
                    AND m.status IN ('active', 'trial')
                )
                OR EXISTS (
                  SELECT 1 FROM trainer_client_roster r2
                  WHERE r2.trainer_id = :tid AND r2.client_id = :cid
                )
              ) AS allowed,
              c.id,
              c.telegram_id,
              c.telegram_username,
              c.phone,
              c.first_name,
              c.last_name,
              c.middle_name,
              c.is_sandbox
            FROM clients c
            WHERE c.id = :cid
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    row = r.fetchone()
    if not row or not row[0]:
        return None
    r2 = await session.execute(
        text(
            """
            SELECT
              (SELECT s.slot_date
               FROM bookings b
               JOIN slots s ON s.id = b.slot_id
               WHERE b.client_id = :cid AND b.trainer_id = :tid
                 AND b.status = 'completed'
               ORDER BY s.slot_date DESC, s.start_time DESC NULLS LAST
               LIMIT 1) AS last_date,
              (SELECT s.start_time
               FROM bookings b
               JOIN slots s ON s.id = b.slot_id
               WHERE b.client_id = :cid AND b.trainer_id = :tid
                 AND b.status = 'completed'
               ORDER BY s.slot_date DESC, s.start_time DESC NULLS LAST
               LIMIT 1) AS last_start,
              (SELECT MIN(s2.slot_date)
               FROM bookings b2
               JOIN slots s2 ON s2.id = b2.slot_id
               WHERE b2.client_id = :cid AND b2.trainer_id = :tid
                 AND b2.status NOT IN ('cancelled', 'declined', 'trainer_removed')) AS first_date
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    d = r2.fetchone()
    return {
        "id": row[1],
        "telegram_id": row[2],
        "telegram_username": row[3] or "",
        "phone": row[4] or "",
        "first_name": row[5] or "",
        "last_name": row[6] or "",
        "middle_name": row[7] or "",
        "is_sandbox": bool(row[8]),
        "last_date": d[0] if d else None,
        "last_start": d[1] if d else None,
        "first_date": d[2] if d else None,
    }


async def patch_trainer_client_identity_for_card(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    *,
    updates: dict[str, Any],
) -> dict | None:
    """
    Update client first/middle/last name from trainer CRM card (subset of keys in updates).
    Empty strings normalize to NULL; values are capped at 64 chars (DB column).
    """
    if not await trainer_has_access_to_client(session, trainer_id, client_id):
        return None
    norm: dict[str, str | None] = {}
    for key in ("first_name", "last_name", "middle_name"):
        if key not in updates:
            continue
        raw = updates[key]
        if raw is None:
            norm[key] = None
        elif isinstance(raw, str):
            s = raw.strip()
            norm[key] = s[:64] if s else None
        else:
            raise ValueError(f"invalid_identity_field:{key}")
    if not norm:
        return await get_trainer_client_for_card(session, trainer_id, client_id)
    assigns = []
    bind: dict[str, Any] = {"cid": client_id}
    for key, val in norm.items():
        pname = "_" + key
        assigns.append(f"{key} = :{pname}")
        bind[pname] = val
    await session.execute(
        text(f"UPDATE clients SET {', '.join(assigns)}, updated_at = NOW() WHERE id = :cid"),
        bind,
    )
    await session.commit()
    return await get_trainer_client_for_card(session, trainer_id, client_id)


async def get_trainer_client_last_booking_service_defaults(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> tuple[int | None, int | None, int | None, str | None]:
    """Last non-cancelled booking by created_at: service_id, price variant (or tier_kind-derived), arena, raw tier kind."""
    r = await session.execute(
        text(
            """
            SELECT
                b.service_id,
                COALESCE(
                    b.service_price_variant_id,
                    (
                        SELECT spv.id
                        FROM trainer_service_price_variants spv
                        WHERE spv.trainer_id = b.trainer_id
                          AND spv.service_id = b.service_id
                          AND b.price_tier_kind IS NOT NULL
                          AND (
                            spv.tier_kind = b.price_tier_kind
                            OR LOWER(TRIM(spv.tier_kind)) = LOWER(TRIM(b.price_tier_kind))
                          )
                        ORDER BY spv.sort_order NULLS LAST, spv.id
                        LIMIT 1
                    )
                ) AS effective_variant_id,
                """
            + SQL_BOOKING_RESOLVED_ARENA_ID
            + """ AS resolved_arena_id,
                b.price_tier_kind AS last_price_tier_kind
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.client_id = :cid
              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
            ORDER BY b.created_at DESC NULLS LAST, b.id DESC
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    row = r.fetchone()
    if not row:
        return None, None, None, None
    sid_raw, vid_raw, aid_raw, tier_raw = row[0], row[1], row[2], row[3]
    sid = int(sid_raw) if sid_raw is not None else None
    vid = int(vid_raw) if vid_raw is not None else None
    aid = int(aid_raw) if aid_raw is not None else None
    tier_kind: str | None = None
    if tier_raw is not None:
        ts = str(tier_raw).strip()
        tier_kind = ts if ts else None
    return sid, vid, aid, tier_kind


async def get_trainer_client_booking_defaults_from_booking_id(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    booking_id: int,
) -> tuple[int | None, int | None, int | None, str | None] | None:
    """
    Presets from one booking row (trainer wrap-up / «Записать снова» after session).
    None if booking missing, wrong trainer/client, or status is cancelled/declined/trainer_removed.
    """
    r = await session.execute(
        text(
            """
            SELECT
                b.service_id,
                COALESCE(
                    b.service_price_variant_id,
                    (
                        SELECT spv.id
                        FROM trainer_service_price_variants spv
                        WHERE spv.trainer_id = b.trainer_id
                          AND spv.service_id = b.service_id
                          AND b.price_tier_kind IS NOT NULL
                          AND (
                            spv.tier_kind = b.price_tier_kind
                            OR LOWER(TRIM(spv.tier_kind)) = LOWER(TRIM(b.price_tier_kind))
                          )
                        ORDER BY spv.sort_order NULLS LAST, spv.id
                        LIMIT 1
                    )
                ) AS effective_variant_id,
                """
            + SQL_BOOKING_RESOLVED_ARENA_ID
            + """ AS resolved_arena_id,
                b.price_tier_kind AS last_price_tier_kind
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid
              AND b.trainer_id = :tid AND b.client_id = :cid
              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
            LIMIT 1
            """
        ),
        {"bid": int(booking_id), "tid": int(trainer_id), "cid": int(client_id)},
    )
    row = r.fetchone()
    if not row:
        return None
    sid_raw, vid_raw, aid_raw, tier_raw = row[0], row[1], row[2], row[3]
    sid = int(sid_raw) if sid_raw is not None else None
    vid = int(vid_raw) if vid_raw is not None else None
    aid = int(aid_raw) if aid_raw is not None else None
    tier_kind: str | None = None
    if tier_raw is not None:
        ts = str(tier_raw).strip()
        tier_kind = ts if ts else None
    return sid, vid, aid, tier_kind


async def get_trainer_client_last_booking_price_variant_for_service(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    service_id: int,
) -> int | None:
    """
    Latest non-cancelled booking for this trainer+client+service: effective price-variant id
    (service_price_variant_id or tier_kind-derived row), newest by booking created_at.
    """
    r = await session.execute(
        text(
            """
            SELECT COALESCE(
                b.service_price_variant_id,
                (
                    SELECT spv.id
                    FROM trainer_service_price_variants spv
                    WHERE spv.trainer_id = b.trainer_id
                      AND spv.service_id = b.service_id
                      AND b.price_tier_kind IS NOT NULL
                      AND (
                        spv.tier_kind = b.price_tier_kind
                        OR LOWER(TRIM(spv.tier_kind)) = LOWER(TRIM(b.price_tier_kind))
                      )
                    ORDER BY spv.sort_order NULLS LAST, spv.id
                    LIMIT 1
                )
            ) AS effective_variant_id
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.client_id = :cid AND b.service_id = :sid
              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
            ORDER BY b.created_at DESC NULLS LAST, b.id DESC
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "cid": client_id, "sid": service_id},
    )
    row = r.fetchone()
    if not row or row[0] is None:
        return None
    return int(row[0])


async def get_trainer_client_latest_booking_service_id(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> int | None:
    """Service from latest *created* non-cancelled booking (same recency rule as booking-defaults), not by slot date."""
    r = await session.execute(
        text(
            """
            SELECT b.service_id
            FROM bookings b
            WHERE b.trainer_id = :tid AND b.client_id = :cid
              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
            ORDER BY b.created_at DESC NULLS LAST, b.id DESC
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    row = r.fetchone()
    return int(row[0]) if row and row[0] is not None else None


async def list_bookings_for_client(
    session: AsyncSession,
    client_telegram_id: int,
    limit: int = 50,
    *,
    acting_client_id: int | None = None,
) -> list[dict]:
    """List client's active (upcoming) bookings only — pending, not completed/cancelled; slot end still in the future.

    Slot end uses Europe/Minsk wall time (same as trainer hub / reminders), not DB session timezone.
    Arena: booking.arena_id, then slot.arena_id, then trainer primary / MIN(trainer_arenas); not arbitrary ta row.

    ``acting_client_id``: when set (e.g. guardian/child profile from ``X-Profile-Id``), list that
    profile's bookings instead of resolving the account's own row from ``client_telegram_id``.
    """
    cid = (
        int(acting_client_id)
        if acting_client_id is not None
        else await get_client_id_by_telegram_id(session, int(client_telegram_id))
    )
    if cid is None:
        return []
    r = await session.execute(
        text(
            """
            SELECT b.id, b.slot_id, b.trainer_id, b.service_id, b.client_comment, b.status,
                   s.slot_date, s.start_time, s.end_time,
                   (EXTRACT(EPOCH FROM (s.end_time - s.start_time)) / 60)::int AS duration_minutes,
                   COALESCE(NULLIF(TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, '')), ''), 'Тренер') AS trainer_name,
                   t.telegram_id AS trainer_telegram_id,
                   NULLIF(TRIM(COALESCE(t.telegram_username, '')), '') AS trainer_telegram_username,
                   NULLIF(TRIM(COALESCE(p.phone, '')), '') AS trainer_phone,
                   srv.name AS service_name,
                   b.price_tier_kind,
                   a.name AS arena_name,
                   a.address AS arena_address,
                   a.latitude AS arena_lat,
                   a.longitude AS arena_lon,
                   COALESCE(b.booking_price_cents, spv.price_cents, ts.price_cents) AS price_cents,
                   NULLIF(TRIM(COALESCE(ts.client_notice, '')), '') AS service_client_notice,
                   (""" + _SQL_SLOT_START_TS + """ <= CURRENT_TIMESTAMP
                     AND """ + _SQL_SLOT_END_TS + """ > CURRENT_TIMESTAMP) AS hub_in_session,
                   (""" + SQL_BOOKING_RESOLVED_ARENA_ID + """) AS resolved_arena_id,
                   b.service_price_variant_id,
                   p.city_id AS trainer_city_id
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            JOIN trainers t ON t.id = b.trainer_id
            JOIN services srv ON srv.id = b.service_id
            LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
            LEFT JOIN trainer_service_price_variants spv ON spv.id = b.service_price_variant_id
            LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
            LEFT JOIN LATERAL (
                SELECT a2.name, a2.address, a2.latitude, a2.longitude
                FROM arenas a2
                WHERE a2.id = ("""
            + SQL_BOOKING_RESOLVED_ARENA_ID
            + """)
            ) a ON true
            WHERE b.client_id = :cid
              AND s.status IN ('available', 'booked')
              AND b.status IN ('pending', 'confirmed')
              AND """ + _SQL_SLOT_END_TS + """ > CURRENT_TIMESTAMP
            ORDER BY s.slot_date ASC, s.start_time ASC
            LIMIT :lim
        """
        ),
        {"cid": int(cid), "lim": limit},
    )
    rows = r.fetchall()
    out = []
    for row in rows:
        arena_name = (row[16] or "").strip() if row[16] else ""
        arena_address = (row[17] or "").strip() if row[17] else ""
        lat, lon = row[18], row[19]
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
            "price_tier_kind": normalize_price_tier_kind(row[15]),
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
            "price_cents": int(row[20]) if row[20] is not None else None,
            "service_client_notice": (row[21] or "").strip() or None,
            "hub_in_session": bool(row[22]),
            "arena_id": int(row[23]) if row[23] is not None else None,
            "service_price_variant_id": int(row[24]) if row[24] is not None else None,
            "trainer_city_id": int(row[25]) if row[25] is not None else None,
        })
    from src.application.booking_payment_notice import enrich_booking_dicts_with_expected_payment_class

    await enrich_booking_dicts_with_expected_payment_class(session, out)
    return out


async def list_booking_history_for_client(
    session: AsyncSession,
    client_telegram_id: int,
    *,
    offset: int = 0,
    limit: int = 20,
    trainer_id: int | None = None,
    acting_client_id: int | None = None,
) -> tuple[list[dict], bool]:
    """List client's booking history — the complement of ``list_bookings_for_client``.

    Partition, not a literal "slot in the past": any booking NOT in the upcoming set
    (terminal status, OR still pending/confirmed but its slot already ended) belongs here.
    A booking cancelled for a future slot must not vanish from both lists — it shows up
    here immediately rather than waiting for the slot to pass. Newest first. Sandbox excluded.
    Returns ``(rows, has_more)``; fetches one extra row to detect a next page without a COUNT(*).

    ``acting_client_id``: see ``list_bookings_for_client``.
    """
    cid = (
        int(acting_client_id)
        if acting_client_id is not None
        else await get_client_id_by_telegram_id(session, int(client_telegram_id))
    )
    if cid is None:
        return [], False
    lim = max(1, min(int(limit), 100))
    off = max(0, int(offset))
    trainer_clause = " AND b.trainer_id = :trainer_id" if trainer_id is not None else ""
    r = await session.execute(
        text(
            """
            SELECT b.id, b.slot_id, b.trainer_id, b.service_id, b.client_comment, b.status,
                   s.slot_date, s.start_time, s.end_time,
                   (EXTRACT(EPOCH FROM (s.end_time - s.start_time)) / 60)::int AS duration_minutes,
                   COALESCE(NULLIF(TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, '')), ''), 'Тренер') AS trainer_name,
                   t.telegram_id AS trainer_telegram_id,
                   NULLIF(TRIM(COALESCE(t.telegram_username, '')), '') AS trainer_telegram_username,
                   NULLIF(TRIM(COALESCE(p.phone, '')), '') AS trainer_phone,
                   srv.name AS service_name,
                   b.price_tier_kind,
                   a.name AS arena_name,
                   a.address AS arena_address,
                   a.latitude AS arena_lat,
                   a.longitude AS arena_lon,
                   COALESCE(b.booking_price_cents, spv.price_cents, ts.price_cents) AS price_cents,
                   NULLIF(TRIM(COALESCE(ts.client_notice, '')), '') AS service_client_notice,
                   false AS hub_in_session,
                   (""" + SQL_BOOKING_RESOLVED_ARENA_ID + """) AS resolved_arena_id,
                   b.service_price_variant_id,
                   p.city_id AS trainer_city_id
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            JOIN trainers t ON t.id = b.trainer_id
            JOIN services srv ON srv.id = b.service_id
            LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
            LEFT JOIN trainer_service_price_variants spv ON spv.id = b.service_price_variant_id
            LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
            LEFT JOIN LATERAL (
                SELECT a2.name, a2.address, a2.latitude, a2.longitude
                FROM arenas a2
                WHERE a2.id = ("""
            + SQL_BOOKING_RESOLVED_ARENA_ID
            + """)
            ) a ON true
            WHERE b.client_id = :cid
              AND NOT b.is_sandbox
              AND (
                b.status NOT IN ('pending', 'confirmed')
                OR """ + _SQL_SLOT_END_TS + """ <= CURRENT_TIMESTAMP
              )"""
            + trainer_clause
            + """
            ORDER BY s.slot_date DESC, s.start_time DESC, b.id DESC
            OFFSET :off
            LIMIT :lim
        """
        ),
        {"cid": int(cid), "off": off, "lim": lim + 1, **({"trainer_id": int(trainer_id)} if trainer_id is not None else {})},
    )
    rows = r.fetchall()
    has_more = len(rows) > lim
    rows = rows[:lim]
    out = []
    for row in rows:
        arena_name = (row[16] or "").strip() if row[16] else ""
        arena_address = (row[17] or "").strip() if row[17] else ""
        lat, lon = row[18], row[19]
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
            "price_tier_kind": normalize_price_tier_kind(row[15]),
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
            "price_cents": int(row[20]) if row[20] is not None else None,
            "service_client_notice": (row[21] or "").strip() or None,
            "hub_in_session": bool(row[22]),
            "arena_id": int(row[23]) if row[23] is not None else None,
            "service_price_variant_id": int(row[24]) if row[24] is not None else None,
            "trainer_city_id": int(row[25]) if row[25] is not None else None,
        })
    from src.application.booking_payment_notice import enrich_booking_dicts_with_expected_payment_class

    await enrich_booking_dicts_with_expected_payment_class(session, out)
    return out, has_more


async def list_client_booking_trainer_options(
    session: AsyncSession,
    client_telegram_id: int,
    *,
    acting_client_id: int | None = None,
) -> list[dict]:
    """Distinct trainers the client has any (non-sandbox) booking with — source for the trainer chips.

    Deliberately NOT ``client_trainer_edges``: an edge can exist from a "saved" trainer with zero
    bookings, which would render a chip with nothing behind it. Ordered by most recent activity.

    ``acting_client_id``: see ``list_bookings_for_client``.
    """
    cid = (
        int(acting_client_id)
        if acting_client_id is not None
        else await get_client_id_by_telegram_id(session, int(client_telegram_id))
    )
    if cid is None:
        return []
    r = await session.execute(
        text(
            """
            SELECT b.trainer_id,
                   COALESCE(NULLIF(TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, '')), ''), 'Тренер') AS trainer_name,
                   MAX(""" + _SQL_SLOT_START_TS + """) AS last_slot_start
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
            WHERE b.client_id = :cid
              AND NOT b.is_sandbox
            GROUP BY b.trainer_id, trainer_name
            ORDER BY last_slot_start DESC
            """
        ),
        {"cid": int(cid)},
    )
    return [
        {"trainer_id": int(row[0]), "trainer_name": (row[1] or "").strip() or "Тренер"}
        for row in r.fetchall()
        if row[0] is not None
    ]


# Hub «последняя запись» / primary fallback: includes client-cancelled visits (still «мой тренер»).
_SQL_PRIMARY_LATEST_BOOKING_STATUSES = (
    "'pending', 'confirmed', 'completed', 'no_show', 'cancelled'"
)
# Upcoming primary: only visits that are still on the calendar (not cancelled/declined).
_SQL_PRIMARY_UPCOMING_BOOKING_STATUSES = (
    "'pending', 'confirmed', 'completed', 'no_show'"
)


async def client_latest_booking_primary_candidate(
    session: AsyncSession,
    client_telegram_id: int,
) -> tuple[int | None, int | None]:
    """
    Trainer (and service_id) for the client's chronologically latest slot start — past or upcoming.

    Includes ``cancelled`` bookings so hub primary does not jump to «saved» after the client cancels.
    Used for «Сохранённые», rebook hints, and hub «Мой тренер» when there is no upcoming booking.
    """
    return await _client_booking_primary_candidate_query(
        session, client_telegram_id, upcoming_only=False
    )


async def client_upcoming_booking_primary_candidate(
    session: AsyncSession,
    client_telegram_id: int,
) -> tuple[int | None, int | None]:
    """
    Same as latest booking candidate but only slots that have not ended yet.
    Hub «Мой тренер» must not stick to a trainer after roster detach / past-only history.
    """
    return await _client_booking_primary_candidate_query(
        session, client_telegram_id, upcoming_only=True
    )


async def _client_booking_primary_candidate_query(
    session: AsyncSession,
    client_telegram_id: int,
    *,
    upcoming_only: bool,
) -> tuple[int | None, int | None]:
    cid = await get_client_id_by_telegram_id(session, int(client_telegram_id))
    if cid is None:
        return None, None
    upcoming_clause = (
        (" AND " + _SQL_SLOT_END_TS + " > CURRENT_TIMESTAMP") if upcoming_only else ""
    )
    status_sql = (
        _SQL_PRIMARY_UPCOMING_BOOKING_STATUSES
        if upcoming_only
        else _SQL_PRIMARY_LATEST_BOOKING_STATUSES
    )
    r = await session.execute(
        text(
            f"""
            SELECT b.trainer_id, b.service_id
            FROM bookings b
            INNER JOIN slots s ON s.id = b.slot_id
            WHERE b.client_id = :cid
              AND b.status IN ({status_sql})
              AND COALESCE(TRIM(LOWER(COALESCE(s.status, ''))), '') <> 'cancelled'
            """
            + upcoming_clause
            + """
            ORDER BY """
            + _SQL_SLOT_START_TS
            + """ DESC NULLS LAST,
                     b.id DESC
            LIMIT 1
            """
        ),
        {"cid": int(cid)},
    )
    row = r.fetchone()
    if not row or row[0] is None:
        return None, None
    tid = int(row[0])
    sid_raw = row[1]
    sid = int(sid_raw) if sid_raw is not None else None
    return tid, sid


REBOOK_TRAINER_TARGETS_DEFAULT_LIMIT = 3


async def client_rebook_trainer_targets(
    session: AsyncSession,
    client_telegram_id: int,
    *,
    limit: int = REBOOK_TRAINER_TARGETS_DEFAULT_LIMIT,
) -> list[tuple[int, int | None]]:
    """
    Distinct trainers the client has (non-cancelled) bookings with, newest per-trainer slot first —
    hub «Снова к …» pills when the client uses multiple trainers.

    ``service_id`` is from that trainer's most recent booking (catalog deep-link hint).
    """
    cid = await get_client_id_by_telegram_id(session, int(client_telegram_id))
    if cid is None:
        return []
    lim = max(1, min(int(limit), 5))
    r = await session.execute(
        text(
            """
            SELECT sub.trainer_id, sub.service_id
            FROM (
                SELECT DISTINCT ON (b.trainer_id)
                       b.trainer_id,
                       b.service_id,
                       """
            + _SQL_SLOT_START_TS
            + """ AS slot_start
                FROM bookings b
                INNER JOIN slots s ON s.id = b.slot_id
                WHERE b.client_id = :cid
                  AND b.status IN ('pending', 'confirmed', 'completed', 'no_show')
                  AND COALESCE(TRIM(LOWER(COALESCE(s.status, ''))), '') <> 'cancelled'
                ORDER BY b.trainer_id, """
            + _SQL_SLOT_START_TS
            + """ DESC NULLS LAST, b.id DESC
            ) sub
            ORDER BY sub.slot_start DESC NULLS LAST
            LIMIT :lim
            """
        ),
        {"cid": int(cid), "lim": lim},
    )
    out: list[tuple[int, int | None]] = []
    for row in r.fetchall():
        if not row or row[0] is None:
            continue
        tid = int(row[0])
        sid_raw = row[1]
        sid = int(sid_raw) if sid_raw is not None else None
        out.append((tid, sid))
    return out


async def list_trainer_client_history(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    limit: int = 20,
    *,
    past_only: bool = True,
    today: date | None = None,
) -> list[dict]:
    """
    Last N non-cancelled bookings for this trainer and client (by slot date desc).

    ``past_only`` (default True): exclude future pending/confirmed so the client card history
    is not flooded by recurring auto-bookings months ahead. Pass ``today`` in NOTIFICATION_TZ.
    """
    lim = max(1, min(100, int(limit)))
    params: dict[str, Any] = {"tid": trainer_id, "cid": client_id, "lim": lim}
    future_filter = ""
    if past_only:
        day = today
        if day is None:
            try:
                from zoneinfo import ZoneInfo
            except ImportError:  # pragma: no cover
                from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
            day = datetime.now(ZoneInfo(NOTIFICATION_TZ)).date()
        params["today"] = day
        future_filter = """
              AND NOT (
                    b.status IN ('pending', 'confirmed')
                AND s.slot_date >= :today
              )
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
                b.status,
                COALESCE(spv.tier_kind, b.price_tier_kind) AS tier_kind_raw,
                b.recurring_client_slot_id
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN services srv ON srv.id = b.service_id
            LEFT JOIN trainer_service_price_variants spv ON spv.id = b.service_price_variant_id
            LEFT JOIN LATERAL (
                SELECT a.name
                FROM arenas a
                WHERE a.id = ("""
            + SQL_BOOKING_RESOLVED_ARENA_ID
            + """)
            ) a2 ON true
            WHERE b.trainer_id = :tid
              AND b.client_id = :cid
              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
            """
            + future_filter
            + """
            ORDER BY s.slot_date DESC, s.start_time DESC
            LIMIT :lim
            """
        ),
        params,
    )
    rows = r.fetchall()
    items: list[dict] = []
    for row in rows:
        raw_tier = row[8] if len(row) > 8 else None
        rec_slot = row[9] if len(row) > 9 else None
        ptk = normalize_price_tier_kind(raw_tier) if raw_tier else None
        tier_label = price_tier_label_ru(ptk) if ptk else None
        items.append(
            {
                "id": row[0],
                "slot_date": row[1],
                "start_time": row[2],
                "end_time": row[3],
                "duration_minutes": row[4] if row[4] is not None else 45,
                "arena_name": (row[5] or "").strip() or None,
                "service_name": (row[6] or "").strip() or "—",
                "status": (row[7] or "").strip() or "confirmed",
                "price_tier_label": tier_label,
                "recurring_client_slot_id": int(rec_slot) if rec_slot is not None else None,
            }
        )
    return items


async def count_trainer_client_sessions(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    *,
    past_only: bool = True,
    today: date | None = None,
) -> int:
    """Total non-cancelled bookings for this trainer and client (client card stats).

    ``past_only`` excludes future pending/confirmed (same idea as history list).
    """
    params: dict[str, Any] = {"tid": trainer_id, "cid": client_id}
    future_filter = ""
    if past_only:
        day = today
        if day is None:
            try:
                from zoneinfo import ZoneInfo
            except ImportError:  # pragma: no cover
                from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
            day = datetime.now(ZoneInfo(NOTIFICATION_TZ)).date()
        params["today"] = day
        future_filter = """
              AND NOT (
                    b.status IN ('pending', 'confirmed')
                AND s.slot_date >= :today
              )
        """
    r = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid
              AND b.client_id = :cid
              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
            """
            + future_filter
        ),
        params,
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
                SELECT a.name
                FROM arenas a
                WHERE a.id = ("""
            + SQL_BOOKING_RESOLVED_ARENA_ID
            + """)
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
                   """
            + SQL_BOOKING_ARENA_DISPLAY
            + """ AS arenas_str,
                   COALESCE(spv.tier_kind, b.price_tier_kind) AS tier_kind_raw,
                   """
            + _SQL_PRIOR_TRAINER_NOTIFIED_BOOKING_COUNT
            + """ AS prior_notified_push_count
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN trainer_service_price_variants spv ON spv.id = b.service_price_variant_id
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
    out: list[dict[str, Any]] = []
    for row in rows:
        raw_tier = row[13] if len(row) > 13 else None
        ptk = normalize_price_tier_kind(raw_tier) if raw_tier else None
        tier_label = price_tier_label_ru(ptk) if ptk else None
        prior_raw = row[14] if len(row) > 14 else None
        out.append(
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
                "price_tier_label": tier_label,
                "is_first_client_online_booking": (
                    int(prior_raw) == 0 if prior_raw is not None else False
                ),
            }
        )
    return out


async def mark_booking_notified(session: AsyncSession, booking_id: int) -> None:
    await session.execute(
        text("UPDATE bookings SET notified_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": booking_id},
    )
    await session.commit()


async def cancel_booking(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
    *,
    notify_client: bool = True,
    record_recurring_week_skip: bool = True,
    cancellation_source: str = BOOKING_CANCELLATION_SOURCE_TRAINER,
) -> bool:
    """
    Cancel booking: booking status to 'cancelled', slot occupancy synced (group slots may stay partially filled).
    Recurring-auto bookings: by default records a week skip so materialization will not recreate the same calendar week.
    ``cancellation_source`` records why the row was cancelled; stats omit recurring/roster system churn.
    Returns True if booking was found and cancelled.
    """
    r = await session.execute(
        text("""
            SELECT b.slot_id, b.recurring_client_slot_id, s.slot_date, b.client_id
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid AND b.trainer_id = :tid AND b.status IN ('pending', 'confirmed')
        """),
        {"bid": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return False
    slot_id = int(row[0])
    recurring_for_skip = row[1]
    slot_date_for_skip = row[2]
    client_id_cancel = int(row[3]) if row[3] is not None else None
    await session.execute(
        text(
            "UPDATE bookings SET status = 'cancelled', cancellation_source = :csrc WHERE id = :bid"
        ),
        {"bid": booking_id, "csrc": cancellation_source},
    )
    if record_recurring_week_skip and recurring_for_skip is not None and slot_date_for_skip is not None:
        from src.application.recurring_use_cases import record_recurring_materialization_week_skip

        await record_recurring_materialization_week_skip(
            session, int(recurring_for_skip), slot_date_for_skip
        )
    await sync_slot_status_for_occupancy(session, slot_id)
    if client_id_cancel is not None and slot_date_for_skip is not None:
        await resync_pending_reminders_for_client_day(
            session, client_id_cancel, slot_date_for_skip, do_commit=False
        )
    if notify_client:
        await _schedule_booking_cancel_notification(session, booking_id)
    await session.commit()
    invalidate_slots_for_trainer(trainer_id)
    return True


async def detach_trainer_client_from_roster_miniapp(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> dict[str, Any] | None:
    """
    Cancels trainer's upcoming pending/confirmed bookings with this client, removes CRM roster row.
    Blocked while the client is active/trial in a group operated by this trainer.
    Returns None if the trainer has no CRM access to the client (same rule as card auth).
    """
    if not await trainer_has_access_to_client(session, trainer_id, client_id):
        return None

    row_g = await session.execute(
        text(
            """
            SELECT 1 FROM training_group_members m
            INNER JOIN training_groups g ON g.id = m.training_group_id
            WHERE g.trainer_id = :tid AND m.client_id = :cid
              AND m.status IN ('active', 'trial')
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    if row_g.fetchone():
        raise ValueError(
            "Клиент состоит в активной группе. Сначала исключите его из группового занятия — "
            "потом можно убрать из списка."
        )

    rb = await session.execute(
        text(
            """
            SELECT b.id FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.client_id = :cid
              AND b.status IN ('pending', 'confirmed')
              AND s.status IN ('available', 'booked')
              AND """
            + _SQL_SLOT_END_TS
            + """ > CURRENT_TIMESTAMP
            ORDER BY b.id
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    bid_rows = rb.fetchall()
    cancelled_upcoming = 0
    for (bid,) in bid_rows:
        if await cancel_booking(
            session,
            int(bid),
            trainer_id,
            cancellation_source=BOOKING_CANCELLATION_SOURCE_ROSTER_DETACH,
        ):
            cancelled_upcoming += 1

    rr = await session.execute(
        text(
            """
            DELETE FROM trainer_client_roster
            WHERE trainer_id = :tid AND client_id = :cid
            RETURNING 1
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    roster_removed = rr.fetchone() is not None
    from src.application.client_trainer_edge_use_cases import (
        purge_client_trainer_hub_signals_on_roster_detach,
    )

    await purge_client_trainer_hub_signals_on_roster_detach(
        session, int(trainer_id), int(client_id)
    )
    await session.commit()
    return {
        "cancelled_upcoming_bookings": cancelled_upcoming,
        "roster_removed": roster_removed,
    }


async def cancel_booking_by_client(
    session: AsyncSession,
    booking_id: int,
    client_telegram_id: int,
    reason: str | None = None,
    *,
    notify_client_confirm: bool = True,
) -> dict | None:
    """
    Cancel booking by client: slot freed, status cancelled, reminders cancelled, reason stored.
    Idempotent: if this client already cancelled the booking, returns the same notification payload
    with ``already_cancelled=True`` (no duplicate UPDATE).
    Returns payload for party notifications or None if booking not found / not owned by client.

    ``notify_client_confirm``: enqueue Telegram self-confirm for the client (False for MAX Mini App —
    client has no Telegram chat for that catalog key).
    """
    from src.application.booking_party_notifications import (
        KIND_CLIENT_CANCEL_CONFIRM,
        KIND_CLIENT_CANCEL_TRAINER,
        ROLE_CLIENT,
        ROLE_TRAINER,
        enqueue_booking_party_notification,
    )

    reason_val = (reason or "").strip() or None
    cid_actor = await get_client_id_by_telegram_id(session, int(client_telegram_id))
    if cid_actor is None:
        return None

    def _payload_from_row(
        row: tuple,
        *,
        slot_id: int | None,
        already_cancelled: bool,
    ) -> dict[str, Any]:
        trainer_telegram_id, trainer_id_cache, slot_date, start_time, client_name = (
            row[0],
            row[1],
            row[2],
            row[3],
            (row[4] or "").strip() or "Клиент",
        )
        client_id = int(row[5]) if row[5] is not None else None
        service_id_raw = row[8] if len(row) > 8 else None
        date_str = slot_date.strftime("%d.%m") if hasattr(slot_date, "strftime") else str(slot_date)
        day_label = ""
        if hasattr(slot_date, "weekday"):
            from src.bot import messages as msg_mod

            day_label = msg_mod.TRAINER_DAYS[slot_date.weekday()]
        time_str = start_time.strftime("%H:%M") if hasattr(start_time, "strftime") else str(start_time)[:5]
        base = {
            "trainer_telegram_id": trainer_telegram_id,
            "trainer_id": int(trainer_id_cache),
            "service_id": int(service_id_raw) if service_id_raw is not None else None,
            "slot_id": int(slot_id) if slot_id is not None else None,
            "slot_date": slot_date,
            "start_time": start_time,
            "client_name": client_name,
            "reason": reason_val,
            "client_id": client_id,
            "client_telegram_id": int(client_telegram_id),
            "booking_id": int(booking_id),
            "already_cancelled": already_cancelled,
            "date_str": date_str,
            "day_label": day_label,
            "time_str": time_str,
        }
        return base

    async def _enqueue_party_notifications(payload: dict[str, Any]) -> None:
        notify_payload = {
            "date_str": payload["date_str"],
            "day_label": payload["day_label"],
            "time_str": payload["time_str"],
            "client_name": payload["client_name"],
            "reason": payload.get("reason"),
            "trainer_id": payload.get("trainer_id"),
            "service_id": payload.get("service_id"),
            "slot_id": payload.get("slot_id"),
            "client_id": payload.get("client_id"),
            "client_telegram_id": payload.get("client_telegram_id"),
        }
        trainer_tid = payload.get("trainer_telegram_id")
        if trainer_tid:
            await enqueue_booking_party_notification(
                session,
                booking_id=int(booking_id),
                kind=KIND_CLIENT_CANCEL_TRAINER,
                recipient_role=ROLE_TRAINER,
                recipient_telegram_id=int(trainer_tid),
                payload=notify_payload,
            )
        else:
            logger.warning(
                "client cancel: trainer has no telegram_id booking_id=%s trainer_id=%s — trainer notify skipped",
                booking_id,
                payload.get("trainer_id"),
            )
        if notify_client_confirm:
            await enqueue_booking_party_notification(
                session,
                booking_id=int(booking_id),
                kind=KIND_CLIENT_CANCEL_CONFIRM,
                recipient_role=ROLE_CLIENT,
                recipient_telegram_id=int(client_telegram_id),
                payload=notify_payload,
            )

    # Load trainer + slot + client for notification before updating
    r = await session.execute(
        text("""
            SELECT t.telegram_id, b.trainer_id, s.slot_date, s.start_time,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                   c.id, c.telegram_id, b.recurring_client_slot_id, b.service_id, b.slot_id, b.status
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            JOIN trainers t ON t.id = b.trainer_id
            WHERE b.id = :bid AND b.client_id = :cid
        """),
        {"bid": booking_id, "cid": int(cid_actor)},
    )
    row = r.fetchone()
    if not row:
        return None

    status = (row[10] or "").strip().lower()
    slot_id_cancel = int(row[9])

    if status == "cancelled":
        src = await session.execute(
            text("SELECT cancellation_source FROM bookings WHERE id = :bid"),
            {"bid": booking_id},
        )
        src_row = src.fetchone()
        if not src_row or (src_row[0] or "").strip().lower() != BOOKING_CANCELLATION_SOURCE_CLIENT:
            return None
        payload = _payload_from_row(row[:9], slot_id=slot_id_cancel, already_cancelled=True)
        await _enqueue_party_notifications(payload)
        await session.commit()
        return payload

    if status not in ("pending", "confirmed"):
        return None

    trainer_telegram_id, trainer_id_cache, slot_date, start_time, client_name = (
        row[0],
        row[1],
        row[2],
        row[3],
        (row[4] or "").strip() or "Клиент",
    )
    client_id = int(row[5]) if row[5] is not None else None
    recurring_for_skip = row[7]
    service_id_raw = row[8]

    await session.execute(
        text("""
            UPDATE bookings
            SET status = 'cancelled',
                client_cancel_comment = :reason,
                cancellation_source = :csrc
            WHERE id = :bid
        """),
        {
            "bid": booking_id,
            "reason": reason_val,
            "csrc": BOOKING_CANCELLATION_SOURCE_CLIENT,
        },
    )
    if recurring_for_skip is not None and slot_date is not None:
        from src.application.recurring_use_cases import record_recurring_materialization_week_skip

        await record_recurring_materialization_week_skip(
            session, int(recurring_for_skip), slot_date
        )
    await sync_slot_status_for_occupancy(session, slot_id_cancel)
    if client_id is not None and slot_date is not None:
        await resync_pending_reminders_for_client_day(session, client_id, slot_date, do_commit=False)
    payload = _payload_from_row(row[:9], slot_id=slot_id_cancel, already_cancelled=False)
    await _enqueue_party_notifications(payload)
    await session.commit()
    invalidate_slots_for_trainer(trainer_id_cache)
    return payload


async def confirm_booking(session: AsyncSession, booking_id: int, trainer_id: int) -> dict | None:
    """
    Confirm booking by trainer.
    Preconditions (enforced in SQL):
    - booking belongs to trainer;
    - booking status is 'pending';
    - slot is still booked.

    On success set status='confirmed' and return booking + slot + client contact info
    for notification flows. Returns None when booking is not confirmable (not found / wrong trainer / wrong status).

    Does NOT set ``client_notified_trainer_booked_at`` — the caller must do that only after
    ``notify_client_booking_confirmed_by_trainer`` (or the retry loop) actually delivers the
    «Ваша запись подтверждена!» push. Setting it here unconditionally used to permanently mask
    delivery failures: the flag blocks both this push and the «Вас записали…» fallback from
    ``get_pending_trainer_booked_notifications``, so a single failed send meant the client was
    silently never notified. See ``get_pending_booking_confirmed_notifications`` for the retry.

    Does touch ``notified_at`` (only if it was still NULL): trainer confirming from the Mini
    App's own pending-requests list, before the async «new booking» push loop ever set it, would
    otherwise leave ``notified_at`` NULL — which is exactly the guard
    ``get_pending_trainer_booked_notifications`` uses to decide a booking is eligible for the
    unrelated «Вас записали…» fallback. Without this, that loop and this confirm's own send could
    race and double-notify the client during the (usually sub-second) gap before this confirm's
    send completes.
    """
    # PostgreSQL: UPDATE ... FROM ... RETURNING can only return columns from the updated table
    r = await session.execute(
        text(
            """
            UPDATE bookings b
            SET status = 'confirmed',
                notified_at = COALESCE(b.notified_at, CURRENT_TIMESTAMP)
            FROM slots s
            WHERE b.slot_id = s.id
              AND b.id = :bid
              AND b.trainer_id = :tid
              AND s.status IN ('available', 'booked')
              AND b.status = 'pending'
            RETURNING b.id
            """
        ),
        {"bid": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    # Load full row for notifications (venue: booking.arena_id, else primary, else MIN(trainer_arenas))
    r2 = await session.execute(
        text(
            """
            SELECT b.id, b.slot_id, b.client_id, c.telegram_id, COALESCE(c.phone, '') AS client_phone,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                   b.client_comment, b.created_at, s.slot_date, s.start_time, s.end_time,
                   COALESCE(NULLIF(TRIM(srv.name), ''), '') AS service_name,
                   COALESCE(b.booking_price_cents, ts.price_cents) AS price_cents_effective,
                   b.price_tier_kind,
                   ar.name AS arena_name,
                   ar.address AS arena_address,
                   ar.latitude AS arena_lat,
                   ar.longitude AS arena_lon,
                   ar.arena_city_name,
                   (SELECT t.telegram_id FROM trainers t WHERE t.id = b.trainer_id) AS trainer_telegram_id,
                   COALESCE(b.is_sandbox, false) AS is_sandbox,
                   COALESCE(c.is_sandbox, false) AS client_is_sandbox
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            JOIN services srv ON srv.id = b.service_id
            LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
            LEFT JOIN LATERAL (
                SELECT a.name, a.address, a.latitude, a.longitude, ac.name AS arena_city_name
                FROM arenas a
                LEFT JOIN cities ac ON ac.id = a.city_id
                WHERE a.id = COALESCE(
                    b.arena_id,
                    s.arena_id,
                    (SELECT t.primary_arena_id FROM trainers t WHERE t.id = b.trainer_id),
                    (SELECT MIN(ta.arena_id) FROM trainer_arenas ta WHERE ta.trainer_id = b.trainer_id)
                )
            ) ar ON true
            WHERE b.id = :bid
            """
        ),
        {"bid": booking_id},
    )
    row2 = r2.fetchone()
    await session.commit()
    if not row2:
        return None
    ms, st_tip = await try_claim_first_booking_milestones(session, trainer_id)
    if ms or st_tip:
        await session.commit()
    arena_lat, arena_lon = row2[16], row2[17]
    trainer_tid = row2[19]
    an = (row2[14] or "").strip() if row2[14] else ""
    aa = (row2[15] or "").strip() if row2[15] else ""
    city_raw = (row2[18] or "").strip() if row2[18] else ""
    map_link = _arena_yandex_map_link(arena_lat, arena_lon, aa or None, an or None)
    ptk = normalize_price_tier_kind(row2[13])
    tier_label = price_tier_label_ru(ptk) if ptk else None
    sn = (row2[11] or "").strip() if row2[11] else ""
    price_cents = row2[12]
    cn_raw = (row2[5] or "").strip() if row2[5] else ""
    st_t, en_t = row2[9], row2[10]
    duration_minutes = _slot_wall_duration_minutes(st_t, en_t)
    return {
        "id": row2[0],
        "slot_id": row2[1],
        "client_id": row2[2],
        "client_telegram_id": row2[3],
        "client_phone": row2[4] or "",
        "client_name": cn_raw or None,
        "client_comment": row2[6],
        "created_at": row2[7],
        "slot_date": row2[8],
        "start_time": row2[9],
        "end_time": row2[10],
        "duration_minutes": duration_minutes,
        "service_name": sn or None,
        "booking_price_cents": int(price_cents) if price_cents is not None else None,
        "price_tier_label": tier_label,
        "arena_name": an or None,
        "arena_address": aa or None,
        "arena_city_name": city_raw or None,
        "map_link": map_link,
        "trainer_telegram_id": int(trainer_tid) if trainer_tid is not None else None,
        "first_booking_milestone": ms,
        "share_catalog_tip": st_tip,
        "is_sandbox": bool(row2[20]),
        "client_is_sandbox": bool(row2[21]),
    }


async def confirm_bookings_batch(
    session: AsyncSession,
    trainer_id: int,
    booking_ids: list[int],
    *,
    max_batch: int = 20,
) -> dict:
    """
    Confirm multiple pending bookings for one trainer.
    Each id is processed independently (same preconditions as ``confirm_booking``).
    """
    seen: set[int] = set()
    ordered: list[int] = []
    for raw in booking_ids:
        bid = int(raw)
        if bid in seen:
            continue
        seen.add(bid)
        ordered.append(bid)
        if len(ordered) >= max_batch:
            break

    confirmed: list[int] = []
    confirmed_infos: list[dict] = []
    failed: list[dict] = []
    first_milestone = False
    share_tip = False

    for bid in ordered:
        info = await confirm_booking(session, bid, trainer_id)
        if info:
            confirmed.append(bid)
            confirmed_infos.append(info)
            if info.get("first_booking_milestone"):
                first_milestone = True
            if info.get("share_catalog_tip"):
                share_tip = True
        else:
            failed.append({"id": bid, "reason": "not_confirmable"})

    return {
        "confirmed": confirmed,
        "confirmed_infos": confirmed_infos,
        "failed": failed,
        "confirmed_count": len(confirmed),
        "failed_count": len(failed),
        "first_booking_milestone": first_milestone,
        "share_catalog_tip": share_tip,
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
            SELECT b.slot_id, b.id,
                   c.telegram_id,
                   COALESCE(c.phone, '') AS client_phone,
                   c.id AS client_row_id,
                   s.slot_date,
                   s.start_time,
                   s.end_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid
              AND b.trainer_id = :tid
              AND b.status = 'pending'
            """
        ),
        {"bid": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    slot_id_decl = int(row[0])
    client_row_decl = int(row[4]) if row[4] is not None else None
    slot_date_decl = row[5]
    await session.execute(
        text("UPDATE bookings SET status = 'declined' WHERE id = :bid"),
        {"bid": booking_id},
    )
    await sync_slot_status_for_occupancy(session, slot_id_decl)
    if client_row_decl is not None and slot_date_decl is not None:
        await resync_pending_reminders_for_client_day(
            session, client_row_decl, slot_date_decl, do_commit=False
        )
    await session.commit()
    invalidate_slots_for_trainer(trainer_id)
    return {
        "id": row[1],
        "client_telegram_id": row[2],
        "client_phone": row[3] or "",
        "slot_date": row[5],
        "start_time": row[6],
        "end_time": row[7],
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
    Returns: booking_id, trainer_id, client_phone, client_name, client_telegram_id, slot_date, start_time
    (client_name / client_telegram_id for clearer reminder copy + «Написать» button).
    """
    r = await session.execute(
        text(
            """
            SELECT
                b.id,
                b.trainer_id,
                COALESCE(c.phone, '') AS client_phone,
                TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                c.telegram_id AS client_telegram_id,
                s.slot_date,
                s.start_time
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            WHERE b.status = 'pending'
              AND s.status IN ('available', 'booked')
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
            "client_name": ((row[3] or "").strip() or None),
            "client_telegram_id": int(row[4]) if row[4] is not None else None,
            "slot_date": row[5],
            "start_time": row[6],
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


async def get_pending_cancel_notification_for_booking(
    session: AsyncSession, booking_id: int
) -> dict | None:
    """Single pending trainer-cancel row for immediate client push after cancel_booking()."""
    r = await session.execute(
        text("""
            SELECT id, booking_id, client_telegram_id, slot_date, start_time, trainer_display_name
            FROM booking_cancel_notifications
            WHERE booking_id = :bid AND sent_at IS NULL
            LIMIT 1
        """),
        {"bid": booking_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "booking_id": row[1],
        "client_telegram_id": row[2],
        "slot_date": row[3],
        "start_time": row[4],
        "trainer_display_name": row[5] or "Тренер",
    }


async def mark_booking_cancel_notification_sent(session: AsyncSession, notification_id: int) -> None:
    await session.execute(
        text("UPDATE booking_cancel_notifications SET sent_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": notification_id},
    )
    await session.commit()


# --- Auto-complete: mark booking completed when slot end has passed; enqueue feedback notifications ---
# Rule (3.1): One pass session is redeemed when booking status becomes completed. All code paths
# that set status to 'completed' must call redeem_pass_session_for_booking in the same transaction.


async def restore_booking_financial_artifacts(session: AsyncSession, booking_id: int) -> None:
    """
    Strip completion-side artifacts for a booking (notifications, pass redemption, cert credit rows).
    Idempotent if rows are absent. Does not change booking status.
    """
    await session.execute(
        text("DELETE FROM booking_completed_notifications WHERE booking_id = :bid"),
        {"bid": booking_id},
    )

    rpr = await session.execute(
        text("SELECT pass_instance_id FROM pass_redemptions WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    pr = rpr.fetchone()
    if pr:
        inst_id = int(pr[0])
        await session.execute(
            text("DELETE FROM pass_redemptions WHERE booking_id = :bid"),
            {"bid": booking_id},
        )
        rpi = await session.execute(
            text("SELECT sessions_remaining, status FROM pass_instances WHERE id = :id"),
            {"id": inst_id},
        )
        pi = rpi.fetchone()
        if pi:
            rem, st = int(pi[0]), (pi[1] or "").strip().lower()
            new_rem = rem + 1
            new_st = "active" if st == "used_up" and new_rem > 0 else st
            await session.execute(
                text(
                    """
                    UPDATE pass_instances
                    SET sessions_remaining = :rem, status = :st
                    WHERE id = :id
                    """
                ),
                {"rem": new_rem, "st": new_st, "id": inst_id},
            )

    rcc = await session.execute(
        text(
            """
            SELECT certificate_instance_id, amount_cents
            FROM certificate_booking_credits WHERE booking_id = :bid
            """
        ),
        {"bid": booking_id},
    )
    crc = rcc.fetchone()
    if crc:
        cert_id, amt = int(crc[0]), int(crc[1])
        await session.execute(
            text("DELETE FROM certificate_booking_credits WHERE booking_id = :bid"),
            {"bid": booking_id},
        )
        rci = await session.execute(
            text(
                "SELECT COALESCE(amount_remaining_cents, 0), status FROM certificate_instances WHERE id = :id"
            ),
            {"id": cert_id},
        )
        ci = rci.fetchone()
        if ci:
            cur_amt, st = int(ci[0]), (ci[1] or "").strip().lower()
            new_bal = cur_amt + amt
            new_st = st
            if st == "redeemed" and new_bal > 0:
                new_st = "active"
            await session.execute(
                text(
                    """
                    UPDATE certificate_instances
                    SET amount_remaining_cents = :nb,
                        status = :st,
                        redeemed_at = CASE WHEN :nb > 0 THEN NULL ELSE redeemed_at END
                    WHERE id = :id
                    """
                ),
                {"nb": new_bal, "st": new_st, "id": cert_id},
            )


async def undo_completed_booking_pass_cert_ledger(session: AsyncSession, booking_id: int) -> bool:
    """
    When status is completed: remove pending completion notifications and restore pass/cert ledger rows.
    Does not change booking status — caller sets terminal status (e.g. confirmed or no_show).
    Returns True if the booking was completed; False if nothing to undo (wrong status).
    """
    r = await session.execute(
        text("SELECT status FROM bookings WHERE id = :bid"),
        {"bid": booking_id},
    )
    row = r.fetchone()
    if not row or (row[0] or "").strip().lower() != "completed":
        return False

    await restore_booking_financial_artifacts(session, booking_id)

    return True


async def purge_past_booking_from_schedule_history(
    session: AsyncSession,
    trainer_id: int,
    booking_id: int,
) -> tuple[bool, str | None]:
    """
    Soft-remove a past booking from schedule UI and trainer-facing aggregates (trainer_removed).
    Reverses pass/cert ledger rows when present. Slot occupancy is resynced.
    Returns (True, None) on success, or (False, machine-readable reason code).
    """
    r = await session.execute(
        text(
            """
            SELECT b.status, b.slot_id, c.telegram_id, b.client_id, s.slot_date
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN clients c ON c.id = b.client_id
            WHERE b.id = :bid AND b.trainer_id = :tid
              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
              AND """
            + _SQL_SLOT_END_TS
            + """ < CURRENT_TIMESTAMP
            """
        ),
        {"bid": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        r2 = await session.execute(
            text(
                """
                SELECT b.id
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.id = :bid AND b.trainer_id = :tid
                """
            ),
            {"bid": booking_id, "tid": trainer_id},
        )
        if not r2.fetchone():
            return False, "not_found"
        return False, "slot_not_past_or_invalid_status"

    slot_id = int(row[1])
    client_id_tr = int(row[3]) if row[3] is not None else None
    slot_date_tr = row[4]

    await restore_booking_financial_artifacts(session, booking_id)
    await session.execute(
        text(
            """
            UPDATE bookings
            SET status = :removed
            WHERE id = :bid AND trainer_id = :tid
            """
        ),
        {"removed": BOOKING_STATUS_TRAINER_REMOVED, "bid": booking_id, "tid": trainer_id},
    )
    await sync_slot_status_for_occupancy(session, slot_id)
    if client_id_tr is not None and slot_date_tr is not None:
        await resync_pending_reminders_for_client_day(
            session, client_id_tr, slot_date_tr, do_commit=False
        )

    if client_id_tr is not None:
        repo = ClientTrainerEdgeRepository(session)
        await repo.recompute_completed_booking_stats_for_global_edge(client_id_tr, trainer_id)

    await session.commit()
    invalidate_slots_for_trainer(trainer_id)
    return True, None


async def reverse_booking_completion_for_problem_report(session: AsyncSession, booking_id: int) -> None:
    """
    Undo completion side effects when a trainer files a problem report after auto-complete (E4 T4.5).
    Restores pass/cert ledger rows and drops pending booking_completed_notifications; sets status to confirmed.
    Does not unsend Telegram pushes already delivered (known limitation).
    """
    if not await undo_completed_booking_pass_cert_ledger(session, booking_id):
        return
    await session.execute(
        text("UPDATE bookings SET status = 'confirmed' WHERE id = :bid"),
        {"bid": booking_id},
    )


async def list_bookings_to_complete(session: AsyncSession, limit: int = 50) -> list[dict]:
    """Bookings with status in ('pending', 'confirmed') and slot end (Europe/Minsk wall time) already in the past.

    Sandbox bookings are excluded: they're a demo and shouldn't auto-complete in the background loop
    (which would also trigger client-completion pushes — those are blocked separately, but we drop
    sandbox here too to keep the pipeline clean).
    """
    r = await session.execute(
        text("""
            SELECT b.id, c.telegram_id, b.trainer_id,
                   s.slot_date, s.start_time, s.end_time,
                   (EXTRACT(EPOCH FROM (s.end_time - s.start_time)) / 60)::int AS duration_minutes,
                   COALESCE(NULLIF(TRIM(srv.name), ''), '') AS service_name,
                   COALESCE(NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), ''), 'Тренер') AS trainer_name,
                   t.telegram_id AS trainer_telegram_id
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            JOIN services srv ON srv.id = b.service_id
            JOIN trainers t ON t.id = b.trainer_id
            LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
            WHERE b.status IN ('pending', 'confirmed') AND s.status IN ('available', 'booked')
              AND NOT b.is_sandbox
              AND """ + _SQL_SLOT_END_TS + """ < CURRENT_TIMESTAMP
              AND NOT EXISTS (SELECT 1 FROM booking_problem_reports pr WHERE pr.booking_id = b.id)
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
            "duration_minutes": int(row[6]) if row[6] is not None else None,
            "service_name": (row[7] or "").strip() or None,
            "trainer_name": (row[8] or "").strip() or "Тренер",
            "trainer_telegram_id": int(row[9]) if row[9] is not None else None,
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
                   s.slot_date, s.start_time, s.end_time,
                   (EXTRACT(EPOCH FROM (s.end_time - s.start_time)) / 60)::int AS duration_minutes,
                   COALESCE(NULLIF(TRIM(srv.name), ''), '') AS service_name,
                   COALESCE(NULLIF(TRIM(CONCAT(COALESCE(p.first_name, ''), ' ', COALESCE(p.last_name, ''))), ''), 'Тренер') AS trainer_name,
                   t.telegram_id AS trainer_telegram_id
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            JOIN services srv ON srv.id = b.service_id
            JOIN trainers t ON t.id = b.trainer_id
            LEFT JOIN trainer_profiles p ON p.trainer_id = b.trainer_id
            WHERE b.status = 'completed'
              AND b.client_booking_completed_push_sent_at IS NULL
              AND c.telegram_id IS NOT NULL
              AND NOT b.is_sandbox -- Demo bookings never push to clients.
              AND NOT c.is_sandbox
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
            "duration_minutes": int(row[6]) if row[6] is not None else None,
            "service_name": (row[7] or "").strip() or None,
            "trainer_name": (row[8] or "").strip() or "Тренер",
            "trainer_telegram_id": int(row[9]) if row[9] is not None else None,
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


async def claim_client_booking_completion_push_sent(
    session: AsyncSession, booking_id: int
) -> bool:
    """Atomically claim client completion push. True if this worker owns the send."""
    r = await session.execute(
        text(
            "UPDATE bookings SET client_booking_completed_push_sent_at = CURRENT_TIMESTAMP "
            "WHERE id = :bid AND client_booking_completed_push_sent_at IS NULL "
            "RETURNING id"
        ),
        {"bid": booking_id},
    )
    await session.commit()
    return r.fetchone() is not None


async def clear_client_booking_completion_push_sent(
    session: AsyncSession, booking_id: int
) -> None:
    """Allow another retry after a clear pre-delivery failure (not used after timeout)."""
    await session.execute(
        text(
            "UPDATE bookings SET client_booking_completed_push_sent_at = NULL "
            "WHERE id = :bid"
        ),
        {"bid": booking_id},
    )
    await session.commit()


async def list_bookings_for_trainer_session_wrapup(
    session: AsyncSession,
    *,
    remaining_seconds_min: int,
    remaining_seconds_max: int,
    limit: int = 20,
) -> list[dict]:
    """
    Confirmed/pending bookings in the fixed wall-clock band before slot end (Europe/Minsk).

    Eligible when remaining time ``R = slot_end - now`` satisfies
    ``remaining_seconds_min <= R <= remaining_seconds_max`` (defaults 120–180 s = 2–3 minutes).

    All CRM clients qualify (phone-only or Telegram-linked); ``client_telegram_id`` in the row
    may be NULL — wrap-up is a trainer push, not a client bot message.
    """
    rmin = int(remaining_seconds_min)
    rmax = int(remaining_seconds_max)
    if rmin <= 0 or rmax <= 0 or rmin >= rmax:
        return []
    r = await session.execute(
        text("""
            SELECT b.id, b.id AS booking_id, b.trainer_id, c.telegram_id AS client_telegram_id,
                   b.client_id,
                   s.slot_date, s.start_time, s.end_time,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                   COALESCE(srv.name, '—') AS service_name,
                   b.booking_price_cents,
                   b.price_tier_kind,
                   """
        + SQL_BOOKING_ARENA_DISPLAY
        + """ AS arenas_str
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN services srv ON srv.id = b.service_id
            WHERE b.status IN ('pending', 'confirmed') AND s.status IN ('available', 'booked')
              AND b.trainer_session_wrapup_sent_at IS NULL
              AND NOT EXISTS (SELECT 1 FROM booking_problem_reports pr WHERE pr.booking_id = b.id)
              AND """ + _SQL_SLOT_END_TS + """ > CURRENT_TIMESTAMP
              AND CURRENT_TIMESTAMP >= """ + _SQL_SLOT_END_TS + """ - ((INTERVAL '1 second') * :rmax)
              AND CURRENT_TIMESTAMP <= """ + _SQL_SLOT_END_TS + """ - ((INTERVAL '1 second') * :rmin)
            ORDER BY s.slot_date, s.start_time
            LIMIT :lim
        """),
        {"lim": limit, "rmin": rmin, "rmax": rmax},
    )
    rows = r.fetchall()
    out: list[dict] = []
    for row in rows:
        ptk = normalize_price_tier_kind(row[11])
        tier_label = price_tier_label_ru(ptk) if ptk else None
        arena_raw = _normalize_trainer_arenas_display(row[12])
        cents = row[10]
        out.append(
            {
                "id": row[0],
                "booking_id": row[1],
                "trainer_id": row[2],
                "client_telegram_id": row[3],
                "client_id": row[4],
                "slot_date": row[5],
                "start_time": row[6],
                "end_time": row[7],
                "client_name": ((row[8] or "").strip() or "Клиент"),
                "service_name": ((row[9] or "—").strip()),
                "booking_price_cents": int(cents) if cents is not None else None,
                "price_tier_label": tier_label,
                "arenas_str": arena_raw,
            }
        )
    return out


async def mark_trainer_session_wrapup_sent(session: AsyncSession, booking_id: int) -> None:
    await session.execute(
        text(
            "UPDATE bookings SET trainer_session_wrapup_sent_at = CURRENT_TIMESTAMP WHERE id = :bid"
        ),
        {"bid": booking_id},
    )
    await session.commit()


async def mark_booking_completed_and_notify(
    session: AsyncSession,
    booking_id: int,
) -> bool:
    """Set booking status to completed, redeem one pass session if applicable, insert row for trainer feedback notification. Returns True if a pass was redeemed."""
    pr = await session.execute(
        text("SELECT 1 FROM booking_problem_reports WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    if pr.fetchone():
        return False
    await session.execute(
        text("UPDATE bookings SET status = 'completed' WHERE id = :bid"),
        {"bid": booking_id},
    )
    # Rule 3.1: deduct one pass session when booking becomes completed (best-effort; no raise if no pass)
    pass_redeemed = await redeem_pass_session_for_booking(session, booking_id)
    cert_redeemed = False
    if not pass_redeemed:
        cert_redeemed = await redeem_certificate_balance_for_booking(session, booking_id)
    trainer_no_pass_footer = not pass_redeemed and not cert_redeemed
    await session.execute(
        text("""
            INSERT INTO booking_completed_notifications
                (booking_id, client_telegram_id, trainer_id, trainer_no_pass_footer)
            SELECT b.id, c.telegram_id, b.trainer_id, :footer
            FROM bookings b
            JOIN clients c ON c.id = b.client_id WHERE b.id = :bid
            ON CONFLICT (booking_id) DO NOTHING
        """),
        {"bid": booking_id, "footer": trainer_no_pass_footer},
    )
    # Trainer already received «wrap-up» push in the last minute — do not enqueue duplicate Telegram.
    await session.execute(
        text("""
            UPDATE booking_completed_notifications n
            SET trainer_sent_at = CURRENT_TIMESTAMP
            FROM bookings b
            WHERE n.booking_id = b.id AND b.id = :bid
              AND b.trainer_session_wrapup_sent_at IS NOT NULL
              AND n.trainer_sent_at IS NULL
        """),
        {"bid": booking_id},
    )
    await session.commit()
    return pass_redeemed


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
    pr = await session.execute(
        text("SELECT 1 FROM booking_problem_reports WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    if pr.fetchone():
        return None
    await session.execute(
        text("UPDATE bookings SET status = 'completed' WHERE id = :bid"),
        {"bid": booking_id},
    )
    pass_redeemed = await redeem_pass_session_for_booking(session, booking_id)
    cert_redeemed = False
    if not pass_redeemed:
        cert_redeemed = await redeem_certificate_balance_for_booking(session, booking_id)
    trainer_no_pass_footer = not pass_redeemed and not cert_redeemed
    await session.execute(
        text("""
            INSERT INTO booking_completed_notifications
                (booking_id, client_telegram_id, trainer_id, trainer_no_pass_footer)
            SELECT b.id, c.telegram_id, b.trainer_id, :footer
            FROM bookings b
            JOIN clients c ON c.id = b.client_id WHERE b.id = :bid
            ON CONFLICT (booking_id) DO NOTHING
        """),
        {"bid": booking_id, "footer": trainer_no_pass_footer},
    )
    await session.execute(
        text("""
            UPDATE booking_completed_notifications n
            SET trainer_sent_at = CURRENT_TIMESTAMP
            FROM bookings b
            WHERE n.booking_id = b.id AND b.id = :bid
              AND b.trainer_session_wrapup_sent_at IS NOT NULL
              AND n.trainer_sent_at IS NULL
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
                   n.trainer_no_pass_footer,
                   b.client_id,
                   s.slot_date, s.start_time, s.end_time,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                   COALESCE(srv.name, '—') AS service_name,
                   b.price_tier_kind,
                   """
        + SQL_BOOKING_ARENA_DISPLAY
        + """ AS arenas_str
            FROM booking_completed_notifications n
            JOIN bookings b ON b.id = n.booking_id
            JOIN clients c ON c.id = b.client_id
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN services srv ON srv.id = b.service_id
            WHERE n.trainer_sent_at IS NULL
            ORDER BY n.id
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    out: list[dict] = []
    for row in rows:
        ptk = normalize_price_tier_kind(row[11])
        tier_label = price_tier_label_ru(ptk) if ptk else None
        arena_raw = _normalize_trainer_arenas_display(row[12])
        out.append(
            {
                "id": row[0],
                "booking_id": row[1],
                "trainer_id": row[2],
                "client_telegram_id": row[3],
                "trainer_no_pass_footer": bool(row[4]),
                "client_id": row[5],
                "slot_date": row[6],
                "start_time": row[7],
                "end_time": row[8],
                "client_name": ((row[9] or "").strip() or "Клиент"),
                "service_name": ((row[10] or "—").strip()),
                "price_tier_label": tier_label,
                "arenas_str": arena_raw,
            }
        )
    return out


async def mark_trainer_completed_sent(session: AsyncSession, notification_id: int) -> None:
    await session.execute(
        text("UPDATE booking_completed_notifications SET trainer_sent_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": notification_id},
    )
    await session.commit()


async def claim_trainer_completed_sent(session: AsyncSession, notification_id: int) -> bool:
    """Atomically claim trainer completion push. True if this worker owns the send."""
    r = await session.execute(
        text(
            "UPDATE booking_completed_notifications "
            "SET trainer_sent_at = CURRENT_TIMESTAMP "
            "WHERE id = :id AND trainer_sent_at IS NULL "
            "RETURNING id"
        ),
        {"id": notification_id},
    )
    await session.commit()
    return r.fetchone() is not None


async def clear_trainer_completed_sent(session: AsyncSession, notification_id: int) -> None:
    """Allow retry after a clear pre-delivery failure (not used after timeout)."""
    await session.execute(
        text(
            "UPDATE booking_completed_notifications SET trainer_sent_at = NULL WHERE id = :id"
        ),
        {"id": notification_id},
    )
    await session.commit()


async def get_booking_for_client_feedback(
    session: AsyncSession,
    booking_id: int,
    client_telegram_id: int,
) -> dict | None:
    """Booking by id and client; must be completed. Returns trainer_id and slot info for feedback flow."""
    cid = await get_client_id_by_telegram_id(session, int(client_telegram_id))
    if cid is None:
        return None
    r = await session.execute(
        text("""
            SELECT b.id, b.trainer_id, s.slot_date, s.start_time
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid AND b.client_id = :cid AND b.status = 'completed'
        """),
        {"bid": booking_id, "cid": int(cid)},
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
    """Completed booking by id and client; repeat flows include service_name and arena_name for trainer pings."""
    cid = await get_client_id_by_telegram_id(session, int(client_telegram_id))
    if cid is None:
        return None
    r = await session.execute(
        text("""
            SELECT b.id, b.trainer_id, b.client_id, b.service_id, s.slot_date, s.start_time, s.end_time,
                   b.service_price_variant_id, sv.name AS service_name,
                   NULLIF(TRIM(ar.name), '') AS arena_name
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN services sv ON sv.id = b.service_id
            LEFT JOIN arenas ar ON ar.id = COALESCE(b.arena_id, s.arena_id)
            WHERE b.id = :bid AND b.client_id = :cid AND b.status = 'completed'
        """),
        {"bid": booking_id, "cid": int(cid)},
    )
    row = r.fetchone()
    if not row:
        return None
    sn = row[8]
    an = row[9]
    return {
        "id": row[0],
        "trainer_id": row[1],
        "client_id": row[2],
        "service_id": row[3],
        "slot_date": row[4],
        "start_time": row[5],
        "end_time": row[6],
        "service_price_variant_id": int(row[7]) if row[7] is not None else None,
        "service_name": (sn or "").strip() or None,
        "arena_name": (an or "").strip() or None,
    }


async def get_booking_for_trainer_feedback(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> dict | None:
    """Booking by id and trainer for optional trainer review text (wrap-up or completed push).

    Allows pending/confirmed (session still active or just ended) and completed — same bookings that can
    show the «Оставить отзыв» CTA. Cancelled/declined excluded.
    """
    r = await session.execute(
        text("""
            SELECT b.id FROM bookings b
            WHERE b.id = :bid AND b.trainer_id = :tid
              AND b.status IN ('pending', 'confirmed', 'completed')
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
    """Save trainer's optional review text. Allowed while booking is still active or completed (not cancelled)."""
    r = await session.execute(
        text("""
            UPDATE bookings SET trainer_review_text = :text
            WHERE id = :bid AND trainer_id = :tid
              AND status IN ('pending', 'confirmed', 'completed')
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
    Clients whose latest non-cancelled session overall ended exactly 10 or 30 days ago,
    and who haven't received this notification yet.
    If a client has a future session, they are considered active and excluded.
    kind: INACTIVE_KIND_10_DAYS or INACTIVE_KIND_30_DAYS. Returns client_id, telegram_id, first_name.
    """
    days = 10 if kind == INACTIVE_KIND_10_DAYS else 30
    # Sandbox clients are demo identities — they should never trigger inactive-client pings,
    # otherwise the trainer (or worse, the phantom phone) gets an «давно не виделись» nudge after
    # an onboarding sandbox session.
    r = await session.execute(
        text("""
            WITH last_session AS (
                SELECT b.client_id, MAX((s.slot_date + s.end_time)) AS last_session_end_at
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                  AND NOT b.is_sandbox
                GROUP BY b.client_id
            ),
            candidates AS (
                SELECT c.id AS client_id, c.telegram_id, c.first_name, ls.last_session_end_at
                FROM clients c
                JOIN last_session ls ON ls.client_id = c.id
                WHERE NOT c.is_sandbox
                  AND ls.last_session_end_at < CURRENT_TIMESTAMP
                  AND (CURRENT_DATE - DATE(ls.last_session_end_at)) = :days
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


async def explain_trainer_booking_failure(
    session: AsyncSession,
    trainer_id: int,
    slot_id: int,
    service_id: int,
) -> str:
    """
    Human-readable reason when create_booking returned None (trainer Mini App).
    Group slots may stay status='booked' while seats remain; route allows that; failure is elsewhere.
    """
    from src.application.trainer_schedule_use_cases import get_slot

    slot = await get_slot(session, slot_id)
    if not slot or slot.get("trainer_id") != trainer_id:
        return "Слот не найден или недоступен"
    cap = max(1, int(slot.get("capacity") or 1))
    r = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM bookings
            WHERE slot_id = :sid AND status IN ('pending', 'confirmed')
            """
        ),
        {"sid": slot_id},
    )
    cnt = int(r.scalar() or 0)
    if cnt >= cap:
        return "Группа заполнена"
    slot_svc = slot.get("service_id")
    if cap > 1:
        if slot_svc is None:
            return "У группового слота не задана услуга в расписании"
        if int(slot_svc) != int(service_id):
            return "Услуга не совпадает со слотом"
    r2 = await session.execute(
        text("SELECT 1 FROM trainer_services WHERE trainer_id = :tid AND service_id = :sid"),
        {"tid": trainer_id, "sid": service_id},
    )
    if not r2.fetchone():
        return "Услуга не подключена в профиле или удалена"
    arena_id = slot.get("arena_id")
    if cap > 1 and arena_id is not None:
        r3 = await session.execute(
            text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
            {"tid": trainer_id, "aid": int(arena_id)},
        )
        if not r3.fetchone():
            return "Площадка слота не привязана к профилю — обновите привязку арен"
    return (
        "Не удалось создать запись. Если групповое занятие уже есть — проверьте миграции БД "
        "(несколько записей на один слот). Иначе откройте слот в расписании и сохраните снова."
    )
