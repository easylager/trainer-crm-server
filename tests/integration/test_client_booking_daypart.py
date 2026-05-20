"""Per-client booking daypart persistence and slot filtering."""
from datetime import date, time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.client_booking_daypart_use_cases import (
    filter_slot_payloads_by_daypart,
    get_client_booking_daypart,
    set_client_booking_daypart,
)
from src.application.trainer_schedule_use_cases import replace_slots_for_day

BOOKING_DAYPART_MORNING = "morning"


@pytest.mark.asyncio
async def test_set_and_get_client_booking_daypart(db_session: AsyncSession) -> None:
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    r2 = await db_session.execute(
        text("INSERT INTO clients (telegram_id, first_name) VALUES (700001, 'A') RETURNING id")
    )
    (client_id,) = r2.fetchone()

    payload = await set_client_booking_daypart(db_session, trainer_id, client_id, BOOKING_DAYPART_MORNING)
    assert payload["value"] == BOOKING_DAYPART_MORNING
    assert payload["label"] == "Утро"

    loaded = await get_client_booking_daypart(db_session, trainer_id, client_id)
    assert loaded == BOOKING_DAYPART_MORNING

    cleared = await set_client_booking_daypart(db_session, trainer_id, client_id, None)
    assert cleared["value"] is None
    assert await get_client_booking_daypart(db_session, trainer_id, client_id) is None


@pytest.mark.asyncio
async def test_filter_slot_payloads_by_daypart(db_session: AsyncSession) -> None:
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    slot_day = date(2026, 6, 10)
    await replace_slots_for_day(
        db_session,
        trainer_id,
        slot_day,
        {8 * 60, 10 * 60, 14 * 60, 18 * 60},
        60,
    )
    await db_session.commit()

    slots = [
        {"id": 1, "start_time": "08:00"},
        {"id": 2, "start_time": "10:00"},
        {"id": 3, "start_time": "14:00"},
        {"id": 4, "start_time": "18:00"},
    ]
    morning = filter_slot_payloads_by_daypart(slots, BOOKING_DAYPART_MORNING)
    assert [s["id"] for s in morning] == [1, 2]

    all_slots = filter_slot_payloads_by_daypart(slots, None)
    assert len(all_slots) == 4
