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
from src.application.trainer_min_price import trainer_min_session_price
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


def test_min_session_price_is_cheapest_tariff_not_group_or_pass() -> None:
    # TASK-352: Влад (#11) — тарифы 45/50, групповая цена 25; «от» = 45, не 25.
    services = [
        {
            "service_name": "Обучение катанию «с нуля»",
            "price_cents": 5000,
            "currency_code": "BYN",
            "group_price_cents": 2500,
            "price_tiers": [{"tier_kind": "child", "price_cents": 4500}, {"tier_kind": "adult", "price_cents": 5000}],
        }
    ]
    assert trainer_min_session_price({"services": services}) == (4500, "BYN")
    # Нет тарифов — цена услуги.
    assert trainer_min_session_price({"services": [{**services[0], "price_tiers": []}]}) == (5000, "BYN")
    assert trainer_min_session_price({"services": [{"service_name": "ОФП", "price_cents": None}]}) is None
    assert trainer_min_session_price({"services": [{"price_cents": 150000, "currency_code": "RUB"}]}) == (150000, "RUB")


def test_trainer_line_shows_cheapest_session() -> None:
    trainer = {
        "services": [{"service_name": "Обучение катанию «с нуля»", "price_cents": 5500}],
        "min_session_price_cents": 5000,
        "min_session_price_currency": "BYN",
    }
    assert trainer_line(trainer) == "Обучение катанию «с нуля» · от\u00a050\u00a0BYN за\u00a0занятие"
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
    # TASK-352: «от» — минимум тарифов (45/50), а не групповая цена и не абонемент (41,87 за занятие).
    await db_session.execute(
        text("UPDATE trainer_services SET group_price_cents = 2500 WHERE trainer_id = :t"), {"t": tid}
    )
    await db_session.execute(text("DELETE FROM trainer_service_price_variants WHERE trainer_id = :t"), {"t": tid})
    await db_session.execute(
        text(
            "INSERT INTO trainer_service_price_variants (trainer_id, service_id, label, price_cents, sort_order, tier_kind) "
            "SELECT :t, service_id, 'Детский', 4500, 0, 'child' FROM trainer_services WHERE trainer_id = :t "
            "UNION ALL SELECT :t, service_id, 'Взрослый', 5000, 1, 'adult' FROM trainer_services WHERE trainer_id = :t"
        ),
        {"t": tid},
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
async def test_place_page_trainers_are_one_learn_block_not_a_list(app_use_test_db, db_session) -> None:
    """TASK-354: список тренеров на катке заменён единым блоком «Учиться с тренером» → каталог."""
    place = await _place(db_session)
    name = f"Анна{uuid.uuid4().hex[:4]}"
    async with _client() as client:
        tid = await _trainer_on(db_session, client, place, first_name=name)
        html = (await client.get(place["path"])).text

    block = re.search(r'<section class="b-sec b-learn-sec" id="learn">(.*?)</section>', html, re.S)
    assert block, "нет блока «Учиться с тренером»"
    assert f"trainers/{tid}/a_list.jpg" in block.group(1)  # лицо тренера
    assert f'href="/c/{city_slug(place["city_name"])}/trenery?arena={place["arena_id"]}"' in block.group(1)
    assert f"{name} Тренерова" not in html and "b-row--coach" not in html
    assert "startapp=trainer_" not in html
    # Список заменял счётчик «Здесь работает 1 тренер» в «На месте» — блок тоже.
    assert "Здесь работает" not in html


@pytest.mark.asyncio
async def test_place_page_without_trainers_invites_the_first_one(app_use_test_db, db_session) -> None:
    """Тренеров нет — блока «Тренеры» нет; «Станьте первым» — строкой в «Ещё на катке». Не у катка — нигде."""
    place = await _place(db_session)
    shop = await _place(db_session, venue_type="shop")
    async with _client() as client:
        html = (await client.get(place["path"])).text
        shop_html = (await client.get(shop["path"])).text
    assert 'id="trainers"' not in html
    section = re.search(r'<section class="b-sec b-sec--place" id="more">(.*?)</section>', html, re.S)
    assert section, "нет блока «Ещё на катке»"
    assert "Станьте первым тренером на странице этого катка" in section.group(1)
    rink_landing = "/trainers" + place["path"][len("/p"):]
    assert f'class="b-coach tg-out" href="{rink_landing}" data-coach-open' in section.group(1)
    assert "startapp=trainer_" not in section.group(1)
    assert 'id="trainers"' not in shop_html and "data-coach-open" not in shop_html


@pytest.mark.asyncio
async def test_city_page_has_no_trainer_list_only_learn_block_and_coach_entry(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    # Второй каток — вариант «много катков», где есть «Чем займёмся?».
    await _insert_arena(db_session, place["city_id"], name=f"Второй каток {uuid.uuid4().hex[:4]}")
    await db_session.commit()
    name = f"Борис{uuid.uuid4().hex[:4]}"
    async with _client() as client:
        await _trainer_on(db_session, client, place, first_name=name)
        html = (await client.get(f"/c/{city_slug(place['city_name'])}")).text

    # TASK-354: нижний список «Тренеры» и строка «Тренеры · N» ушли; вход для тренеров города остался.
    assert 'id="trainers"' not in html and 'href="#trainers"' not in html and f"{name} Тренерова" not in html
    assert 'id="learn"' in html
    assert "/trainers?utm_source=glide&amp;utm_medium=city_hub" in html


@pytest.mark.asyncio
async def test_arena_trainers_api_carries_the_same_price(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    async with _client() as client:
        tid = await _trainer_on(db_session, client, place, first_name=f"Гена{uuid.uuid4().hex[:4]}")
        data = (await client.get(f"/api/public/arenas/{place['arena_id']}/trainers")).json()
    item = next(t for t in data["items"] if t["id"] == tid)
    assert item["min_session_price_cents"] == 4500
    assert item["min_session_price_currency"] == "BYN"
