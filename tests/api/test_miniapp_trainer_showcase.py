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
    assert item["telegram_url"] and f"trainer_{tid}" in item["telegram_url"]
    assert "phone" in item
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
async def test_showcase_keeps_a_slot_the_trainer_page_shows_past_seven_days(app_use_test_db, db_session) -> None:
    """Страница /t смотрит на 14 дней. Витрина с запасом в 7 дней этот слот теряла."""
    async with _client() as client:
        place = await _place(db_session)
        tid = await _trainer_on(db_session, client, place, first_name=f"Влад{uuid.uuid4().hex[:4]}")
        await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
        far = await _slot(db_session, tid, days=9, hour=11, arena_id=place["arena_id"])
        await db_session.commit()
        body = (await client.get(f"/api/public/trainer-showcase?city_id={place['city_id']}")).json()

    item = next(t for t in body["items"] if t["id"] == tid)
    assert [w["slot_id"] for w in item["windows"]] == [far]


@pytest.mark.asyncio
async def test_showcase_service_presentation_public_vs_own(app_use_test_db, db_session) -> None:
    """Публичная услуга отдаёт наш крючок/подробности и название; своя — только слова тренера и заметку."""
    async with _client() as client:
        place = await _place(db_session)
        tid = await _trainer_on(db_session, client, place, first_name=f"Оля{uuid.uuid4().hex[:4]}")
        await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
        public_sid = (
            await db_session.execute(text("SELECT service_id FROM trainer_services WHERE trainer_id = :t"), {"t": tid})
        ).scalar_one()
        await db_session.execute(
            text("UPDATE services SET name = 'ОХМ(отработка хоккейного мастерства)', client_summary = :s WHERE id = :i"),
            {"s": "Для тех, кто уже стоит на льду.\n\nОтрабатываем повороты.\n\nИ торможение.", "i": public_sid},
        )
        await db_session.execute(
            text(
                "UPDATE trainer_services SET description = 'Слова тренера', "
                "client_notice = 'В стоимость не входят: прокат коньков.' WHERE trainer_id = :t AND service_id = :i"
            ),
            {"t": tid, "i": public_sid},
        )
        own_sid = (
            await db_session.execute(
                text(
                    "INSERT INTO services (name, is_public, created_by_trainer_id, client_summary) "
                    "VALUES ('Постановка прыжков', false, :t, 'Чужой текст.\n\nНе должен утечь.') RETURNING id"
                ),
                {"t": tid},
            )
        ).scalar_one()
        await db_session.execute(
            text("INSERT INTO trainer_services (trainer_id, service_id, price_cents, description) VALUES (:t, :s, 6000, 'Мои слова')"),
            {"t": tid, "s": own_sid},
        )
        await db_session.commit()
        body = (await client.get(f"/api/public/trainer-showcase?city_id={place['city_id']}")).json()

    item = next(t for t in body["items"] if t["id"] == tid)
    by_id = {s["service_id"]: s for s in item["services"]}
    pub, own = by_id[public_sid], by_id[own_sid]
    assert pub["title"] == "ОХМ — отработка хоккейного мастерства"
    assert pub["summary_hook"] == "Для тех, кто уже стоит на льду."
    assert pub["summary_body"] == "Отрабатываем повороты. И торможение."
    assert pub["description"] == "Слова тренера"
    assert pub["client_notice"] == "В стоимость не входят: прокат коньков."
    assert own["is_public"] is False
    assert own["title"] == "Постановка прыжков"
    assert own["summary_hook"] == "" and own["summary_body"] == ""
    assert own["description"] == "Мои слова" and own["client_notice"] is None


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


