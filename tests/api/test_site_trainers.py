"""TASK-265: тренеры на сайте — на странице катка и в городе, запись в Telegram на карточку тренера."""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import city_slug
from src.application.place_links import parse_trainer_deep_link, trainer_start_param
from src.application.site_trainers import trainer_initial, trainer_line
from src.application.trainer_min_price import load_pass_min_per_session, trainer_min_session_price
from tests.api.test_public_arenas import _insert_arena
from tests.api.test_public_catalog_integration import _create_active_trainer_via_api
from tests.api.test_public_place_page import _place
from tests.db_catalog_helpers import require_seed_service_id


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def test_trainer_start_param_round_trip() -> None:
    assert trainer_start_param(7) == "trainer_7"
    assert trainer_start_param(7, 3) == "trainer_7_a_3"
    assert parse_trainer_deep_link("trainer_7") == (7, None)
    assert parse_trainer_deep_link("trainer_7_a_3") == (7, 3)
    assert parse_trainer_deep_link("trainer_0") is None
    assert parse_trainer_deep_link("arena_7") is None


def test_min_session_price_takes_cheapest_of_pass_tiers_group_and_single() -> None:
    services = [
        {
            "service_name": "Обучение катанию «с нуля»",
            "price_cents": 5500,
            "currency_code": "BYN",
            "group_price_cents": 2500,
            "price_tiers": [{"tier_kind": "child", "price_cents": 4500}, {"tier_kind": "two_adults", "price_cents": 7000}],
        }
    ]
    # Абонемент дешевле всего → он.
    assert trainer_min_session_price({"services": services}, pass_min_cents=2000) == (2000, "BYN")
    # Групповое дешевле абонемента и тарифов → групповое.
    assert trainer_min_session_price({"services": services}, pass_min_cents=3812) == (2500, "BYN")
    services_no_group = [{**services[0], "group_price_cents": None}]
    # Детский тариф дешевле разовой цены.
    assert trainer_min_session_price({"services": services_no_group}, pass_min_cents=None) == (4500, "BYN")
    assert trainer_min_session_price({"services": [{"service_name": "ОФП", "price_cents": None}]}, pass_min_cents=None) is None
    assert trainer_min_session_price({"services": [{"price_cents": 150000, "currency_code": "RUB"}]}, pass_min_cents=None) == (150000, "RUB")


def test_trainer_line_shows_cheapest_session() -> None:
    trainer = {
        "services": [{"service_name": "Обучение катанию «с нуля»", "price_cents": 5500}],
        "min_session_price_cents": 4187,
        "min_session_price_currency": "BYN",
    }
    assert trainer_line(trainer) == "Обучение катанию «с нуля» · от\u00a041,87\u00a0BYN за\u00a0занятие"
    assert trainer_line({"services": [{"service_name": "Фигурное катание"}], "min_session_price_cents": None}) == "Фигурное катание"
    assert trainer_line({}) == ""


def test_trainer_initial_skips_emoji() -> None:
    assert trainer_initial("🪴 Анна") == "А"
    assert trainer_initial("") == "Т"


async def _trainer_on(db_session, client: AsyncClient, place: dict, *, first_name: str) -> int:
    sid = await require_seed_service_id(db_session)
    tid = await _create_active_trainer_via_api(
        client,
        db_session,
        city_id=place["city_id"],
        service_ids=[sid],
        arena_ids=[place["arena_id"]],
        first_name=first_name,
        last_name="Тренерова",
    )
    await db_session.execute(
        text("INSERT INTO trainer_cities (trainer_id, city_id) VALUES (:t, :c) ON CONFLICT DO NOTHING"),
        {"t": tid, "c": place["city_id"]},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_arenas (trainer_id, arena_id, is_public) VALUES (:t, :a, true) "
            "ON CONFLICT (trainer_id, arena_id) DO UPDATE SET is_public = true"
        ),
        {"t": tid, "a": place["arena_id"]},
    )
    await db_session.execute(
        text("UPDATE trainer_services SET price_cents = 5500 WHERE trainer_id = :t"), {"t": tid}
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active) "
            "VALUES (:t, 'Детский 16 занятий', 16, 67000, true), (:t, 'Старый', 4, 1000, false)"
        ),
        {"t": tid},
    )
    await db_session.execute(
        text("INSERT INTO trainer_photos (trainer_id, file_key, file_key_list, sort_order) VALUES (:t, :fk, :fl, 0)"),
        {"t": tid, "fk": f"trainers/{tid}/a.jpg", "fl": f"trainers/{tid}/a_list.jpg"},
    )
    await db_session.commit()
    return tid


