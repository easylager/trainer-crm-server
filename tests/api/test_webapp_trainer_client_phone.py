"""
Trainer Mini App: PATCH client phone + the merge-duplicate-accounts follow-up.

Phone editing never existed before (see merge_clients — this is Step 1 built on it): a trainer
typo on manual add is exactly how the platform ends up with two `clients` rows for one person.
"""
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
    return 5_400_000_000 + (uuid.uuid4().int % 4_000_000_000)


def _fresh_client_telegram_id() -> int:
    return 7_500_000_000 + (uuid.uuid4().int % 2_000_000_000)


@contextmanager
def patch_trainer_webapp_init(telegram_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        yield


async def _insert_trainer(db_session, tg: int) -> int:
    r = await db_session.execute(text("INSERT INTO trainers (status, telegram_id) VALUES ('active', :tg) RETURNING id"), {"tg": tg})
    trainer_id = int(r.scalar_one())
    await db_session.execute(
        text("INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'T', 'Trainer', 30)"),
        {"tid": trainer_id},
    )
    return trainer_id


async def _insert_client_on_roster(
    db_session, trainer_id: int, *, first_name: str, last_name: str | None, telegram_id: int | None, phone_seed: int
) -> int:
    phone, phone_norm = belarus_test_phone(phone_seed)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, :fn, :ln, :ph, :pn) RETURNING id
            """
        ),
        {"tg": telegram_id, "fn": first_name, "ln": last_name, "ph": phone, "pn": phone_norm},
    )
    client_id = int(r.scalar_one())
    await db_session.execute(
        text("INSERT INTO trainer_client_roster (trainer_id, client_id) VALUES (:t, :c)"),
        {"t": trainer_id, "c": client_id},
    )
    return client_id


async def _insert_upcoming_booking(db_session, trainer_id: int, client_id: int, service_id: int) -> int:
    slot_day = date.today() + timedelta(days=10)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id)
            VALUES (:tid, :d, :st, :en, 'booked', 1, :svc) RETURNING id
            """
        ),
        {"tid": trainer_id, "d": slot_day, "st": time(10, 0), "en": time(11, 0), "svc": service_id},
    )
    slot_id = int(r.scalar_one())
    r = await db_session.execute(
        text(
            "INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status) "
            "VALUES (:tid, :cid, :sid, :svc, 'confirmed') RETURNING id"
        ),
        {"tid": trainer_id, "cid": client_id, "sid": slot_id, "svc": service_id},
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_patch_phone_no_conflict_updates(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _insert_trainer(db_session, tg)
    client_id = await _insert_client_on_roster(
        db_session, trainer_id, first_name="Ann", last_name="Offline", telegram_id=None, phone_seed=_fresh_client_telegram_id()
    )
    await db_session.commit()

    new_phone, new_norm = belarus_test_phone(_fresh_client_telegram_id())
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            resp = await http.patch(
                f"/api/webapp/trainer/clients/{client_id}/phone",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"phone": new_phone},
            )
    assert resp.status_code == 200, resp.text

    r = await db_session.execute(text("SELECT phone_normalized FROM clients WHERE id = :c"), {"c": client_id})
    assert r.scalar_one() == new_norm


@pytest.mark.asyncio
async def test_patch_phone_conflict_with_accessible_client_is_mergeable(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _insert_trainer(db_session, tg)
    other_tg = _fresh_client_telegram_id()
    other_client_id = await _insert_client_on_roster(
        db_session, trainer_id, first_name="Татьяна", last_name="Силантьева", telegram_id=other_tg, phone_seed=other_tg
    )
    editing_client_id = await _insert_client_on_roster(
        db_session, trainer_id, first_name="Татьяна", last_name=None, telegram_id=None, phone_seed=_fresh_client_telegram_id()
    )
    other_phone, _ = belarus_test_phone(other_tg)
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            resp = await http.patch(
                f"/api/webapp/trainer/clients/{editing_client_id}/phone",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"phone": other_phone},
            )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "phone_in_use"
    assert detail["mergeable"] is True
    assert detail["other_client_id"] == other_client_id
    assert detail["preview"]["has_telegram"] is True
    assert "Татьяна" in detail["preview"]["display_name"]


@pytest.mark.asyncio
async def test_patch_phone_conflict_with_inaccessible_client_is_not_mergeable(app_use_test_db, db_session) -> None:
    tg_a = _fresh_trainer_telegram_id()
    tg_b = _fresh_trainer_telegram_id()
    trainer_a = await _insert_trainer(db_session, tg_a)
    trainer_b = await _insert_trainer(db_session, tg_b)

    other_tg = _fresh_client_telegram_id()
    await _insert_client_on_roster(
        db_session, trainer_b, first_name="Чужой", last_name="Клиент", telegram_id=other_tg, phone_seed=other_tg
    )
    editing_client_id = await _insert_client_on_roster(
        db_session, trainer_a, first_name="Свой", last_name=None, telegram_id=None, phone_seed=_fresh_client_telegram_id()
    )
    other_phone, _ = belarus_test_phone(other_tg)
    await db_session.commit()

    with patch_trainer_webapp_init(tg_a):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            resp = await http.patch(
                f"/api/webapp/trainer/clients/{editing_client_id}/phone",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"phone": other_phone},
            )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["mergeable"] is False
    assert detail["other_client_id"] is None
    assert detail["preview"] is None


