"""
Center grid sessions and bookings (ADR-003 W2).

studio_central collectives: admin-owned collective_sessions, PAYG tariffs, attendance modes.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    SCHEDULE_MODE_STUDIO_CENTRAL,
    _assert_collective_studio_admin,
    get_collective_by_slug,
    is_collective_studio_admin_role,
    list_active_trainer_ids_for_collective_slug,
)
from src.shared.config import Settings

logger = logging.getLogger(__name__)

SCHEDULE_MODE_MEMBER_AUTONOMOUS = "member_autonomous"

ATTENDANCE_LANE_SELF = "lane_self"
ATTENDANCE_LANE_WITH_GUEST = "lane_with_guest"
ATTENDANCE_LANE_OWN_COACH = "lane_own_coach"
ATTENDANCE_COACH_INDIVIDUAL = "center_coach_individual"
ATTENDANCE_COACH_PAIR = "center_coach_pair"

ATTENDANCE_MODES = (
    ATTENDANCE_LANE_SELF,
    ATTENDANCE_LANE_WITH_GUEST,
    ATTENDANCE_LANE_OWN_COACH,
    ATTENDANCE_COACH_INDIVIDUAL,
    ATTENDANCE_COACH_PAIR,
)

LANE_ATTENDANCE_MODES = frozenset(
    {ATTENDANCE_LANE_SELF, ATTENDANCE_LANE_WITH_GUEST, ATTENDANCE_LANE_OWN_COACH}
)
COACH_ATTENDANCE_MODES = frozenset({ATTENDANCE_COACH_INDIVIDUAL, ATTENDANCE_COACH_PAIR})

SESSION_STATUS_AVAILABLE = "available"
SESSION_STATUS_CANCELLED = "cancelled"

BOOKING_STATUS_PENDING = "pending"
BOOKING_STATUS_CONFIRMED = "confirmed"
BOOKING_STATUS_CANCELLED = "cancelled"
BOOKING_STATUS_DECLINED = "declined"

# Throwing center PAYG reference tariffs (BYN cents) — ADR-003
CENTER_TARIFF_LANE_HOUR_CENTS = 2000
CENTER_TARIFF_GUEST_SURCHARGE_CENTS = 1500
CENTER_TARIFF_COACH_INDIVIDUAL_CENTS = 7000
CENTER_TARIFF_COACH_PAIR_CENTS = 10000


def compute_center_booking_price_cents(
    attendance_mode: str,
    *,
    guest_count: int = 0,
) -> int:
    """PAYG price for a center session booking (W2: no pass redemption)."""
    mode = (attendance_mode or "").strip()
    guests = max(0, int(guest_count))
    if mode == ATTENDANCE_LANE_SELF:
        return CENTER_TARIFF_LANE_HOUR_CENTS
    if mode == ATTENDANCE_LANE_WITH_GUEST:
        return CENTER_TARIFF_LANE_HOUR_CENTS + guests * CENTER_TARIFF_GUEST_SURCHARGE_CENTS
    if mode == ATTENDANCE_LANE_OWN_COACH:
        base = CENTER_TARIFF_LANE_HOUR_CENTS
        if guests > 0:
            base += guests * CENTER_TARIFF_GUEST_SURCHARGE_CENTS
        return base
    if mode == ATTENDANCE_COACH_INDIVIDUAL:
        return CENTER_TARIFF_COACH_INDIVIDUAL_CENTS
    if mode == ATTENDANCE_COACH_PAIR:
        return CENTER_TARIFF_COACH_PAIR_CENTS
    raise ValueError("invalid_attendance_mode")


def center_tariff_catalog() -> dict[str, Any]:
    """Public PAYG tariff card for client UI."""
    return {
        "currency": "BYN",
        "lane_hour_cents": CENTER_TARIFF_LANE_HOUR_CENTS,
        "guest_surcharge_cents": CENTER_TARIFF_GUEST_SURCHARGE_CENTS,
        "coach_individual_cents": CENTER_TARIFF_COACH_INDIVIDUAL_CENTS,
        "coach_pair_cents": CENTER_TARIFF_COACH_PAIR_CENTS,
        "attendance_modes": list(ATTENDANCE_MODES),
    }


async def _count_active_session_bookings(session: AsyncSession, session_id: int) -> int:
    r = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM collective_session_bookings
            WHERE collective_session_id = :sid
              AND status IN ('pending', 'confirmed', 'completed')
            """
        ),
        {"sid": int(session_id)},
    )
    return int(r.scalar_one())


async def _get_collective_owner_trainer_id(session: AsyncSession, collective_id: int) -> int | None:
    r = await session.execute(
        text("SELECT owner_trainer_id FROM collectives WHERE id = :id"),
        {"id": int(collective_id)},
    )
    row = r.fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