@pytest.mark.asyncio
async def test_showcase_windows_only_on_arenas_of_this_city(app_use_test_db, db_session) -> None:
    """Тренер на катках двух городов: окно с катка города B не попадает в витрину города A."""
    async with _client() as client:
        a = await _place(db_session)
        b = await _place(db_session)
        tid = await _trainer_on(db_session, client, a, first_name=f"Два{uuid.uuid4().hex[:4]}")
        await db_session.execute(
            text("INSERT INTO trainer_arenas (trainer_id, arena_id, is_public) VALUES (:t, :a, true) ON CONFLICT DO NOTHING"),
            {"t": tid, "a": b["arena_id"]},
        )
        await db_session.execute(
            text("INSERT INTO trainer_cities (trainer_id, city_id) VALUES (:t, :c) ON CONFLICT DO NOTHING"),
            {"t": tid, "c": b["city_id"]},
        )
        await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
        await _slot(db_session, tid, days=2, hour=13, arena_id=b["arena_id"])
        await db_session.commit()
        in_a = (await client.get(f"/api/public/trainer-showcase?city_id={a['city_id']}")).json()
        in_b = (await client.get(f"/api/public/trainer-showcase?city_id={b['city_id']}")).json()
    assert next(t for t in in_a["items"] if t["id"] == tid)["windows"] == []
    wins_b = next(t for t in in_b["items"] if t["id"] == tid)["windows"]
    assert len(wins_b) == 1 and wins_b[0]["arena_id"] == b["arena_id"]


@pytest.mark.asyncio
async def test_group_price_by_personal_link_matches_booked_price(app_use_test_db, db_session) -> None:
    """PR #236: тренер по личной ссылке (карточка каталога) — групповая цена та же, что запишет сервер.

    Форма записи (``trainerFromCatalogCard`` → ``payHtml``) берёт ``group_price_cents`` карточки;
    сервер пишет в группу ``COALESCE(group_price_cents, price_cents)``. Здесь — что обе стороны равны.
    """
    async with _client() as client:
        place = await _place(db_session)
        tid = await _trainer_on(db_session, client, place, first_name=f"Оля{uuid.uuid4().hex[:4]}")
    await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
    service_id = (
        await db_session.execute(text("SELECT service_id FROM trainer_services WHERE trainer_id = :t"), {"t": tid})
    ).scalar_one()
    slot_id = await _slot(db_session, tid, days=3, hour=12, arena_id=place["arena_id"], capacity=6)
    await db_session.execute(text("UPDATE slots SET service_id = :s WHERE id = :id"), {"s": service_id, "id": slot_id})
    await db_session.commit()
    ctg = _fresh_client_telegram_id()
    phone, _norm = belarus_test_phone(ctg)
    headers = {"X-Telegram-Init-Data": "mock"}
    with patch_client_init_auth(ctg):
        async with _client() as client:
            card = (await client.get(f"/api/webapp/client/catalog-trainer/{tid}", headers=headers)).json()
            showcase = (await client.get(f"/api/public/trainer-showcase?city_id={place['city_id']}")).json()
            book = await client.post(
                "/api/webapp/client/booking",
                json={"slot_id": slot_id, "phone": phone, "service_id": service_id, "first_name": "Анна"},
                headers=headers,
            )
    assert book.status_code == 200, book.text
    booked = (
        await db_session.execute(
            text("SELECT booking_price_cents FROM bookings WHERE id = :b"), {"b": book.json()["booking_id"]}
        )
    ).scalar_one()
    card_svc = next(s for s in card["services"] if s["service_id"] == service_id)
    showcase_svc = next(s for s in next(t for t in showcase["items"] if t["id"] == tid)["services"] if s["service_id"] == service_id)
    assert card_svc["group_price_cents"] == showcase_svc["group_price_cents"] == booked == 2500


async def _group_slot(db_session, tid: int, arena_id: int, *, status: str, hour: int = 12) -> tuple[int, int, int]:
    service_id = (
        await db_session.execute(text("SELECT service_id FROM trainer_services WHERE trainer_id = :t"), {"t": tid})
    ).scalar_one()
    group_id = (
        await db_session.execute(
            text(
                "INSERT INTO training_groups (trainer_id, name, service_id, arena_id, max_members, status) "
                "VALUES (:t, 'Группа', :s, :a, 6, :st) RETURNING id"
            ),
            {"t": tid, "s": service_id, "a": arena_id, "st": status},
        )
    ).scalar_one()
    slot_id = await _slot(db_session, tid, days=4, hour=hour, arena_id=arena_id, capacity=6)
    await db_session.execute(
        text("UPDATE slots SET service_id = :s, training_group_id = :g WHERE id = :id"),
        {"s": service_id, "g": group_id, "id": slot_id},
    )
    return slot_id, service_id, group_id


