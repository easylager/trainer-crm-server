"""Trainer session wrap-up eligibility: all CRM clients, not only Telegram-linked."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import (
    create_booking,
    list_bookings_for_trainer_session_wrapup,
)
from src.shared.config import (
    TRAINER_SESSION_WRAPUP_REMAINING_SEC_MAX,
    TRAINER_SESSION_WRAPUP_REMAINING_SEC_MIN,
)
from src.shared.notification_hours import NOTIFICATION_TZ
from tests.conftest import belarus_test_phone
from tests.integration.test_booking_use_cases import _create_trainer_and_slot

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]


@pytest.mark.asyncio
async def test_wrapup_includes_phone_only_client(db_session: AsyncSession) -> None:
    """Phone CRM clients must receive trainer wrap-up the same as bot-linked clients."""
    tz = ZoneInfo(NOTIFICATION_TZ)
    now = datetime.now(tz)
    slot_end = now + timedelta(seconds=150)
    slot_date = slot_end.date()
    end_time = slot_end.time().replace(microsecond=0)
    start_time = (slot_end - timedelta(hours=1)).time().replace(microsecond=0)

    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, slot_date, start_time, end_time, status="booked"
    )
    phone, phone_norm = belarus_test_phone(900_000_001)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (first_name, last_name, phone, phone_normalized, is_sandbox)
            VALUES ('Телефон', 'Клиент', :phone, :pn, false)
            RETURNING id
            """
        ),
        {"phone": phone, "pn": phone_norm},
    )
    (client_id,) = r.fetchone()
    bid, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        created_by_trainer=True,
    )
    assert bid is not None

    rows = await list_bookings_for_trainer_session_wrapup(
        db_session,
        remaining_seconds_min=TRAINER_SESSION_WRAPUP_REMAINING_SEC_MIN,
        remaining_seconds_max=TRAINER_SESSION_WRAPUP_REMAINING_SEC_MAX,
    )
    ids = {r["booking_id"] for r in rows}
    assert bid in ids
    match = next(r for r in rows if r["booking_id"] == bid)
    assert match["client_telegram_id"] is None