async def _session_row_to_dict(
    session: AsyncSession,
    row: Any,
    *,
    include_coaches: bool = True,
) -> dict[str, Any]:
    sid = int(row[0])
    booked = await _count_active_session_bookings(session, sid)
    capacity = max(1, int(row[5]))
    payload: dict[str, Any] = {
        "id": sid,
        "collective_id": int(row[1]),
        "slot_date": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
        "start_time": row[3].strftime("%H:%M") if hasattr(row[3], "strftime") else str(row[3])[:5],
        "end_time": row[4].strftime("%H:%M") if hasattr(row[4], "strftime") else str(row[4])[:5],
        "capacity": capacity,
        "arena_id": int(row[6]) if row[6] is not None else None,
        "status": str(row[7]),
        "booked_count": booked,
        "seats_left": max(0, capacity - booked),
    }
    if include_coaches:
        cr = await session.execute(
            text(
                """
                SELECT csc.trainer_id, tp.first_name, tp.last_name
                FROM collective_session_coaches csc
                LEFT JOIN trainer_profiles tp ON tp.trainer_id = csc.trainer_id
                WHERE csc.collective_session_id = :sid
                ORDER BY csc.trainer_id
                """
            ),
            {"sid": sid},
        )
        coaches = []
        for crow in cr.fetchall():
            name = " ".join(filter(None, [(crow[1] or "").strip(), (crow[2] or "").strip()])).strip()
            coaches.append(
                {
                    "trainer_id": int(crow[0]),
                    "display_name": name or f"Trainer #{crow[0]}",
                }
            )
        payload["assigned_coaches"] = coaches
    return payload


async def _require_studio_central_collective(
    session: AsyncSession,
    collective_id: int,
) -> dict[str, Any] | None:
    r = await session.execute(
        text(
            """
            SELECT id, slug, display_name, schedule_mode, status, owner_trainer_id
            FROM collectives WHERE id = :id LIMIT 1
            """
        ),
        {"id": int(collective_id)},
    )
    row = r.fetchone()
    if row is None:
        return None
    coll = {
        "id": int(row[0]),
        "slug": str(row[1]),
        "display_name": str(row[2]),
        "schedule_mode": str(row[3]),
        "status": str(row[4]),
        "owner_trainer_id": int(row[5]) if row[5] is not None else None,
    }
    if coll["schedule_mode"] != SCHEDULE_MODE_STUDIO_CENTRAL:
        return {"error": "not_studio_central"}
    if coll["status"] != COLLECTIVE_STATUS_ACTIVE:
        return {"error": "collective_not_active"}
    return coll


async def create_collective_session(
    session: AsyncSession,
    *,
    collective_id: int,
    owner_trainer_id: int,
    slot_date: date,
    start_time: time,
    end_time: time,
    capacity: int = 1,
    arena_id: int | None = None,
    coach_trainer_ids: list[int] | None = None,
) -> dict[str, Any] | None:
    """Owner creates a bookable center window."""
    err = await _assert_collective_studio_admin(session, collective_id, owner_trainer_id)
    if err:
        return {"error": err}
    coll = await _require_studio_central_collective(session, collective_id)
    if coll is None:
        return {"error": "collective_not_found"}
    if coll.get("error"):
        return coll

    cap = max(1, min(int(capacity), 500))
    if end_time <= start_time:
        return {"error": "invalid_time_range"}

    member_ids = await list_active_trainer_ids_for_collective_slug(session, coll["slug"]) or []
    coach_ids = [int(x) for x in (coach_trainer_ids or []) if int(x) in member_ids]

    r = await session.execute(
        text(
            """
            INSERT INTO collective_sessions (
                collective_id, slot_date, start_time, end_time, capacity, arena_id, status
            )
            VALUES (:cid, :d, :st, :et, :cap, :aid, :status)
            RETURNING id, collective_id, slot_date, start_time, end_time, capacity, arena_id, status
            """
        ),
        {
            "cid": int(collective_id),
            "d": slot_date,
            "st": start_time,
            "et": end_time,
            "cap": cap,
            "aid": arena_id,
            "status": SESSION_STATUS_AVAILABLE,
        },
    )
    row = r.fetchone()
    sid = int(row[0])
    for tid in coach_ids:
        await session.execute(
            text(
                """
                INSERT INTO collective_session_coaches (collective_session_id, trainer_id)
                VALUES (:sid, :tid)
                ON CONFLICT DO NOTHING
                """
            ),
            {"sid": sid, "tid": tid},
        )
    await session.commit()
    return await _session_row_to_dict(session, row)


async def update_collective_session_coaches(
    session: AsyncSession,
    *,
    session_id: int,
    owner_trainer_id: int,
    coach_trainer_ids: list[int],
) -> dict[str, Any] | None:
    """Replace assigned coaches for a session."""
    r = await session.execute(
        text(
            """
            SELECT cs.id, cs.collective_id, cs.slot_date, cs.start_time, cs.end_time,
                   cs.capacity, cs.arena_id, cs.status
            FROM collective_sessions cs
            WHERE cs.id = :id
            """
        ),
        {"id": int(session_id)},
    )
    row = r.fetchone()
    if row is None:
        return None
    cid = int(row[1])
    err = await _assert_collective_studio_admin(session, cid, owner_trainer_id)
    if err:
        return {"error": err}
    coll = await get_collective_by_slug(
        session,
        (await session.execute(text("SELECT slug FROM collectives WHERE id = :id"), {"id": cid})).scalar_one(),
        active_only=False,
    )
    member_ids = set(await list_active_trainer_ids_for_collective_slug(session, coll["slug"]) or []) if coll else set()
    coach_ids = [int(x) for x in coach_trainer_ids if int(x) in member_ids]

    await session.execute(
        text("DELETE FROM collective_session_coaches WHERE collective_session_id = :sid"),
        {"sid": int(session_id)},
    )
    for tid in coach_ids:
        await session.execute(
            text(
                """
                INSERT INTO collective_session_coaches (collective_session_id, trainer_id)
                VALUES (:sid, :tid)
                """
            ),
            {"sid": int(session_id), "tid": tid},
        )
    await session.commit()
    return await _session_row_to_dict(session, row)


