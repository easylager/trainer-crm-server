"""PRD E7: GET/POST problem routes respect rollout gate."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, time, timedelta
from typing import Iterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal


def _fresh_trainer_telegram_id() -> int:
    import uuid

    return 5_300_000_000 + (uuid.uuid4().int % 4_000_000_000)


@contextmanager
def patch_trainer_webapp_init(telegram_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        yield


@pytest.mark.asyncio
@patch("src.api.routes.webapp.booking_problem_api_allowed_for_trainer", return_value=False)
async def test_problem_options_forbidden_when_rollout_denied(
    _mock_rollout,
    app_use_test_db,
    db_session,
) -> None:
    from tests.conftest import belarus_test_phone, unique_test_telegram_id
    from tests.db_catalog_helpers import require_seed_service_id

    tomorrow = date.today() + timedelta(days=1)
    service_id = await require_seed_service_id(db_session)
    trainer_tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": trainer_tg, "id": trainer_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'T', 'P', 25)"
        ),
        {"tid": trainer_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 1000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :et, 'booked')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": tomorrow, "st": time(10, 0), "et": time(11, 0)},
    )
    (slot_id,) = r.fetchone()
    ctg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(ctg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'L', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": ctg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    (booking_id,) = r.fetchone()
    await db_session.commit()

    with patch_trainer_webapp_init(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r0 = await client.get(
                f"/api/webapp/trainer/bookings/{booking_id}/problem-options",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert r0.status_code == 403
    assert r0.json().get("detail") == "booking_problem_rollout"