@pytest.mark.asyncio
async def test_archived_group_slot_not_offered_by_link_nor_bookable(app_use_test_db, db_session) -> None:
    """PR #236: слот архивной группы (в нём уже есть запись — архивация его не отменила) по ссылке не свободен,
    новая запись — «Slot not available»; прежняя запись остаётся как была. Активная группа — как раньше."""
    async with _client() as client:
        place = await _place(db_session)
        tid = await _trainer_on(db_session, client, place, first_name=f"Вера{uuid.uuid4().hex[:4]}")
    await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
    archived_slot, service_id, _g = await _group_slot(db_session, tid, place["arena_id"], status="archived")
    active_slot, _s, _g2 = await _group_slot(db_session, tid, place["arena_id"], status="active", hour=15)
    member = (
        await db_session.execute(
            text("INSERT INTO clients (first_name, telegram_id) VALUES ('Участник', :tg) RETURNING id"),
            {"tg": _fresh_client_telegram_id()},
        )
    ).scalar_one()
    old_booking = (
        await db_session.execute(
            text(
                "INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status) "
                "VALUES (:s, :t, :c, :svc, 'confirmed') RETURNING id"
            ),
            {"s": archived_slot, "t": tid, "c": member, "svc": service_id},
        )
    ).scalar_one()
    await db_session.commit()
    ctg = _fresh_client_telegram_id()
    phone, _norm = belarus_test_phone(ctg)
    headers = {"X-Telegram-Init-Data": "mock"}
    body = {"phone": phone, "service_id": service_id, "first_name": "Анна"}
    with patch_client_init_auth(ctg):
        async with _client() as client:
            by_link = (await client.get(f"/api/webapp/client/slot/{archived_slot}?trainer_id={tid}", headers=headers)).json()
            book = await client.post("/api/webapp/client/booking", json={**body, "slot_id": archived_slot}, headers=headers)
            active_link = (await client.get(f"/api/webapp/client/slot/{active_slot}?trainer_id={tid}", headers=headers)).json()
            active_book = await client.post("/api/webapp/client/booking", json={**body, "slot_id": active_slot}, headers=headers)
    assert by_link == {"available": False, "slot": None}
    assert book.status_code == 400 and book.json()["detail"] == "Slot not available"
    assert active_link["available"] is True and active_link["slot"]["capacity"] == 6
    assert active_book.status_code == 200, active_book.text
    old = (await db_session.execute(text("SELECT status FROM bookings WHERE id = :b"), {"b": old_booking})).scalar_one()
    assert old == "confirmed"
    n = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM bookings WHERE slot_id = :s AND status IN ('pending', 'confirmed')"),
            {"s": archived_slot},
        )
    ).scalar_one()
    assert n == 1