async def cancel_collective_session(
    session: AsyncSession,
    *,
    session_id: int,
    owner_trainer_id: int,
) -> dict[str, Any] | None:
    r = await session.execute(
        text("SELECT collective_id FROM collective_sessions WHERE id = :id"),
        {"id": int(session_id)},
    )
    row = r.fetchone()
    if row is None:
        return None
    err = await _assert_collective_studio_admin(session, int(row[0]), owner_trainer_id)
    if err:
        return {"error": err}
    await session.execute(
        text("UPDATE collective_sessions SET status = :c, updated_at = :now WHERE id = :id"),
        {"c": SESSION_STATUS_CANCELLED, "now": datetime.now(timezone.utc), "id": int(session_id)},
    )
    await session.commit()
    return {"ok": True, "session_id": int(session_id)}


async def list_collective_sessions_for_studio(
    session: AsyncSession,
    *,
    collective_id: int,
    from_date: date,
    to_date: date,
) -> list[dict[str, Any]]:
    r = await session.execute(
        text(
            """
            SELECT id, collective_id, slot_date, start_time, end_time, capacity, arena_id, status
            FROM collective_sessions
            WHERE collective_id = :cid
              AND slot_date >= :fd AND slot_date <= :td
              AND status != :cancelled
            ORDER BY slot_date, start_time
            """
        ),
        {
            "cid": int(collective_id),
            "fd": from_date,
            "td": to_date,
            "cancelled": SESSION_STATUS_CANCELLED,
        },
    )
    out: list[dict[str, Any]] = []
    for row in r.fetchall():
        out.append(await _session_row_to_dict(session, row))
    return out


def _monday_of_week(d: date) -> date:
    """Normalize any date to the Monday of its ISO week."""
    return d - timedelta(days=d.weekday())


def _hhmm_to_time(raw: str) -> time:
    parts = (raw or "").strip().split(":")
    return time(int(parts[0]), int(parts[1]))


async def _collective_session_exists(
    session: AsyncSession,
    *,
    collective_id: int,
    slot_date: date,
    start_time: time,
    end_time: time,
) -> bool:
    r = await session.execute(
        text(
            """
            SELECT 1 FROM collective_sessions
            WHERE collective_id = :cid
              AND slot_date = :d
              AND start_time = :st
              AND end_time = :et
              AND status != :cancelled
            LIMIT 1
            """
        ),
        {
            "cid": int(collective_id),
            "d": slot_date,
            "st": start_time,
            "et": end_time,
            "cancelled": SESSION_STATUS_CANCELLED,
        },
    )
    return r.fetchone() is not None


