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


def test_trainer_line_first_service_and_lowest_price() -> None:
    trainer = {
        "services": [
            {"service_name": "Обучение катанию «с нуля»", "price_cents": 5500, "currency_code": "BYN"},
            {"service_name": "ОФП", "price_cents": 4000, "currency_code": "BYN"},
            {"service_name": "Без цены", "price_cents": None},
        ]
    }
    assert trainer_line(trainer) == "Обучение катанию «с нуля» · от 40 BYN"
    assert trainer_line({"services": [{"service_name": "Фигурное катание", "price_cents": None}]}) == "Фигурное катание"
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
    assert "от 55 BYN" in body
    assert f"startapp=trainer_{tid}_a_{place['arena_id']}" in body
    # Список заменяет счётчик «Здесь работает 1 тренер» в «На месте».
    assert "Здесь работает" not in html


@pytest.mark.asyncio
async def test_place_page_without_trainers_has_no_section(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    async with _client() as client:
        html = (await client.get(place["path"])).text
    assert 'id="trainers"' not in html


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
