"""
Which trainers share CRM scope with a client row — roster link, active bookings, or training group.
Aligns with ``trainer_has_access_to_client`` in booking_use_cases.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_trainer_ids_for_client_crm_scope(session: AsyncSession, client_id: int) -> list[int]:
    """
    Distinct trainer ids that may manage this client. Order: explicit roster (stable),
    then trainers from non-cancelled bookings (most recent slot first),
    then active/trial group trainers. Used for family invite anchor trainer and trainer alerts.
    """
    cid = int(client_id)
    seen: set[int] = set()
    out: list[int] = []

    r_roster = await session.execute(
        text(
            """
            SELECT trainer_id FROM trainer_client_roster
            WHERE client_id = :cid
            ORDER BY trainer_id ASC
            """
        ),
        {"cid": cid},
    )
    for row in r_roster.fetchall():
        if row[0] is None:
            continue
        tid = int(row[0])
        if tid not in seen:
            seen.add(tid)
            out.append(tid)

    r_book = await session.execute(
        text(
            """
            SELECT b.trainer_id
            FROM bookings b
            INNER JOIN slots s ON s.id = b.slot_id
            WHERE b.client_id = :cid
              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
            ORDER BY s.slot_date DESC, s.start_time DESC NULLS LAST, b.trainer_id ASC
            """
        ),
        {"cid": cid},
    )
    for row in r_book.fetchall():
        if row[0] is None:
            continue
        tid = int(row[0])
        if tid not in seen:
            seen.add(tid)
            out.append(tid)

    r_grp = await session.execute(
        text(
            """
            SELECT g.trainer_id
            FROM training_group_members m
            INNER JOIN training_groups g ON g.id = m.training_group_id
            WHERE m.client_id = :cid
              AND m.status IN ('active', 'trial')
            ORDER BY g.trainer_id ASC
            """
        ),
        {"cid": cid},
    )
    for row in r_grp.fetchall():
        if row[0] is None:
            continue
        tid = int(row[0])
        if tid not in seen:
            seen.add(tid)
            out.append(tid)

    return out