@pytest.mark.asyncio
async def test_slot_link_respects_self_book_window_of_acting_profile(app_use_test_db, db_session) -> None:
    """PR #236: окно самозаписи ребёнка «утро» — вечернее время по ссылке для него недоступно (как в /client/slots);
    у родителя без ограничения то же время свободно."""
    from src.application.client_booking_daypart_use_cases import set_client_booking_daypart

    async with _client() as client:
        place = await _place(db_session)
        tid = await _trainer_on(db_session, client, place, first_name=f"Нина{uuid.uuid4().hex[:4]}")
    await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
    evening = await _slot(db_session, tid, days=4, hour=18, arena_id=place["arena_id"])
    morning = await _slot(db_session, tid, days=4, hour=9, arena_id=place["arena_id"])
    await db_session.commit()
    ctg = _fresh_client_telegram_id()
    await db_session.execute(
        text("INSERT INTO clients (first_name, telegram_id) VALUES ('Мама', :tg)"), {"tg": ctg}
    )
    await db_session.commit()
    headers = {"X-Telegram-Init-Data": "mock"}
    with patch_client_init_auth(ctg):
        async with _client() as client:
            child_id = (
                await client.post("/api/webapp/client/profiles", json={"first_name": "Соня"}, headers=headers)
            ).json()["client_id"]
            await set_client_booking_daypart(db_session, tid, child_id, "morning")
            child = {**headers, "X-Profile-Id": str(child_id)}
            child_evening = (await client.get(f"/api/webapp/client/slot/{evening}?trainer_id={tid}", headers=child)).json()
            child_morning = (await client.get(f"/api/webapp/client/slot/{morning}?trainer_id={tid}", headers=child)).json()
            child_list = (await client.get(f"/api/webapp/client/slots?trainer_id={tid}", headers=child)).json()
            parent_evening = (await client.get(f"/api/webapp/client/slot/{evening}?trainer_id={tid}", headers=headers)).json()
    assert child_evening == {"available": False, "slot": None}
    assert child_morning["available"] is True
    assert evening not in [s["id"] for s in child_list["slots"]]
    assert parent_evening["available"] is True


@pytest.mark.asyncio
async def test_request_without_city_takes_trainers_city(app_use_test_db, db_session) -> None:
    """PR #236: новый родитель по личной ссылке, города в сессии нет — заявка тренеру уходит с городом тренера.
    Без тренера и без города — 422, как и раньше (город обязателен)."""
    async with _client() as client:
        place = await _place(db_session)
        trainer_id = await _trainer_on(db_session, client, place, first_name=f"Даша{uuid.uuid4().hex[:4]}")
    trainer_city = (
        await db_session.execute(text("SELECT city_id FROM trainer_profiles WHERE trainer_id = :t"), {"t": trainer_id})
    ).scalar_one()
    assert trainer_city is not None
    service_id = (
        await db_session.execute(text("SELECT service_id FROM trainer_services WHERE trainer_id = :t"), {"t": trainer_id})
    ).scalar_one()
    await db_session.commit()
    headers = {"X-Telegram-Init-Data": "mock"}
    with patch_client_init_auth(_fresh_client_telegram_id()):
        async with _client() as client:
            ok = await client.post(
                "/api/webapp/client/request",
                json={"service_id": service_id, "trainer_id": trainer_id, "first_name": "Анна"},
                headers=headers,
            )
            no_city_no_trainer = await client.post(
                "/api/webapp/client/request", json={"service_id": service_id, "first_name": "Анна"}, headers=headers
            )
    assert ok.status_code == 200, ok.text
    saved_city = (
        await db_session.execute(
            text("SELECT city_id FROM client_requests WHERE id = :r"), {"r": ok.json()["request_id"]}
        )
    ).scalar_one()
    assert saved_city == trainer_city
    assert no_city_no_trainer.status_code == 422


@pytest.mark.asyncio
async def test_showcase_keeps_window_on_primary_arena_without_trainer_arenas_row(app_use_test_db, db_session) -> None:
    """Основной каток без записи в ``trainer_arenas`` и каток другого города: свой остаётся, чужой скрыт."""
    async with _client() as client:
        a = await _place(db_session)
        b = await _place(db_session)
        tid = await _trainer_on(db_session, client, a, first_name=f"Прим{uuid.uuid4().hex[:4]}")
        await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
        await db_session.execute(text("DELETE FROM trainer_arenas WHERE trainer_id = :t"), {"t": tid})
        await db_session.execute(
            text("UPDATE trainers SET primary_arena_id = :a WHERE id = :t"), {"a": a["arena_id"], "t": tid}
        )
        mine = await _slot(db_session, tid, days=2, hour=12, arena_id=None)  # без катка слота -> основной
        await _slot(db_session, tid, days=2, hour=14, arena_id=b["arena_id"])  # каток другого города
        await db_session.commit()
        body = (await client.get(f"/api/public/trainer-showcase?city_id={a['city_id']}")).json()
    item = next(t for t in body["items"] if t["id"] == tid)
    assert [w["slot_id"] for w in item["windows"]] == [mine]