async def duplicate_collective_sessions_week(
    session: AsyncSession,
    *,
    collective_id: int,
    owner_trainer_id: int,
    source_week_start: date,
    weeks_ahead: int = 1,
) -> dict[str, Any]:
    """
    Copy all center windows from source Mon–Sun to the following week(s).
    Skips slots that already exist at the same date/time.
    """
    err = await _assert_collective_studio_admin(session, collective_id, owner_trainer_id)
    if err:
        return {"error": err}
    coll = await _require_studio_central_collective(session, collective_id)
    if coll is None:
        return {"error": "collective_not_found"}
    if coll.get("error"):
        return coll

    weeks = max(1, min(int(weeks_ahead), 8))
    monday = _monday_of_week(source_week_start)
    source_end = monday + timedelta(days=6)
    source_sessions = await list_collective_sessions_for_studio(
        session,
        collective_id=int(collective_id),
        from_date=monday,
        to_date=source_end,
    )
    if not source_sessions:
        return {
            "ok": True,
            "created_count": 0,
            "skipped_count": 0,
            "source_week_start": monday.isoformat(),
            "weeks_ahead": weeks,
            "created_session_ids": [],
        }

    member_ids = set(
        await list_active_trainer_ids_for_collective_slug(session, coll["slug"]) or []
    )
    created_count = 0
    skipped_count = 0
    created_ids: list[int] = []

    for offset in range(1, weeks + 1):
        day_delta = timedelta(days=7 * offset)
        for src in source_sessions:
            src_date = date.fromisoformat(str(src["slot_date"]))
            target_date = src_date + day_delta
            start_time = _hhmm_to_time(str(src["start_time"]))
            end_time = _hhmm_to_time(str(src["end_time"]))
            if await _collective_session_exists(
                session,
                collective_id=int(collective_id),
                slot_date=target_date,
                start_time=start_time,
                end_time=end_time,
            ):
                skipped_count += 1
                continue

            cap = max(1, min(int(src.get("capacity") or 1), 500))
            arena_id = src.get("arena_id")
            coach_ids = [
                int(c["trainer_id"])
                for c in (src.get("assigned_coaches") or [])
                if int(c["trainer_id"]) in member_ids
            ]

            r = await session.execute(
                text(
                    """
                    INSERT INTO collective_sessions (
                        collective_id, slot_date, start_time, end_time, capacity, arena_id, status
                    )
                    VALUES (:cid, :d, :st, :et, :cap, :aid, :status)
                    RETURNING id
                    """
                ),
                {
                    "cid": int(collective_id),
                    "d": target_date,
                    "st": start_time,
                    "et": end_time,
                    "cap": cap,
                    "aid": arena_id,
                    "status": SESSION_STATUS_AVAILABLE,
                },
            )
            sid = int(r.scalar_one())
            for tid in coach_ids:
                await session.execute(
                    text(
                        """
                        INSERT INTO collective_session_coaches (collective_session_id, trainer_id)
                        VALUES (:sid, :tid)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {"sid": sid, "tid": tid},
                )
            created_count += 1
            created_ids.append(sid)

    await session.commit()
    return {
        "ok": True,
        "created_count": created_count,
        "skipped_count": skipped_count,
        "source_week_start": monday.isoformat(),
        "weeks_ahead": weeks,
        "created_session_ids": created_ids,
    }


async def list_public_collective_sessions(
    session: AsyncSession,
    *,
    slug: str,
    from_date: date,
    to_date: date,
) -> dict[str, Any] | None:
    coll = await get_collective_by_slug(session, slug, active_only=True)
    if coll is None:
        return None
    if coll.get("schedule_mode") != SCHEDULE_MODE_STUDIO_CENTRAL:
        return {"error": "not_studio_central", "schedule_mode": coll.get("schedule_mode")}
    sessions = await list_collective_sessions_for_studio(
        session,
        collective_id=int(coll["id"]),
        from_date=from_date,
        to_date=to_date,
    )
    # Only future bookable windows for clients
    now = datetime.now(timezone.utc)
    filtered: list[dict[str, Any]] = []
    for s in sessions:
        if int(s.get("seats_left") or 0) <= 0:
            continue
        filtered.append(s)
    from src.application.collective_pass_use_cases import list_collective_pass_products

    pass_products = await list_collective_pass_products(
        session,
        collective_id=int(coll["id"]),
        active_only=True,
    )
    return {
        "collective_id": coll["id"],
        "slug": coll["slug"],
        "display_name": coll["display_name"],
        "schedule_mode": coll.get("schedule_mode"),
        "tariffs": center_tariff_catalog(),
        "pass_products": pass_products,
        "sessions": filtered,
    }


async def _validate_coach_assignment(
    session: AsyncSession,
    session_id: int,
    center_coach_id: int | None,
    attendance_mode: str,
) -> str | None:
    if attendance_mode in COACH_ATTENDANCE_MODES:
        if center_coach_id is None:
            return "center_coach_required"
        r = await session.execute(
            text(
                """
                SELECT 1 FROM collective_session_coaches
                WHERE collective_session_id = :sid AND trainer_id = :tid
                """
            ),
            {"sid": int(session_id), "tid": int(center_coach_id)},
        )
        if r.fetchone() is None:
            return "coach_not_assigned"
    elif center_coach_id is not None:
        return "center_coach_not_allowed"
    return None


async def create_collective_session_booking(
    session: AsyncSession,
    *,
    session_id: int,
    client_id: int,
    attendance_mode: str,
    center_coach_id: int | None = None,
    guest_count: int = 0,
    client_comment: str | None = None,
    created_by_trainer_id: int | None = None,
    collective_pass_instance_id: int | None = None,
) -> dict[str, Any] | None:
    """
    Book a center session slot (PAYG or collective pass W3).

    trainer_id on booking: fulfillment coach, or collective owner for lane-only (ADR §4.1).
    Pass credits debited on confirm (or immediately when trainer creates confirmed booking).
    """
    mode = (attendance_mode or "").strip()
    if mode not in ATTENDANCE_MODES:
        return {"error": "invalid_attendance_mode"}

    r = await session.execute(
        text(
            """
            SELECT cs.id, cs.collective_id, cs.capacity, cs.status, cs.slot_date, cs.start_time,
                   c.schedule_mode, c.owner_trainer_id, c.status AS coll_status
            FROM collective_sessions cs
            INNER JOIN collectives c ON c.id = cs.collective_id
            WHERE cs.id = :id
            FOR UPDATE OF cs
            """
        ),
        {"id": int(session_id)},
    )
    row = r.fetchone()
    if row is None:
        return None
    if str(row[3]) != SESSION_STATUS_AVAILABLE or str(row[8]) != COLLECTIVE_STATUS_ACTIVE:
        return {"error": "session_not_available"}
    if str(row[6]) != SCHEDULE_MODE_STUDIO_CENTRAL:
        return {"error": "not_studio_central"}

    coach_err = await _validate_coach_assignment(session, int(session_id), center_coach_id, mode)
    if coach_err:
        return {"error": coach_err}

    guests = max(0, int(guest_count))
    if mode == ATTENDANCE_LANE_WITH_GUEST and guests < 1:
        return {"error": "guest_count_required"}
    if mode == ATTENDANCE_COACH_PAIR and guests < 1:
        guests = 1  # pair implies +1 participant

    booked = await _count_active_session_bookings(session, int(session_id))
    if booked >= max(1, int(row[2])):
        return {"error": "session_full"}

    collective_id = int(row[1])
    owner_id = int(row[7]) if row[7] is not None else None
    if mode in COACH_ATTENDANCE_MODES and center_coach_id is not None:
        fulfillment_trainer_id = int(center_coach_id)
    elif owner_id is not None:
        fulfillment_trainer_id = owner_id
    else:
        return {"error": "no_fulfillment_trainer"}

    pass_inst_id: int | None = None
    pass_credits = 0
    try:
        if collective_pass_instance_id is not None:
            from src.application.collective_pass_use_cases import validate_pass_for_booking

            validated = await validate_pass_for_booking(
                session,
                collective_pass_instance_id=int(collective_pass_instance_id),
                client_id=int(client_id),
                collective_id=collective_id,
                attendance_mode=mode,
                guest_count=guests,
            )
            if validated is None:
                return {"error": "pass_validation_failed"}
            if validated.get("error"):
                return validated
            pass_inst_id = int(validated["collective_pass_instance_id"])
            pass_credits = int(validated["pass_credits_reserved"])
            price_cents = int(validated["booking_price_cents"])
        else:
            price_cents = compute_center_booking_price_cents(mode, guest_count=guests)
    except ValueError:
        return {"error": "invalid_attendance_mode"}

    status = BOOKING_STATUS_CONFIRMED if created_by_trainer_id else BOOKING_STATUS_PENDING
    now = datetime.now(timezone.utc)

    ins = await session.execute(
        text(
            """
            INSERT INTO collective_session_bookings (
                collective_session_id, collective_id, client_id, trainer_id,
                attendance_mode, center_coach_id, guest_count, booking_price_cents,
                client_comment, status, created_by_trainer_id, created_at,
                collective_pass_instance_id, pass_credits_reserved
            )
            VALUES (
                :sid, :cid, :clid, :tid, :mode, :ccid, :guests, :price,
                :comment, :status, :cbt, :now, :pass_inst, :pass_credits
            )
            RETURNING id
            """
        ),
        {
            "sid": int(session_id),
            "cid": collective_id,
            "clid": int(client_id),
            "tid": fulfillment_trainer_id,
            "mode": mode,
            "ccid": int(center_coach_id) if center_coach_id is not None else None,
            "guests": guests,
            "price": price_cents,
            "comment": (client_comment or "")[:2000] or None,
            "status": status,
            "cbt": created_by_trainer_id,
            "now": now,
            "pass_inst": pass_inst_id,
            "pass_credits": pass_credits,
        },
    )
    booking_id = int(ins.scalar_one())
    if status == BOOKING_STATUS_CONFIRMED and pass_inst_id is not None:
        from src.application.collective_pass_use_cases import redeem_collective_pass_for_session_booking

        await redeem_collective_pass_for_session_booking(session, booking_id=booking_id)
    await session.commit()
    return {
        "booking_id": booking_id,
        "collective_session_id": int(session_id),
        "collective_id": collective_id,
        "attendance_mode": mode,
        "center_coach_id": center_coach_id,
        "guest_count": guests,
        "booking_price_cents": price_cents,
        "collective_pass_instance_id": pass_inst_id,
        "pass_credits_reserved": pass_credits,
        "status": status,
        "trainer_id": fulfillment_trainer_id,
    }


async def _booking_actor_may_manage(
    session: AsyncSession,
    *,
    collective_id: int,
    fulfillment_trainer_id: int,
    actor_trainer_id: int,
) -> bool:
    if int(fulfillment_trainer_id) == int(actor_trainer_id):
        return True
    err = await _assert_collective_studio_admin(session, collective_id, actor_trainer_id)
    return err is None


async def confirm_collective_session_booking(
    session: AsyncSession,
    *,
    booking_id: int,
    trainer_id: int,
) -> dict[str, Any] | None:
    """Trainer/owner/admin confirms pending center booking."""
    r = await session.execute(
        text(
            """
            SELECT id, trainer_id, status, collective_id
            FROM collective_session_bookings WHERE id = :id
            """
        ),
        {"id": int(booking_id)},
    )
    row = r.fetchone()
    if row is None:
        return None
    if not await _booking_actor_may_manage(
        session,
        collective_id=int(row[3]),
        fulfillment_trainer_id=int(row[1]),
        actor_trainer_id=int(trainer_id),
    ):
        return {"error": "forbidden"}
    if str(row[2]) != BOOKING_STATUS_PENDING:
        return {"error": "not_pending"}
    await session.execute(
        text(
            """
            UPDATE collective_session_bookings
            SET status = :confirmed
            WHERE id = :id
            """
        ),
        {"confirmed": BOOKING_STATUS_CONFIRMED, "id": int(booking_id)},
    )
    from src.application.collective_pass_use_cases import redeem_collective_pass_for_session_booking

    await redeem_collective_pass_for_session_booking(session, booking_id=int(booking_id))
    await session.commit()
    return {"ok": True, "booking_id": int(booking_id)}


def _attendance_mode_label_ru(mode: str) -> str:
    labels = {
        ATTENDANCE_LANE_SELF: "Дорожка",
        ATTENDANCE_LANE_WITH_GUEST: "Дорожка + гость",
        ATTENDANCE_LANE_OWN_COACH: "Дорожка, свой тренер",
        ATTENDANCE_COACH_INDIVIDUAL: "С тренером центра",
        ATTENDANCE_COACH_PAIR: "Парная с тренером",
    }
    return labels.get((mode or "").strip(), mode or "—")


def _client_display_name(first: str | None, last: str | None, client_id: int) -> str:
    name = " ".join(filter(None, [(first or "").strip(), (last or "").strip()])).strip()
    return name or f"Клиент #{client_id}"


async def build_center_hub_summary(
    session: AsyncSession,
    *,
    collective_id: int,
    admin_trainer_id: int,
    summary_date: date | None = None,
) -> dict[str, Any] | None:
    """Today grid stats + pending inbox for trainer hub center ops card."""
    err = await _assert_collective_studio_admin(session, collective_id, admin_trainer_id)
    if err:
        return None
    day = summary_date or date.today()
    pending = await count_pending_collective_session_bookings_for_admin(
        session,
        collective_id=int(collective_id),
        admin_trainer_id=int(admin_trainer_id),
    )
    pending_count = int(pending.get("count") or 0)

    r = await session.execute(
        text(
            """
            SELECT
                cs.id,
                cs.start_time,
                cs.end_time,
                GREATEST(cs.capacity, 1)::int AS capacity,
                (
                    SELECT COUNT(*)::int
                    FROM collective_session_bookings b
                    WHERE b.collective_session_id = cs.id
                      AND b.status IN ('pending', 'confirmed', 'completed')
                ) AS booked
            FROM collective_sessions cs
            WHERE cs.collective_id = :cid
              AND cs.slot_date = :day
              AND cs.status != :cancelled
            ORDER BY cs.start_time, cs.id
            """
        ),
        {
            "cid": int(collective_id),
            "day": day,
            "cancelled": SESSION_STATUS_CANCELLED,
        },
    )
    rows = r.fetchall()
    session_count = len(rows)
    capacity_total = sum(int(row[3]) for row in rows)
    booked_total = sum(int(row[4] or 0) for row in rows)
    next_session: dict[str, Any] | None = None
    if rows:
        row0 = rows[0]
        cap0 = int(row0[3])
        booked0 = int(row0[4] or 0)
        next_session = {
            "id": int(row0[0]),
            "start_time": row0[1].strftime("%H:%M") if hasattr(row0[1], "strftime") else str(row0[1])[:5],
            "end_time": row0[2].strftime("%H:%M") if hasattr(row0[2], "strftime") else str(row0[2])[:5],
            "booked_count": booked0,
            "capacity": cap0,
            "seats_left": max(0, cap0 - booked0),
        }
    return {
        "date": day.isoformat(),
        "pending_bookings": pending_count,
        "sessions_today": session_count,
        "capacity_today": capacity_total,
        "booked_today": booked_total,
        "seats_left_today": max(0, capacity_total - booked_total),
        "next_session": next_session,
    }


async def count_pending_collective_session_bookings_for_admin(
    session: AsyncSession,
    *,
    collective_id: int,
    admin_trainer_id: int,
) -> dict[str, Any]:
    """Lightweight pending count for hub dual summary and inbox badges."""
    err = await _assert_collective_studio_admin(session, collective_id, admin_trainer_id)
    if err:
        return {"error": err, "count": 0}
    r = await session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM collective_session_bookings b
            WHERE b.collective_id = :cid AND b.status = :pending
            """
        ),
        {"cid": int(collective_id), "pending": BOOKING_STATUS_PENDING},
    )
    return {"count": int(r.scalar_one() or 0)}


