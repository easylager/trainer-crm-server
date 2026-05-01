"""Trainer Mini App: PATCH client CRM identity (ФИО) from client card."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, time, timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from tests.conftest import belarus_test_phone
from tests.db_catalog_helpers import require_seed_service_id


def _fresh_trainer_telegram_id() -> int:
    return 5_300_000_000 + (uuid.uuid4().int % 4_000_000_000)


@contextmanager
def patch_trainer_webapp_init(telegram_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        yield


async def _slot_for_trainer(db_session, trainer_id: int, service_id: int) -> int:
    d0 = date.today() + timedelta(days=12)
    st = time(10, 0)
    en = time(11, 0)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id)
            VALUES (:tid, :d, :st, :en, 'booked', 1, :svc)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": d0, "st": st, "en": en, "svc": service_id},
    )
    (slot_id,) = r.fetchone()
    await db_session.commit()
    return slot_id


@pytest.mark.asyncio
async def test_patch_trainer_client_identity_updates_names(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    trainer_id = r.fetchone()[0]
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'T', 'Trainer', 30)"
        ),
        {"tid": trainer_id},
    )
    service_id = await require_seed_service_id(db_session)
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    phone, phone_norm = belarus_test_phone(tg)
    r2 = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (NULL, 'Ann', 'Offline', :phone, :pn)
            RETURNING id
            """
        ),
        {"phone": phone, "pn": phone_norm},
    )
    client_id = int(r2.fetchone()[0])
    slot_id = await _slot_for_trainer(db_session, trainer_id, service_id)
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status)
            VALUES (:tid, :cid, :sid, :svc, 'confirmed')
            """
        ),
        {"tid": trainer_id, "cid": client_id, "sid": slot_id, "svc": service_id},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            resp = await http.patch(
                f"/api/webapp/trainer/clients/{client_id}/identity",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "first_name": "Анна",
                    "last_name": "Орлова",
                    "middle_name": "Сергеевна",
                },
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["client"]["id"] == client_id
    assert data["client"]["first_name"] == "Анна"
    assert data["client"]["last_name"] == "Орлова"
    assert data["client"]["middle_name"] == "Сергеевна"

    rdb = await db_session.execute(
        text("SELECT first_name, middle_name, last_name FROM clients WHERE id = :cid"),
        {"cid": client_id},
    )
    fn, mn, ln = rdb.fetchone()
    assert fn == "Анна"
    assert mn == "Сергеевна"
    assert ln == "Орлова"


@pytest.mark.asyncio
async def test_patch_trainer_client_identity_empty_body_400(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    trainer_id = r.fetchone()[0]
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'T', 'Trainer', 30)"
        ),
        {"tid": trainer_id},
    )
    service_id = await require_seed_service_id(db_session)
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    phone, phone_norm = belarus_test_phone(tg + 1)
    r2 = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (NULL, 'X', 'Y', :phone, :pn)
            RETURNING id
            """
        ),
        {"phone": phone, "pn": phone_norm},
    )
    client_id = int(r2.fetchone()[0])
    slot_id = await _slot_for_trainer(db_session, trainer_id, service_id)
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status)
            VALUES (:tid, :cid, :sid, :svc, 'confirmed')
            """
        ),
        {"tid": trainer_id, "cid": client_id, "sid": slot_id, "svc": service_id},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            resp = await http.patch(
                f"/api/webapp/trainer/clients/{client_id}/identity",
                headers={"X-Telegram-Init-Data": "mock"},
                json={},
            )
    assert resp.status_code == 400
