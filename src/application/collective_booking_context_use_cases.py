"""
Trainer booking contexts and delegate booking (ADR-003 W4–W5).

Context picker: personal slots vs center sessions when coach books a client.
Delegate: studio admin books into member slots or center sessions on their behalf.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.collective_session_use_cases import (
    ATTENDANCE_MODES,
    create_collective_session_booking,
    list_collective_sessions_for_studio,
)
from src.application.collective_use_cases import (
    MEMBER_ROLE_MEMBER,
    SCHEDULE_MODE_MEMBER_AUTONOMOUS,
    SCHEDULE_MODE_STUDIO_CENTRAL,
    STUDIO_ACCESS_MODE_ADMIN_ONLY,
    STUDIO_ACCESS_MODE_FULL,
    _assert_collective_studio_admin,
    get_trainer_studio_access_mode,
    is_collective_studio_admin_role,
    list_active_collective_memberships,
    resolve_collective_membership,
)


async def _trainer_has_upcoming_center_coach_duties(
    session: AsyncSession,
    *,
    trainer_id: int,
    collective_id: int,
) -> bool:
    today = date.today()
    r = await session.execute(
        text(
            """
            SELECT 1
            FROM collective_session_coaches csc
            INNER JOIN collective_sessions cs ON cs.id = csc.collective_session_id
            WHERE csc.trainer_id = :tid
              AND cs.collective_id = :cid
              AND cs.status = 'available'
              AND cs.slot_date >= :today
            LIMIT 1
            """
        ),
        {"tid": int(trainer_id), "cid": int(collective_id), "today": today},
    )
    return r.fetchone() is not None


async def _list_delegate_coaches(
    session: AsyncSession,
    *,
    collective_id: int,
) -> list[dict[str, Any]]:
    r = await session.execute(
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
        {"cid": int(collective_id)},
    )
    out: list[dict[str, Any]] = []
    for row in r.fetchall():
        name = " ".join(filter(None, [(row[1] or "").strip(), (row[2] or "").strip()])).strip()
        out.append(
            {
                "trainer_id": int(row[0]),
                "display_name": name or f"Тренер #{int(row[0])}",
            }
        )
    return out


async def list_trainer_booking_contexts(
    session: AsyncSession,
    trainer_id: int,
) -> dict[str, Any]:
    """Contexts for coach/staff client booking picker."""
    access_mode = await get_trainer_studio_access_mode(session, trainer_id)
    memberships = await list_active_collective_memberships(session, trainer_id)
    contexts: list[dict[str, Any]] = []

    if access_mode != STUDIO_ACCESS_MODE_ADMIN_ONLY:
        has_autonomous = any(m.schedule_mode == SCHEDULE_MODE_MEMBER_AUTONOMOUS for m in memberships)
        if not memberships or has_autonomous or len(memberships) == 1:
            label = "Личное расписание"
            if len(memberships) == 1 and memberships[0].schedule_mode == SCHEDULE_MODE_MEMBER_AUTONOMOUS:
                label = f"{memberships[0].display_name} · личные слоты"
            contexts.append(
                {
                    "kind": "personal_slot",
                    "context_id": "personal",
                    "label": label,
                    "collective_slug": None,
                    "schedule_mode": SCHEDULE_MODE_MEMBER_AUTONOMOUS,
                }
            )
        elif len(memberships) > 1:
            contexts.append(
                {
                    "kind": "personal_slot",
                    "context_id": "personal",
                    "label": "Личное расписание",
                    "collective_slug": None,
                    "schedule_mode": SCHEDULE_MODE_MEMBER_AUTONOMOUS,
                }
            )

    for m in memberships:
        if m.schedule_mode != SCHEDULE_MODE_STUDIO_CENTRAL:
            continue
        can_center = is_collective_studio_admin_role(m.role) or await _trainer_has_upcoming_center_coach_duties(
            session,
            trainer_id=trainer_id,
            collective_id=m.collective_id,
        )
        if not can_center:
            continue
        contexts.append(
            {
                "kind": "center_session",
                "context_id": f"center:{m.slug}",
                "label": f"{m.display_name} · окна центра",
                "collective_slug": m.slug,
                "collective_display_name": m.display_name,
                "schedule_mode": m.schedule_mode,
                "can_delegate": is_collective_studio_admin_role(m.role),
            }
        )

    delegate: dict[str, Any] | None = None
    for m in memberships:
        if m.schedule_mode == SCHEDULE_MODE_STUDIO_CENTRAL and is_collective_studio_admin_role(m.role):
            delegate = {
                "collective_slug": m.slug,
                "collective_display_name": m.display_name,
                "coaches": await _list_delegate_coaches(session, collective_id=m.collective_id),
            }
            break

    default_id = contexts[0]["context_id"] if contexts else "personal"
    return {
        "contexts": contexts,
        "delegate": delegate,
        "studio_access_mode": access_mode,
        "default_context_id": default_id,
        "needs_context_picker": len(contexts) > 1,
    }


async def list_staff_bookable_center_sessions(
    session: AsyncSession,
    *,
    actor_trainer_id: int,
    collective_slug: str,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict[str, Any]:
    """Upcoming center windows staff/coach may book clients into."""
    membership = await resolve_collective_membership(
        session,
        actor_trainer_id,
        collective_slug=collective_slug,
    )
    if membership is None:
        return {"error": "not_in_collective"}
    if membership.schedule_mode != SCHEDULE_MODE_STUDIO_CENTRAL:
        return {"error": "not_studio_central"}

    today = date.today()
    fd = from_date or today
    td = to_date or (today + timedelta(days=28))
    all_sessions = await list_collective_sessions_for_studio(
        session,
        collective_id=membership.collective_id,
        from_date=fd,
        to_date=td,
    )

    if is_collective_studio_admin_role(membership.role):
        sessions = all_sessions
    else:
        assigned_ids: set[int] = set()
        r = await session.execute(
            text(
                """
                SELECT csc.collective_session_id
                FROM collective_session_coaches csc
                INNER JOIN collective_sessions cs ON cs.id = csc.collective_session_id
                WHERE csc.trainer_id = :tid AND cs.collective_id = :cid
                  AND cs.slot_date >= :fd AND cs.slot_date <= :td
                """
            ),
            {
                "tid": int(actor_trainer_id),
                "cid": membership.collective_id,
                "fd": fd,
                "td": td,
            },
        )
        assigned_ids = {int(row[0]) for row in r.fetchall()}
        sessions = [s for s in all_sessions if int(s["id"]) in assigned_ids]

    return {
        "sessions": sessions,
        "attendance_modes": list(ATTENDANCE_MODES),
        "collective_slug": membership.slug,
    }


async def assert_delegate_personal_slot_booking(
    session: AsyncSession,
    *,
    actor_trainer_id: int,
    target_trainer_id: int,
    slot_id: int,
    collective_slug: str | None = None,
) -> str | None:
    """
    Studio admin may book a client into another member's slot (ADR §6 delegate).
    Returns error code or None when allowed.
    """
    if int(actor_trainer_id) == int(target_trainer_id):
        return None

    slot_r = await session.execute(
        text("SELECT trainer_id, status FROM slots WHERE id = :sid"),
        {"sid": int(slot_id)},
    )
    slot_row = slot_r.fetchone()
    if slot_row is None:
        return "slot_not_found"
    if int(slot_row[0]) != int(target_trainer_id):
        return "slot_not_target_trainer"
    if str(slot_row[1]) not in ("available", "booked"):
        return "slot_not_available"

    membership = await resolve_collective_membership(
        session,
        actor_trainer_id,
        collective_slug=collective_slug,
    )
    if membership is None or not is_collective_studio_admin_role(membership.role):
        return "not_delegate_admin"
    if membership.schedule_mode != SCHEDULE_MODE_STUDIO_CENTRAL:
        return "not_studio_central"

    target_mem = await session.execute(
        text(
            """
            SELECT 1 FROM collective_members
            WHERE collective_id = :cid AND trainer_id = :tid AND status = 'active'
            """
        ),
        {"cid": membership.collective_id, "tid": int(target_trainer_id)},
    )
    if target_mem.fetchone() is None:
        return "target_not_member"
    return None


async def create_staff_center_session_booking(
    session: AsyncSession,
    *,
    actor_trainer_id: int,
    collective_slug: str,
    session_id: int,
    client_id: int,
    attendance_mode: str,
    center_coach_id: int | None = None,
    guest_count: int = 0,
    client_comment: str | None = None,
    target_trainer_id: int | None = None,
) -> dict[str, Any]:
    """Trainer or studio admin books client into center session (confirmed immediately)."""
    membership = await resolve_collective_membership(
        session,
        actor_trainer_id,
        collective_slug=collective_slug,
    )
    if membership is None:
        return {"error": "not_in_collective"}

    coach_id = center_coach_id
    if target_trainer_id is not None:
        if not is_collective_studio_admin_role(membership.role):
            return {"error": "not_delegate_admin"}
        mem_check = await session.execute(
            text(
                """
                SELECT 1 FROM collective_members
                WHERE collective_id = :cid AND trainer_id = :tid AND status = 'active'
                """
            ),
            {"cid": membership.collective_id, "tid": int(target_trainer_id)},
        )
        if mem_check.fetchone() is None:
            return {"error": "target_not_member"}
        coach_id = int(target_trainer_id)
    elif not is_collective_studio_admin_role(membership.role):
        r = await session.execute(
            text(
                """
                SELECT 1 FROM collective_session_coaches
                WHERE collective_session_id = :sid AND trainer_id = :tid
                """
            ),
            {"sid": int(session_id), "tid": int(actor_trainer_id)},
        )
        if r.fetchone() is None:
            return {"error": "not_assigned_coach"}
        if coach_id is None and (attendance_mode or "").startswith("center_coach"):
            coach_id = int(actor_trainer_id)

    created = await create_collective_session_booking(
        session,
        session_id=int(session_id),
        client_id=int(client_id),
        attendance_mode=attendance_mode,
        center_coach_id=coach_id if coach_id else None,
        guest_count=guest_count,
        client_comment=client_comment,
        created_by_trainer_id=int(actor_trainer_id),
    )
    return created or {"error": "session_not_found"}
