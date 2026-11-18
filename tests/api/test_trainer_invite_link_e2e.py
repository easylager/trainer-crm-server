"""
Сквозной сценарий ссылки тренера (``welcome_ref``): клиент, заведённый тренером заранее, регистрируется
через форму бота и при входе в приложение видит своего тренера, записи и абонементы.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.booking_use_cases import create_booking, link_trainer_client_roster
from tests.api.test_webapp_client_miniapp_integration import (
    _client_auth_headers,
    _create_trainer_online_with_slot,
    patch_client_init_auth,
)


def _tg() -> int:
    return 7_900_000_000 + (uuid.uuid4().int % 1_000_000_000)


async def _trainer_made_client(db_session, *, phone_e164: str, normalized: str) -> int:
    """Клиент, которого тренер завёл руками: есть телефон, нет Telegram."""
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (first_name, phone, phone_normalized, is_sandbox)
            VALUES ('Заведённый', :p, :n, false) RETURNING id
            """
        ),
        {"p": phone_e164, "n": normalized},
    )
    cid = int(r.scalar_one())
    await db_session.commit()
    return cid


async def _give_pass(db_session, *, trainer_id: int, client_id: int) -> None:
    pid = (
        await db_session.execute(
            text(
                "INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active) "
                "VALUES (:t, 'Абонемент 8', 8, 8000, true) RETURNING id"
            ),
            {"t": trainer_id},
        )
    ).scalar_one()
    await db_session.execute(
        text(
            "INSERT INTO pass_instances (client_id, pass_product_id, sessions_remaining, sessions_total, "
            "price_cents, status) VALUES (:c, :p, 5, 8, 8000, 'active')"
        ),
        {"c": client_id, "p": pid},
    )
    await db_session.commit()


async def _setup(db_session, *, phone_digits_seed: int):
    day = date.today() + timedelta(days=3)
    trainer_id, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=day, start_hours={12, 13}
    )
    normalized = f"37529{phone_digits_seed % 10**7:07d}"  # реальный код оператора, иначе 8029… не распознать
    phone_e164 = f"+{normalized}"
    client_id = await _trainer_made_client(db_session, phone_e164=phone_e164, normalized=normalized)
    await link_trainer_client_roster(db_session, trainer_id, client_id)
    booking_id, _ = await create_booking(
        db_session, slot_id, trainer_id, client_id, service_id, created_by_trainer=True
    )
    assert booking_id
    await db_session.commit()
    await _give_pass(db_session, trainer_id=trainer_id, client_id=client_id)
    return trainer_id, client_id, booking_id, phone_e164


async def _register(tg: int, trainer_id: int, phone: str, name: str = "Иван"):
    with patch_client_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            return await c.post(
                "/api/webapp/client/self-register",
                json={"trainer_id": trainer_id, "phone": phone, "first_name": name},
                headers=_client_auth_headers(),
            )


async def _get(tg: int, path: str):
    with patch_client_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            return await c.get(f"/api/webapp{path}", headers=_client_auth_headers())


@pytest.mark.asyncio
async def test_precreated_client_sees_booking_pass_and_trainer_after_registration(
    app_use_test_db, db_session
) -> None:
    tg = _tg()
    trainer_id, client_id, booking_id, phone = await _setup(db_session, phone_digits_seed=tg)

    # До регистрации Telegram-аккаунт ничего не видит.
    before = await _get(tg, "/client/passes")
    assert before.json()["items"] == []

    r = await _register(tg, trainer_id, phone)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "linked", "client_id": client_id}  # тот же клиент, не дубль

    tg_in_db = (
        await db_session.execute(text("SELECT telegram_id FROM clients WHERE id = :c"), {"c": client_id})
    ).scalar_one()
    assert int(tg_in_db) == tg

    passes = (await _get(tg, "/client/passes")).json()["items"]
    assert len(passes) == 1

    bookings = (await _get(tg, "/client/bookings")).json()
    flat = str(bookings)
    assert str(booking_id) in flat, bookings
    assert bookings["pending_referral"] in (None, {}, False) or not bookings["pending_referral"]

    primary = (
        await db_session.execute(
            text("SELECT 1 FROM client_trainer_edges WHERE client_id = :c AND trainer_id = :t AND is_primary"),
            {"c": client_id, "t": trainer_id},
        )
    ).first()
    assert primary is not None, "тренер должен стать основным"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fmt",
    [
        "plain",
        "spaces",
        pytest.param(
            "local8",
            marks=pytest.mark.xfail(
                strict=True,
                reason="self-register ищет клиента по сырой строке body.phone, а не по нормализованной: "
                "'8029…' не находит '+375 29…' и создаёт дубль. Форма шлёт E.164, так что в проде не видно.",
            ),
        ),
    ],
)
async def test_phone_format_variants_find_the_same_precreated_client(app_use_test_db, db_session, fmt) -> None:
    tg = _tg()
    trainer_id, client_id, _b, phone = await _setup(db_session, phone_digits_seed=tg)
    d = phone.lstrip("+")  # 375XXXXXXXXX
    typed = {
        "plain": phone,
        "spaces": f"+{d[:3]} {d[3:5]} {d[5:8]}-{d[8:10]}-{d[10:]}",
        "local8": f"80{d[3:]}",
    }[fmt]
    r = await _register(tg, trainer_id, typed)
    assert r.status_code == 200, (typed, r.text)
    assert r.json()["client_id"] == client_id, (typed, r.json())


@pytest.mark.asyncio
async def test_unknown_phone_creates_new_client_in_roster_without_foreign_data(app_use_test_db, db_session) -> None:
    other_tg = _tg()
    trainer_id, other_client_id, _b, _p = await _setup(db_session, phone_digits_seed=other_tg)
    tg = _tg()
    new_phone = f"+37533{(tg + 12345) % 10**7:07d}"
    r = await _register(tg, trainer_id, new_phone, "Новый")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "created"
    new_id = r.json()["client_id"]
    assert new_id != other_client_id
    in_roster = (
        await db_session.execute(
            text("SELECT 1 FROM trainer_client_roster WHERE trainer_id = :t AND client_id = :c"),
            {"t": trainer_id, "c": new_id},
        )
    ).first()
    assert in_roster is not None
    # Чужих абонементов и записей у нового клиента нет.
    assert (await _get(tg, "/client/passes")).json()["items"] == []


@pytest.mark.asyncio
async def test_phone_of_another_telegram_account_is_rejected(app_use_test_db, db_session) -> None:
    owner_tg = _tg()
    trainer_id, client_id, _b, phone = await _setup(db_session, phone_digits_seed=owner_tg)
    assert (await _register(owner_tg, trainer_id, phone)).status_code == 200
    intruder = _tg()
    r = await _register(intruder, trainer_id, phone)
    assert r.status_code == 409, r.text
    # Данные владельца не утекли чужому аккаунту.
    assert (await _get(intruder, "/client/passes")).json()["items"] == []
