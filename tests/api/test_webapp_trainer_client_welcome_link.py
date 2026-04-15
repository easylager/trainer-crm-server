"""Trainer Mini App: per-client welcome link (bind Telegram to existing client row)."""
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
from src.application.booking_use_cases import trainer_has_access_to_client
from src.application.client_use_cases import (
    attach_telegram_id_to_client,
    get_client_id_by_telegram_id,
    get_client_telegram_id,
)
from src.application.welcome_link_use_cases import (
    WELCOME_TOKEN_TYPE_CLIENT_BIND,
    consume_welcome_link_token,
    create_welcome_link_token,
)
from src.shared.config import Settings
from tests.conftest import belarus_test_phone
from tests.db_catalog_helpers import require_seed_service_id


def _fresh_trainer_telegram_id() -> int:
    return 5_200_000_000 + (uuid.uuid4().int % 4_000_000_000)


@contextmanager
def patch_trainer_webapp_init(telegram_id: int) -> Iterator[None]:
    with patch("src.api.routes.webapp.require_telegram_user_id", return_value=telegram_id):
        yield


async def _trainer_service_and_slot(
    db_session,
    trainer_id: int,
    service_id: int,
) -> int:
    d0 = date.today() + timedelta(days=10)
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
async def test_trainer_client_welcome_link_401_without_init(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/trainer/clients/1/welcome-link?service_id=1")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_trainer_client_welcome_link_200_returns_one_time_url(
    app_use_test_db,
    db_session,
) -> None:
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
            "VALUES (:tid, 'Bind', 'Trainer', 30)"
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
    client_id = r2.fetchone()[0]
    slot_id = await _trainer_service_and_slot(db_session, trainer_id, service_id)
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

    with patch_trainer_webapp_init(tg), patch("src.api.routes.webapp.Settings") as ms:
        ms.return_value.client_bot_username = "BindWelcomeTestBot"
        ms.return_value.telegram_bot_token_trainer = Settings().telegram_bot_token_trainer
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/trainer/clients/{client_id}/welcome-link?service_id={service_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    link = data.get("welcome_link") or ""
    assert "t.me/BindWelcomeTestBot" in link
    assert "welcome_t_" in link


@pytest.mark.asyncio
async def test_trainer_client_welcome_link_400_when_already_linked(
    app_use_test_db,
    db_session,
) -> None:
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
            "VALUES (:tid, 'B', 'T', 30)"
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
    other_tg = tg + 99_000
    phone, phone_norm = belarus_test_phone(other_tg)
    r2 = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tid, 'X', 'Y', :phone, :pn)
            RETURNING id
            """
        ),
        {"tid": other_tg, "phone": phone, "pn": phone_norm},
    )
    client_id = r2.fetchone()[0]
    slot_id = await _trainer_service_and_slot(db_session, trainer_id, service_id)
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

    with patch_trainer_webapp_init(tg), patch("src.api.routes.webapp.Settings") as ms:
        ms.return_value.client_bot_username = "Bot"
        ms.return_value.telegram_bot_token_trainer = Settings().telegram_bot_token_trainer
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/trainer/clients/{client_id}/welcome-link?service_id={service_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_trainer_client_welcome_link_404_without_booking_access(
    app_use_test_db,
    db_session,
) -> None:
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
            "VALUES (:tid, 'A', 'B', 30)"
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
            VALUES (NULL, 'Solo', 'Client', :phone, :pn)
            RETURNING id
            """
        ),
        {"phone": phone, "pn": phone_norm},
    )
    orphan_client_id = r2.fetchone()[0]
    await db_session.commit()

    with patch_trainer_webapp_init(tg), patch("src.api.routes.webapp.Settings") as ms:
        ms.return_value.client_bot_username = "Bot"
        ms.return_value.telegram_bot_token_trainer = Settings().telegram_bot_token_trainer
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/trainer/clients/{orphan_client_id}/welcome-link?service_id={service_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_client_bind_token_attach_telegram_to_existing_row(
    app_use_test_db,
    db_session,
) -> None:
    """Domain flow: consume client_bind token + attach keeps single clients row."""
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    trainer_id = r.fetchone()[0]
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'T', 'T', 30)"
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
    phone, phone_norm = belarus_test_phone(8_080_808_080)
    r2 = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (NULL, 'Ann', 'Bind', :phone, :pn)
            RETURNING id
            """
        ),
        {"phone": phone, "pn": phone_norm},
    )
    client_id = r2.fetchone()[0]
    d0 = date.today() + timedelta(days=11)
    st = time(12, 0)
    en = time(13, 0)
    r3 = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id)
            VALUES (:tid, :d, :st, :en, 'booked', 1, :svc)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": d0, "st": st, "en": en, "svc": service_id},
    )
    slot_id = r3.fetchone()[0]
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

    assert await trainer_has_access_to_client(db_session, trainer_id, client_id) is True
    token_uuid = await create_welcome_link_token(
        db_session,
        WELCOME_TOKEN_TYPE_CLIENT_BIND,
        trainer_id,
        service_id=service_id,
        client_id=client_id,
    )
    payload = await consume_welcome_link_token(db_session, token_uuid)
    assert payload is not None
    assert payload["type"] == WELCOME_TOKEN_TYPE_CLIENT_BIND
    assert payload["client_id"] == client_id
    client_telegram = 9_009_009_009
    other = await get_client_id_by_telegram_id(db_session, client_telegram)
    assert other is None
    ok = await attach_telegram_id_to_client(db_session, client_id, client_telegram)
    await db_session.commit()
    assert ok is True
    assert await get_client_telegram_id(db_session, client_id) == client_telegram
    r_count = await db_session.execute(text("SELECT COUNT(*) FROM clients WHERE phone_normalized = :pn"), {"pn": phone_norm})
    assert r_count.fetchone()[0] == 1