async def list_pending_collective_session_bookings_for_owner(
    session: AsyncSession,
    *,
    collective_id: int,
    owner_trainer_id: int,
    limit: int = 50,
) -> dict[str, Any]:
    """Inbox for center admin — pending client requests (ADR Q4 lane-only → owner)."""
    err = await _assert_collective_studio_admin(session, collective_id, owner_trainer_id)
    if err:
        return {"error": err}
    lim = max(1, min(int(limit), 200))
    r = await session.execute(
        text(
            """
            SELECT
                b.id, b.attendance_mode, b.guest_count, b.booking_price_cents,
                b.client_comment, b.status, b.created_at,
                b.collective_pass_instance_id, b.pass_credits_reserved,
                cs.id, cs.slot_date, cs.start_time, cs.end_time,
                cl.id, cl.first_name, cl.last_name, cl.phone,
                b.center_coach_id,
                tp.first_name, tp.last_name
            FROM collective_session_bookings b
            INNER JOIN collective_sessions cs ON cs.id = b.collective_session_id
            INNER JOIN clients cl ON cl.id = b.client_id
            LEFT JOIN trainer_profiles tp ON tp.trainer_id = b.center_coach_id
            WHERE b.collective_id = :cid AND b.status = :pending
            ORDER BY cs.slot_date, cs.start_time, b.created_at
            LIMIT :lim
            """
        ),
        {"cid": int(collective_id), "pending": BOOKING_STATUS_PENDING, "lim": lim},
    )
    items: list[dict[str, Any]] = []
    for row in r.fetchall():
        slot_date = row[10].isoformat() if hasattr(row[10], "isoformat") else str(row[10])
        start = row[11].strftime("%H:%M") if hasattr(row[11], "strftime") else str(row[11])[:5]
        end = row[12].strftime("%H:%M") if hasattr(row[12], "strftime") else str(row[12])[:5]
        coach_name = None
        if row[17] is not None:
            coach_name = " ".join(filter(None, [(row[18] or "").strip(), (row[19] or "").strip()])).strip() or None
        items.append(
            {
                "booking_id": int(row[0]),
                "attendance_mode": str(row[1]),
                "attendance_mode_label": _attendance_mode_label_ru(str(row[1])),
                "guest_count": int(row[2] or 0),
                "booking_price_cents": int(row[3] or 0),
                "client_comment": row[4],
                "status": str(row[5]),
                "created_at": row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6]),
                "collective_pass_instance_id": int(row[7]) if row[7] is not None else None,
                "pass_credits_reserved": int(row[8] or 0),
                "collective_session_id": int(row[9]),
                "slot_date": slot_date,
                "start_time": start,
                "end_time": end,
                "client_id": int(row[13]),
                "client_name": _client_display_name(row[14], row[15], int(row[13])),
                "client_phone": (row[16] or "").strip() or None,
                "center_coach_id": int(row[17]) if row[17] is not None else None,
                "center_coach_name": coach_name,
            }
        )
    return {"bookings": items, "count": len(items)}


