"""TASK-357: витрина тренеров Mini App и запись ребёнка новым учеником."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.infrastructure.db.models import SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE
from tests.api.test_arena_trainer_windows import _slot
from tests.api.test_public_place_page import _place
from tests.api.test_site_trainers import _trainer_on
from tests.api.test_webapp_client_miniapp_integration import (
    _ensure_trainer_subscription_tier,
    _fresh_client_telegram_id,
    patch_client_init_auth,
)
from tests.conftest import belarus_test_phone


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _completed_booking(db_session, tid: int, *, days_ago: int, self_booking: bool = False) -> None:
    tg = _fresh_client_telegram_id()
    if self_booking:
        await db_session.execute(text("UPDATE trainers SET telegram_id = :tg WHERE id = :t"), {"tg": tg, "t": tid})
    cid = (
        await db_session.execute(
            text("INSERT INTO clients (first_name, telegram_id) VALUES ('Ученик', :tg) RETURNING id"), {"tg": tg}
        )
    ).scalar_one()
    sid = (
        await db_session.execute(
            text(
                "INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity) "
                "VALUES (:t, :d, '10:00', '11:00', 'booked', 1) RETURNING id"
            ),
            {"t": tid, "d": date.today() - timedelta(days=days_ago)},
        )
    ).scalar_one()
    await db_session.execute(
        text(
            "INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status) "
            "VALUES (:s, :t, :c, (SELECT service_id FROM trainer_services WHERE trainer_id = :t LIMIT 1), 'completed')"
        ),
        {"s": sid, "t": tid, "c": cid},
    )


@pytest.mark.asyncio
async def test_showcase_has_from_price_glide_since_windows_and_ice_arenas(app_use_test_db, db_session) -> None:
    async with _client() as client:
        place = await _place(db_session)
        tid = await _trainer_on(db_session, client, place, first_name=f"Анна{uuid.uuid4().hex[:4]}")
        await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
        await _slot(db_session, tid, days=2, hour=12, arena_id=place["arena_id"])
        # Самозапись раньше — не считается; первое настоящее занятие — 40 дней назад.
        await _completed_booking(db_session, tid, days_ago=400, self_booking=True)
        await _completed_booking(db_session, tid, days_ago=40)
        await db_session.commit()
        body = (await client.get(f"/api/public/trainer-showcase?city_id={place['city_id']}")).json()

    item = next(t for t in body["items"] if t["id"] == tid)
    first = date.today() - timedelta(days=40)
    assert item["glide_since"] == f"{first.year:04d}-{first.month:02d}"
    # Тарифы фикстуры 45/50, групповая 25, абонемент 41,87 → «от 25» из trainer_min_price.
    assert item["min_session_price_cents"] == 2500
    # «от» по вкладкам считает сервер (``direction_min_price``); ключи — вкладки Mini App.
    assert item["min_price_by_direction"] == {
        "all": {"cents": 2500, "currency": "BYN"},
        "s-nulya": {"cents": 2500, "currency": "BYN"},
    }
    assert item["can_book"] is True
    assert len(item["windows"]) == 1 and item["windows"][0]["slot_id"]
    assert [a["id"] for a in item["arenas"]] == [place["arena_id"]]
    svc = item["services"][0]
    assert svc["is_public"] is True
    # Публичная услуга сама — направление; поле привязки своей услуги (TASK-353) есть и пустое.
    assert "direction_service_id" in svc and svc["direction_service_id"] is None
    # Групповой слот записывается по COALESCE(group_price_cents, price_cents) — витрина показывает ту же цену.
    assert svc["group_price_cents"] == 2500
    assert {t["tier_kind"] for t in svc["price_tiers"]} >= {"child", "adult"}
    # Число занятий не отдаём (решение владельца) — только месяц.
    assert not any("count" in k and "rating" not in k for k in item)


@pytest.mark.asyncio
async def test_showcase_without_online_booking_has_no_windows(app_use_test_db, db_session) -> None:
    async with _client() as client:
        place = await _place(db_session)
        tid = await _trainer_on(db_session, client, place, first_name=f"Катя{uuid.uuid4().hex[:4]}")
        await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_CRM)
        await _slot(db_session, tid, days=2, hour=12, arena_id=place["arena_id"])
        await db_session.commit()
        body = (await client.get(f"/api/public/trainer-showcase?city_id={place['city_id']}")).json()
    item = next(t for t in body["items"] if t["id"] == tid)
    assert item["can_book"] is False
    assert item["windows"] == []
    assert item["glide_since"] is None


@pytest.mark.asyncio
async def test_new_client_child_booking_puts_phone_on_child_profile(app_use_test_db, db_session) -> None:
    """Новый ученик выбирает «Ребёнок»: профиль ребёнка создаётся до записи, телефон — из записи."""
    async with _client() as client:
        place = await _place(db_session)
        trainer_id = await _trainer_on(db_session, client, place, first_name=f"Лена{uuid.uuid4().hex[:4]}")
    await _ensure_trainer_subscription_tier(db_session, trainer_id, SUBSCRIPTION_TIER_ONLINE)
    slot_id = await _slot(db_session, trainer_id, days=3, hour=12, arena_id=place["arena_id"])
    service_id = (
        await db_session.execute(text("SELECT service_id FROM trainer_services WHERE trainer_id = :t"), {"t": trainer_id})
    ).scalar_one()
    variant_id = (
        await db_session.execute(
            text("SELECT id FROM trainer_service_price_variants WHERE trainer_id = :t AND tier_kind = 'child'"),
            {"t": trainer_id},
        )
    ).scalar_one()
    await db_session.commit()
    ctg = _fresh_client_telegram_id()
    phone, _norm = belarus_test_phone(ctg)
    headers = {"X-Telegram-Init-Data": "mock"}
    with patch_client_init_auth(ctg):
        async with _client() as client:
            created = await client.post("/api/webapp/client/profiles", json={"first_name": "Соня"}, headers=headers)
            assert created.status_code == 200, created.text
            child_id = created.json()["client_id"]
            book = await client.post(
                "/api/webapp/client/booking",
                json={
                    "slot_id": slot_id,
                    "phone": phone,
                    "service_id": service_id,
                    "service_price_variant_id": variant_id,
                },
                headers={**headers, "X-Profile-Id": str(child_id)},
            )
    assert book.status_code == 200, book.text
    row = (
        await db_session.execute(
            text("SELECT b.client_id, c.first_name, c.phone FROM bookings b JOIN clients c ON c.id = b.client_id WHERE b.id = :b"),
            {"b": book.json()["booking_id"]},
        )
    ).one()
    assert row[0] == child_id and row[1] == "Соня"
    assert row[2] == phone


@pytest.mark.asyncio
async def test_request_sheet_phone_is_saved_for_trainer(app_use_test_db, db_session) -> None:
    """Шторка «Оставить заявку»: телефон для тренера сохраняется у клиента; без телефона — как раньше."""
    async with _client() as client:
        place = await _place(db_session)
        trainer_id = await _trainer_on(db_session, client, place, first_name=f"Катя{uuid.uuid4().hex[:4]}")
    service_id = (
        await db_session.execute(text("SELECT service_id FROM trainer_services WHERE trainer_id = :t"), {"t": trainer_id})
    ).scalar_one()
    await db_session.commit()
    ctg = _fresh_client_telegram_id()
    phone, _norm = belarus_test_phone(ctg)
    headers = {"X-Telegram-Init-Data": "mock"}
    body = {"city_id": place["city_id"], "service_id": service_id, "trainer_id": trainer_id, "first_name": "Анна"}
    with patch_client_init_auth(ctg):
        async with _client() as client:
            bad = await client.post("/api/webapp/client/request", json={**body, "phone": "12"}, headers=headers)
            ok = await client.post("/api/webapp/client/request", json={**body, "phone": phone}, headers=headers)
    assert bad.status_code == 400
    assert ok.status_code == 200, ok.text
    saved = (
        await db_session.execute(text("SELECT phone FROM clients WHERE telegram_id = :tg"), {"tg": ctg})
    ).scalar_one()
    assert saved == phone


@pytest.mark.asyncio
async def test_single_slot_link_beyond_two_weeks_and_taken(app_use_test_db, db_session) -> None:
    """Ссылка ``trainer_<id>_s_<slot>``: время за пределами /client/slots открывается; занятое — нет."""
    async with _client() as client:
        place = await _place(db_session)
        tid = await _trainer_on(db_session, client, place, first_name=f"Ира{uuid.uuid4().hex[:4]}")
    await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
    far = await _slot(db_session, tid, days=20, hour=12, arena_id=place["arena_id"])
    taken = await _slot(db_session, tid, days=4, hour=12, arena_id=place["arena_id"], status="booked")
    await db_session.commit()
    headers = {"X-Telegram-Init-Data": "mock"}
    with patch_client_init_auth(_fresh_client_telegram_id()):
        async with _client() as client:
            ok = (await client.get(f"/api/webapp/client/slot/{far}?trainer_id={tid}", headers=headers)).json()
            busy = (await client.get(f"/api/webapp/client/slot/{taken}?trainer_id={tid}", headers=headers)).json()
            alien = (await client.get(f"/api/webapp/client/slot/{far}?trainer_id={tid + 100000}", headers=headers)).json()
    assert ok["available"] is True
    assert ok["slot"]["id"] == far and ok["slot"]["arena_id"] == place["arena_id"] and ok["slot"]["start_time"] == "12:00"
    assert busy == {"available": False, "slot": None}
    assert alien["available"] is False


@pytest.mark.asyncio
async def test_child_profile_phone_written_only_when_valid(app_use_test_db, db_session) -> None:
    """Телефон в профиль ребёнка — только нормализованный валидный (запись на сеанс студии шлёт как ввели)."""
    from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
    from src.api.routes.webapp import _ensure_client_for_webapp_miniapp

    ctg = _fresh_client_telegram_id()
    with patch_client_init_auth(ctg):
        async with _client() as client:
            created = await client.post(
                "/api/webapp/client/profiles", json={"first_name": "Соня"}, headers={"X-Telegram-Init-Data": "mock"}
            )
    child_id = created.json()["client_id"]
    principal = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=ctg)
    phone, _norm = belarus_test_phone(ctg)

    async def child_phone() -> str | None:
        return (await db_session.execute(text("SELECT phone FROM clients WHERE id = :c"), {"c": child_id})).scalar()

    await _ensure_client_for_webapp_miniapp(db_session, principal, "mock", phone="12-34", requested_profile_id=child_id)
    assert not await child_phone()
    spaced = phone[:4] + " " + phone[4:6] + " " + phone[6:]
    await _ensure_client_for_webapp_miniapp(db_session, principal, "mock", phone=spaced, requested_profile_id=child_id)
    assert await child_phone() == phone


@pytest.mark.asyncio
async def test_client_passes_list_tier_scope(app_use_test_db, db_session) -> None:
    """«Спишем 1» обещаем только при точном покрытии: /client/passes отдаёт тарифы абонемента (пусто — любые)."""
    from src.application.pass_product_use_cases import list_client_pass_instances

    async with _client() as client:
        place = await _place(db_session)
        tid = await _trainer_on(db_session, client, place, first_name=f"Оля{uuid.uuid4().hex[:4]}")
    cid = (await db_session.execute(text("INSERT INTO clients (first_name) VALUES ('Аня') RETURNING id"))).scalar_one()
    for name, kinds in (("Детский", ["child"]), ("Любой", [])):
        pid = (
            await db_session.execute(
                text("INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents) VALUES (:t, :n, 8, 1000) RETURNING id"),
                {"t": tid, "n": name},
            )
        ).scalar_one()
        for k in kinds:
            await db_session.execute(
                text("INSERT INTO trainer_pass_product_tiers (pass_product_id, tier_kind) VALUES (:p, :k)"), {"p": pid, "k": k}
            )
        await db_session.execute(
            text(
                "INSERT INTO pass_instances (client_id, pass_product_id, sessions_remaining, sessions_total, price_cents, status) "
                "VALUES (:c, :p, 4, 8, 1000, 'active')"
            ),
            {"c": cid, "p": pid},
        )
    items = {i["product_name"]: i["tier_kinds"] for i in await list_client_pass_instances(db_session, cid)}
    assert items == {"Детский": ["child"], "Любой": []}
