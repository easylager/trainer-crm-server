"""Client booking anti-spam guards."""
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.client_booking_abuse_guard import (
    client_booking_attempt_allowed,
    client_booking_quota_error,
    reset_client_booking_limiter_for_tests,
)
from src.application.client_use_cases import get_or_create_client
from src.infrastructure.db.models import SUBSCRIPTION_TIER_ONLINE
from tests.api.test_webapp_client_miniapp_integration import _create_trainer_online_with_slot


@pytest.fixture(autouse=True)
def _reset_booking_limiter():
    reset_client_booking_limiter_for_tests()
    yield
    reset_client_booking_limiter_for_tests()


def test_client_booking_attempt_allowed_respects_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.application.client_booking_abuse_guard.Settings",
        lambda: type("S", (), {
            "client_booking_rate_max_requests": 2,
            "client_booking_rate_window_sec": 600.0,
        })(),
    )
    reset_client_booking_limiter_for_tests()
    assert client_booking_attempt_allowed(900001) is True
    assert client_booking_attempt_allowed(900001) is True
    assert client_booking_attempt_allowed(900001) is False


@pytest.mark.asyncio
async def test_client_booking_quota_error_when_pending_at_trainer_limit(
    app_use_test_db,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "src.application.client_booking_abuse_guard.Settings",
        lambda: type("S", (), {
            "client_booking_max_pending_per_trainer": 1,
            "client_booking_max_pending_global": 10,
        })(),
    )

    ref_day = date.today() + timedelta(days=14)
    trainer_id, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=ref_day, start_hours={11}, tier=SUBSCRIPTION_TIER_ONLINE
    )
    ctg = 7_200_000_001
    client_id = await get_or_create_client(db_session, ctg, phone="+375291234568")

    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'pending')
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    await db_session.flush()

    err = await client_booking_quota_error(db_session, client_id, trainer_id)
    assert err is not None
    assert "заявки" in err.lower()