async def decline_collective_session_booking(
    session: AsyncSession,
    *,
    booking_id: int,
    trainer_id: int,
) -> dict[str, Any] | None:
    """Owner or fulfillment coach declines a pending center booking."""
    r = await session.execute(
        text(
            """
            SELECT id, trainer_id, status, collective_id
            FROM collective_session_bookings WHERE id = :id
            """
        ),
        {"id": int(booking_id)},
    )
    row = r.fetchone()
    if row is None:
        return None
    if not await _booking_actor_may_manage(
        session,
        collective_id=int(row[3]),
        fulfillment_trainer_id=int(row[1]),
        actor_trainer_id=int(trainer_id),
    ):
        return {"error": "forbidden"}
    if str(row[2]) != BOOKING_STATUS_PENDING:
        return {"error": "not_pending"}
    await session.execute(
        text(
            """
            UPDATE collective_session_bookings
            SET status = :declined
            WHERE id = :id
            """
        ),
        {"declined": BOOKING_STATUS_DECLINED, "id": int(booking_id)},
    )
    await session.commit()
    return {"ok": True, "booking_id": int(booking_id)}


async def build_center_schedule_admin_for_trainer(
    session: AsyncSession,
    *,
    trainer_id: int,
    from_date: date,
    to_date: date,
) -> dict[str, Any] | None:
    """Studio admin overlay for unified schedule: all center windows + team roster."""
    from src.application.collective_use_cases import (
        get_effective_studio_access_mode,
        is_collective_studio_admin_role,
        list_active_collective_memberships,
        SCHEDULE_MODE_STUDIO_CENTRAL,
    )
    from src.application.organization_capabilities import capabilities_for_collective_membership

    memberships = await list_active_collective_memberships(session, trainer_id)
    studio_access_mode = await get_effective_studio_access_mode(session, trainer_id)
    for m in memberships:
        if m.schedule_mode != SCHEDULE_MODE_STUDIO_CENTRAL:
            continue
        if not is_collective_studio_admin_role(m.role):
            continue
        sessions = await list_collective_sessions_for_studio(
            session,
            collective_id=m.collective_id,
            from_date=from_date,
            to_date=to_date,
        )
        caps = capabilities_for_collective_membership(
            organization_format=m.organization_format,
            schedule_mode=m.schedule_mode,
            role=m.role,
            studio_access_mode=studio_access_mode,
        )
        cr = await session.execute(
            text(
                """
                SELECT cm.trainer_id, tp.first_name, tp.last_name
                FROM collective_members cm
                LEFT JOIN trainer_profiles tp ON tp.trainer_id = cm.trainer_id
                WHERE cm.collective_id = :cid
                  AND cm.status = 'active'
                  AND cm.role IN ('owner', 'admin', 'member')
                ORDER BY cm.role, cm.trainer_id
                """
            ),
            {"cid": m.collective_id},
        )
        coaches: list[dict[str, Any]] = []
        for row in cr.fetchall():
            name = " ".join(filter(None, [(row[1] or "").strip(), (row[2] or "").strip()])).strip()
            coaches.append(
                {
                    "trainer_id": int(row[0]),
                    "display_name": name or f"Тренер #{int(row[0])}",
                }
            )
        return {
            "collective_slug": m.slug,
            "collective_name": m.display_name,
            "sessions": sessions,
            "coaches": coaches,
            "organization_format": m.organization_format,
            "capabilities": caps,
        }
    return None