@pytest.mark.asyncio
async def test_merge_endpoint_moves_booking_to_telegram_survivor(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _insert_trainer(db_session, tg)
    service_id = await require_seed_service_id(db_session)
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )

    other_tg = _fresh_client_telegram_id()
    survivor_client_id = await _insert_client_on_roster(
        db_session, trainer_id, first_name="Татьяна", last_name="Силантьева", telegram_id=other_tg, phone_seed=other_tg
    )
    stub_client_id = await _insert_client_on_roster(
        db_session, trainer_id, first_name="Татьяна", last_name=None, telegram_id=None, phone_seed=_fresh_client_telegram_id()
    )
    booking_id = await _insert_upcoming_booking(db_session, trainer_id, stub_client_id, service_id)
    other_phone, other_norm = belarus_test_phone(other_tg)
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            conflict = await http.patch(
                f"/api/webapp/trainer/clients/{stub_client_id}/phone",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"phone": other_phone},
            )
            assert conflict.status_code == 409

            merged = await http.post(
                f"/api/webapp/trainer/clients/{stub_client_id}/phone/merge",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"other_client_id": survivor_client_id, "phone": other_phone},
            )
    assert merged.status_code == 200, merged.text
    assert merged.json()["client"]["id"] == survivor_client_id

    r = await db_session.execute(text("SELECT COUNT(*) FROM clients WHERE id = :c"), {"c": stub_client_id})
    assert r.scalar_one() == 0

    r = await db_session.execute(text("SELECT client_id FROM bookings WHERE id = :b"), {"b": booking_id})
    assert r.scalar_one() == survivor_client_id

    r = await db_session.execute(text("SELECT last_name, phone_normalized FROM clients WHERE id = :c"), {"c": survivor_client_id})
    last_name, phone_norm = r.fetchone()
    assert last_name == "Силантьева"
    assert phone_norm == other_norm


@pytest.mark.asyncio
async def test_merge_endpoint_rejects_stale_conflict(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _insert_trainer(db_session, tg)

    other_tg = _fresh_client_telegram_id()
    other_client_id = await _insert_client_on_roster(
        db_session, trainer_id, first_name="Другой", last_name=None, telegram_id=other_tg, phone_seed=other_tg
    )
    editing_client_id = await _insert_client_on_roster(
        db_session, trainer_id, first_name="Я", last_name=None, telegram_id=None, phone_seed=_fresh_client_telegram_id()
    )
    other_phone, _ = belarus_test_phone(other_tg)
    # Other client's number changed after the trainer saw the 409 — merge must refuse, not blindly proceed.
    new_other_phone, new_other_norm = belarus_test_phone(_fresh_client_telegram_id())
    await db_session.execute(
        text("UPDATE clients SET phone = :ph, phone_normalized = :pn WHERE id = :c"),
        {"ph": new_other_phone, "pn": new_other_norm, "c": other_client_id},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            resp = await http.post(
                f"/api/webapp/trainer/clients/{editing_client_id}/phone/merge",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"other_client_id": other_client_id, "phone": other_phone},
            )
    assert resp.status_code == 409
