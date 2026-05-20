"""Per-trainer client preference: which slot times appear in self-booking."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.booking_daypart import (
    booking_daypart_api_payload,
    normalize_booking_daypart,
    slot_dict_matches_booking_daypart,
)


async def get_client_booking_daypart(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> str | None:
    r = await session.execute(
        text(
            """
            SELECT preferred_booking_daypart
            FROM trainer_client_notes
            WHERE trainer_id = :tid AND client_id = :cid
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return normalize_booking_daypart(row[0])


async def set_client_booking_daypart(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    daypart: str | None,
) -> dict[str, Any]:
    """
    Upsert only preferred_booking_daypart on trainer_client_notes.
    ``daypart`` None clears the restriction (client sees all slots).
    """
    normalized = normalize_booking_daypart(daypart)
    if daypart is not None and normalized is None:
        raise ValueError("invalid_booking_daypart")

    await session.execute(
        text(
            """
            INSERT INTO trainer_client_notes (trainer_id, client_id, preferred_booking_daypart)
            VALUES (:tid, :cid, :dp)
            ON CONFLICT (trainer_id, client_id)
            DO UPDATE SET
                preferred_booking_daypart = EXCLUDED.preferred_booking_daypart,
                updated_at = now()
            """
        ),
        {"tid": trainer_id, "cid": client_id, "dp": normalized},
    )
    await session.commit()
    return booking_daypart_api_payload(normalized)


def filter_slot_payloads_by_daypart(
    slots: list[dict[str, Any]],
    daypart: str | None,
) -> list[dict[str, Any]]:
    if not daypart:
        return slots
    return [s for s in slots if slot_dict_matches_booking_daypart(s, daypart)]


def filter_raw_slots_by_daypart(
    slots: list[dict[str, Any]],
    daypart: str | None,
) -> list[dict[str, Any]]:
    """Slots from list_slots (start_time may be time or str)."""
    if not daypart:
        return slots
    return [s for s in slots if slot_dict_matches_booking_daypart(s, daypart)]