async def list_center_duties_for_trainer(
    session: AsyncSession,
    *,
    trainer_id: int,
    from_date: date,
    to_date: date,
) -> list[dict[str, Any]]:
    """
    Merged schedule overlay (ADR §6): center windows where trainer is on duty.

    Returns empty list for solo trainers — no collective_session_coaches rows.
    """
    r = await session.execute(
        text(
            """
            SELECT
                cs.id, cs.collective_id, c.display_name, c.slug,
                cs.slot_date, cs.start_time, cs.end_time, cs.capacity, cs.status,
                (
                    SELECT COUNT(*) FROM collective_session_bookings cb
                    WHERE cb.collective_session_id = cs.id
                      AND cb.status IN ('pending', 'confirmed', 'completed')
                ) AS booked_count
            FROM collective_session_coaches csc
            INNER JOIN collective_sessions cs ON cs.id = csc.collective_session_id
            INNER JOIN collectives c ON c.id = cs.collective_id
            WHERE csc.trainer_id = :tid
              AND cs.slot_date >= :fd AND cs.slot_date <= :td
              AND cs.status != :cancelled
              AND c.status = :active
              AND c.schedule_mode = :central
            ORDER BY cs.slot_date, cs.start_time
            """
        ),
        {
            "tid": int(trainer_id),
            "fd": from_date,
            "td": to_date,
            "cancelled": SESSION_STATUS_CANCELLED,
            "active": COLLECTIVE_STATUS_ACTIVE,
            "central": SCHEDULE_MODE_STUDIO_CENTRAL,
        },
    )
    out: list[dict[str, Any]] = []
    for row in r.fetchall():
        slot_date = row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4])
        start = row[5].strftime("%H:%M") if hasattr(row[5], "strftime") else str(row[5])[:5]
        end = row[6].strftime("%H:%M") if hasattr(row[6], "strftime") else str(row[6])[:5]
        capacity = max(1, int(row[7]))
        booked = int(row[9] or 0)
        out.append(
            {
                "kind": "center_duty",
                "collective_session_id": int(row[0]),
                "collective_id": int(row[1]),
                "collective_name": str(row[2]),
                "collective_slug": str(row[3]),
                "slot_date": slot_date,
                "start_time": start,
                "end_time": end,
                "capacity": capacity,
                "booked_count": booked,
                "status": str(row[8]),
            }
        )
    return out


