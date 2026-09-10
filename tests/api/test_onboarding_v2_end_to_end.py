"""
Сквозной тест главного инварианта онбординга v2.

> Модерация решает видимость в каталоге, а не право тренера работать.

Проверяем оба конца одновременно, потому что порознь они ничего не доказывают:
тренер без модерации и почти без профиля проходит первый экран, а его собственный
ученик по личной ссылке действительно видит слоты и может записаться — при этом
в публичном каталоге этого тренера нет.

Если этот тест когда-нибудь упадёт, значит гейт вернулся.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from tests.conftest import belarus_test_phone
from tests.db_catalog_helpers import require_seed_service_id

QUICK_SETUP_URL = "/api/webapp/trainer/onboarding/quick-setup"


def _fresh_tg_id() -> int:
    return 5_800_000_000 + (uuid.uuid4().int % 4_000_000_000)


@contextmanager
def _as_trainer(telegram_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        yield


@contextmanager
def _as_client(telegram_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        yield


@pytest.mark.asyncio
async def test_unmoderated_trainer_can_be_booked_but_is_not_in_the_catalog(
    app_use_test_db, db_session
) -> None:
    trainer_tg = _fresh_tg_id()
    client_tg = _fresh_tg_id()

    # 1. Ровно то, что создаёт /start: строка тренера и привязанный Telegram. Больше ничего.
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('pending_profile') RETURNING id")
    )
    trainer_id = int(r.fetchone()[0])
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": trainer_tg, "id": trainer_id},
    )
    await db_session.commit()

    service_id = await require_seed_service_id(db_session)

    # 2. Первый экран. Никакой анкеты, города, площадки, телефона и фото.
    with _as_trainer(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            setup = await c.post(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "service_ids": [service_id],
                    "days": [{"day_of_week": d, "hours": [7, 18]} for d in range(7)],
                    "duration_minutes": 60,
                },
            )
            access = await c.get(
                "/api/webapp/trainer/access",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            schedule = await c.get(
                "/api/webapp/schedule",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert setup.status_code == 200, setup.text
    assert setup.json()["open_slots_ahead"] > 0
    assert access.status_code == 200, access.text
    acc = access.json()
    assert acc["access_state"] == "active"
    assert acc["schedule_unlocked"] is True
    assert acc["is_active"] is False, "каталожная модерация не пройдена — is_active остаётся ложью"
    assert acc["trainer_status"] == "pending_profile"
    assert schedule.status_code == 200, schedule.text
    assert (schedule.json().get("slots") or []), "свой календарь открыт без анкеты"

    # ``quick-setup`` включает welcome-триал со всеми модулями — без модуля online
    # обещание «ученик запишется сам» было бы невыполнимым.
    r = await db_session.execute(
        text("SELECT modules FROM trainer_subscriptions WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    mods = r.scalar() or {}
    assert mods.get("online") is True, "онлайн-запись должна работать с первой минуты триала"

    # 3. Ученик по личной ссылке не только видит слоты — он записывается.
    phone, _pn = belarus_test_phone(client_tg)
    with _as_client(client_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            slots = await c.get(
                f"/api/webapp/client/slots?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert slots.status_code == 200, slots.text
            body = slots.json()
            assert body["online_booking_available"] is True
            assert len(body["slots"]) > 0, "ученик должен видеть свободное время"
            slot_id = int(body["slots"][-1]["id"])
            booked = await c.post(
                "/api/webapp/client/booking",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "slot_id": slot_id,
                    "service_id": service_id,
                    "phone": phone,
                    "first_name": "Ученик",
                },
            )
    assert booked.status_code == 200, booked.text
    assert isinstance(booked.json().get("booking_id"), int)

    r = await db_session.execute(
        text("SELECT status FROM trainers WHERE id = :t"),
        {"t": trainer_id},
    )
    assert r.scalar() == "pending_profile"

    with _as_trainer(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            checklist = await c.get(
                "/api/webapp/trainer/onboarding/checklist",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert checklist.status_code == 200, checklist.text
    assert (checklist.json().get("next_step") or {}).get("key") is None, (
        "после первой записи хаб не выносит отдельную карточку про профиль/площадку"
    )

    # 4. И при этом тренера нет в публичном каталоге — модерацию он не проходил.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        catalog = await c.get("/api/public/trainers?limit=200")
    assert catalog.status_code == 200
    payload = catalog.json()
    rows = payload if isinstance(payload, list) else (payload.get("trainers") or payload.get("items") or [])
    assert trainer_id not in [t.get("id") for t in rows], "в каталог пускает только модерация"


@pytest.mark.asyncio
async def test_the_first_screen_never_demands_a_profile(app_use_test_db, db_session) -> None:
    """
    Регрессия на возврат гейта: после первого экрана у тренера по-прежнему нет ни города,
    ни телефона, ни описания, ни площадки — и это не мешает ему работать.
    """
    trainer_tg = _fresh_tg_id()
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('pending_profile') RETURNING id")
    )
    trainer_id = int(r.fetchone()[0])
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": trainer_tg, "id": trainer_id},
    )
    await db_session.commit()

    service_id = await require_seed_service_id(db_session)

    with _as_trainer(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "service_ids": [service_id],
                    "days": [{"day_of_week": 0, "hours": [9]}],
                    "duration_minutes": 60,
                },
            )
            checklist = await c.get(
                "/api/webapp/trainer/onboarding/checklist",
                headers={"X-Telegram-Init-Data": "mock"},
            )

    r = await db_session.execute(
        text("SELECT city_id, phone, description FROM trainer_profiles WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    city_id, phone, description = r.fetchone()
    assert city_id is None and not phone and not description

    data = checklist.json()
    assert data["schedule_unlocked"] is True
    assert data["slots_locked_reason"] is None
    assert (data.get("next_step") or {}).get("key") == "share_link", (
        "следующий шаг после расписания — отдать ссылку ученику, а не заполнять анкету"
    )


@pytest.mark.asyncio
async def test_unmoderated_trainer_can_create_pass_and_use_crm_tools(
    app_use_test_db, db_session
) -> None:
    """
    Каталожная модерация не блокирует абонементы, сертификаты, заявки и ссылки.
    Тот же ``pending_profile``, что после /start: карточки в каталоге нет — CRM есть.
    """
    trainer_tg = _fresh_tg_id()
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('pending_profile') RETURNING id")
    )
    trainer_id = int(r.fetchone()[0])
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": trainer_tg, "id": trainer_id},
    )
    await db_session.commit()

    service_id = await require_seed_service_id(db_session)
    headers = {"X-Telegram-Init-Data": "mock"}

    with _as_trainer(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            setup = await c.post(
                QUICK_SETUP_URL,
                headers=headers,
                json={
                    "service_ids": [service_id],
                    "days": [{"day_of_week": 0, "hours": [9]}],
                    "duration_minutes": 60,
                },
            )
            assert setup.status_code == 200, setup.text

            created = await c.post(
                "/api/webapp/trainer/pass-products",
                headers=headers,
                json={
                    "name": "Тестовый",
                    "sessions_total": 5,
                    "price_cents": 10000,
                    "service_ids": [],
                    "tier_kinds": [],
                },
            )
            listed = await c.get("/api/webapp/trainer/pass-products", headers=headers)
            cert_created = await c.post(
                "/api/webapp/trainer/certificate-products",
                headers=headers,
                json={"name": "Сертификат 50", "amount_cents": 5000, "expires_in_days": 90},
            )
            certs = await c.get("/api/webapp/trainer/certificate-products", headers=headers)
            requests = await c.get("/api/webapp/trainer/requests/summary", headers=headers)
            welcome = await c.get("/api/webapp/trainer/welcome-link/eligibility", headers=headers)

    assert created.status_code == 200, created.text
    assert isinstance(created.json().get("id"), int)
    assert listed.status_code == 200, listed.text
    assert any(p.get("id") == created.json()["id"] for p in (listed.json().get("items") or []))
    assert cert_created.status_code == 200, cert_created.text
    assert isinstance(cert_created.json().get("id"), int)
    assert certs.status_code == 200, certs.text
    assert any(p.get("id") == cert_created.json()["id"] for p in (certs.json().get("items") or []))
    assert requests.status_code == 200, requests.text
    assert welcome.status_code == 200, welcome.text

    r = await db_session.execute(
        text("SELECT status FROM trainers WHERE id = :t"),
        {"t": trainer_id},
    )
    assert r.scalar() == "pending_profile"


@pytest.mark.asyncio
async def test_deactivated_trainer_still_cannot_create_pass_product(
    app_use_test_db, db_session
) -> None:
    """The one closed door: admin paused the account."""
    trainer_tg = _fresh_tg_id()
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('deactivated') RETURNING id")
    )
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": trainer_tg, "id": int(r.fetchone()[0])},
    )
    await db_session.commit()

    with _as_trainer(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            created = await c.post(
                "/api/webapp/trainer/pass-products",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "name": "Тестовый",
                    "sessions_total": 5,
                    "price_cents": 10000,
                    "service_ids": [],
                    "tier_kinds": [],
                },
            )
    assert created.status_code == 403