@pytest.mark.asyncio
async def test_place_page_lists_trainers_with_telegram_link_to_their_card(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    name = f"Анна{uuid.uuid4().hex[:4]}"
    async with _client() as client:
        tid = await _trainer_on(db_session, client, place, first_name=name)
        html = (await client.get(place["path"])).text

    section = re.search(r'<section class="b-sec b-sec--place" id="trainers">(.*?)</section>', html, re.S)
    assert section, "нет секции тренеров"
    body = section.group(1)
    assert f"{name} Тренерова" in body
    assert f"trainers/{tid}/a_list.jpg" in body
    # 670 BYN / 16 = 41,875 → вниз до 41,87; неактивный абонемент (2,50 за занятие) не считается.
    assert "от\u00a041,87\u00a0BYN за\u00a0занятие" in body
    assert f"startapp=trainer_{tid}_a_{place['arena_id']}" in body
    # Список заменяет счётчик «Здесь работает 1 тренер» в «На месте».
    assert "Здесь работает" not in html


@pytest.mark.asyncio
async def test_place_page_without_trainers_invites_the_first_one(app_use_test_db, db_session) -> None:
    """Тренеров нет — раздел только со строкой «Станьте первым»; не у катка — раздела нет."""
    place = await _place(db_session)
    shop = await _place(db_session, venue_type="shop")
    async with _client() as client:
        html = (await client.get(place["path"])).text
        shop_html = (await client.get(shop["path"])).text
    section = re.search(r'<section class="b-sec b-sec--place" id="trainers">(.*?)</section>', html, re.S)
    assert section, "нет раздела тренеров"
    assert "Станьте первым тренером на странице этого катка" in section.group(1)
    assert 'class="b-coach tg-out" href="/trainers" data-coach-open' in section.group(1)
    assert "startapp=trainer_" not in section.group(1)
    assert 'id="trainers"' not in shop_html


@pytest.mark.asyncio
async def test_city_page_shows_trainers_and_route_row_points_to_them(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    # Второй каток — вариант «много катков», где есть строка «Тренеры» в «Что нужно».
    await _insert_arena(db_session, place["city_id"], name=f"Второй каток {uuid.uuid4().hex[:4]}")
    await db_session.commit()
    name = f"Борис{uuid.uuid4().hex[:4]}"
    async with _client() as client:
        tid = await _trainer_on(db_session, client, place, first_name=name)
        html = (await client.get(f"/c/{city_slug(place['city_name'])}")).text

    section = re.search(r'<section class="b-sec" id="trainers">(.*?)</section>', html, re.S)
    assert section, "нет раздела тренеров в городе"
    assert f"{name} Тренерова" in section.group(1)
    # Из города — карточка тренера без привязки к катку.
    assert f"startapp=trainer_{tid}&" in section.group(1)
    assert 'href="#trainers"' in html


@pytest.mark.asyncio
async def test_pass_min_per_session_floors_and_skips_inactive(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    async with _client() as client:
        tid = await _trainer_on(db_session, client, place, first_name=f"Вера{uuid.uuid4().hex[:4]}")
    assert await load_pass_min_per_session(db_session, [tid]) == {tid: 4187}
    assert await load_pass_min_per_session(db_session, []) == {}


@pytest.mark.asyncio
async def test_arena_trainers_api_carries_the_same_price(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    async with _client() as client:
        tid = await _trainer_on(db_session, client, place, first_name=f"Гена{uuid.uuid4().hex[:4]}")
        data = (await client.get(f"/api/public/arenas/{place['arena_id']}/trainers")).json()
    item = next(t for t in data["items"] if t["id"] == tid)
    assert item["min_session_price_cents"] == 4187
    assert item["min_session_price_currency"] == "BYN"