def _times_overlap(start_a: time, end_a: time, start_b: time, end_b: time) -> bool:
    """Half-open interval overlap on same calendar day."""
    a0 = start_a.hour * 60 + start_a.minute
    a1 = end_a.hour * 60 + end_a.minute
    b0 = start_b.hour * 60 + start_b.minute
    b1 = end_b.hour * 60 + end_b.minute
    return a0 < b1 and b0 < a1


async def find_trainer_center_duty_conflicts(
    session: AsyncSession,
    *,
    trainer_id: int,
    slot_date: date,
    intervals: list[tuple[time, time]],
) -> list[dict[str, Any]]:
    """Center duty windows overlapping proposed personal slot intervals."""
    if not intervals:
        return []
    duties = await list_center_duties_for_trainer(
        session,
        trainer_id=int(trainer_id),
        from_date=slot_date,
        to_date=slot_date,
    )
    conflicts: list[dict[str, Any]] = []
    for duty in duties:
        try:
            sh, sm = (duty["start_time"] or "00:00").split(":")[:2]
            eh, em = (duty["end_time"] or "00:00").split(":")[:2]
            d_start = time(int(sh), int(sm))
            d_end = time(int(eh), int(em))
        except (ValueError, TypeError):
            continue
        for start, end in intervals:
            if _times_overlap(start, end, d_start, d_end):
                conflicts.append(
                    {
                        "kind": "center_duty",
                        "collective_name": duty.get("collective_name"),
                        "start_time": duty.get("start_time"),
                        "end_time": duty.get("end_time"),
                    }
                )
                break
    return conflicts


async def assert_no_center_duty_conflict_for_slots(
    session: AsyncSession,
    *,
    trainer_id: int,
    slot_date: date,
    intervals: list[tuple[time, time]],
) -> None:
    """Raises ValueError when personal slots overlap assigned center duty (ADR §6)."""
    conflicts = await find_trainer_center_duty_conflicts(
        session,
        trainer_id=trainer_id,
        slot_date=slot_date,
        intervals=intervals,
    )
    if not conflicts:
        return
    first = conflicts[0]
    label = first.get("collective_name") or "центр"
    raise ValueError(
        f"Пересечение с дежурством ({label} {first.get('start_time')}–{first.get('end_time')})"
    )

