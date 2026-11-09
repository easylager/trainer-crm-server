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
from src.application.trainer_min_price import load_pass_offers, trainer_min_session_price
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


def test_min_session_price_takes_tariffs_group_and_pass() -> None:
    # Решение владельца 2026-11-07: «от» — и групповая, и абонемент на занятие (правило TASK-265).
    vlad = {
        "service_id": 1,
        "service_name": "Обучение катанию «с нуля»",
        "price_cents": 5000,
        "currency_code": "BYN",
        "group_price_cents": 2500,
        "price_tiers": [{"tier_kind": "child", "price_cents": 4500}, {"tier_kind": "adult", "price_cents": 5000}],
    }
    # Влад (#11): тарифы 45/50, групповая 25 → «от 25».
    assert trainer_min_session_price({"services": [vlad]}) == (2500, "BYN")
    no_group = {**vlad, "group_price_cents": None}
    # TASK-352: есть тарифы — берём их; цена услуги поверх тарифов не минимум.
    assert trainer_min_session_price({"services": [{**no_group, "price_cents": 3000}]}) == (4500, "BYN")
    assert trainer_min_session_price({"services": [{**no_group, "price_tiers": []}]}) == (5000, "BYN")
    # Гаевский: тарифы 50/55, абонемент 670/16 = 41,87 на все услуги → «от 41,87».
    gaev = {**no_group, "price_tiers": [{"tier_kind": "child", "price_cents": 5000}, {"tier_kind": "adult", "price_cents": 5500}]}
    every = {"per_session_cents": 4187, "service_ids": None}
    assert trainer_min_session_price({"services": [gaev], "passes": [every]}) == (4187, "BYN")
    # Абонемент только на другую услугу (Хоккейное, 4) эти услуги не покрывает.
    hockey_only = {"per_session_cents": 4187, "service_ids": (4,)}
    assert trainer_min_session_price({"services": [gaev], "passes": [hockey_only]}) == (5000, "BYN")
    assert trainer_min_session_price({"services": [gaev, {**gaev, "service_id": 4}], "passes": [hockey_only]}) == (4187, "BYN")
    # Нет услуг — абонементу нечего покрывать.
    assert trainer_min_session_price({"services": [], "passes": [every]}) is None
    assert trainer_min_session_price({"services": [{"service_name": "ОФП", "price_cents": None}]}) is None
    assert trainer_min_session_price({"services": [{"price_cents": 150000, "currency_code": "RUB"}]}) == (150000, "RUB")


def test_min_session_offer_says_what_the_minimum_is() -> None:
    from src.application.trainer_min_price import (
        BASIS_GROUP,
        BASIS_PASS,
        BASIS_SINGLE,
        trainer_min_session_offer,
    )

    svc = {"service_id": 1, "currency_code": "BYN", "price_cents": 5000, "group_price_cents": 2500}
    assert trainer_min_session_offer({"services": [svc]}) == (2500, "BYN", BASIS_GROUP)
    every = {"per_session_cents": 4000, "service_ids": None}
    assert trainer_min_session_offer({"services": [{**svc, "group_price_cents": None}], "passes": [every]}) == (
        4000,
        "BYN",
        BASIS_PASS,
    )
    # Равная цена — обычное занятие честнее группового, групповое — абонемента.
    assert trainer_min_session_offer({"services": [{**svc, "group_price_cents": 5000}]}) == (5000, "BYN", BASIS_SINGLE)
    assert trainer_min_session_offer(
        {"services": [{**svc, "price_cents": 6000}], "passes": [{"per_session_cents": 2500, "service_ids": None}]}
    ) == (2500, "BYN", BASIS_GROUP)
    assert trainer_min_session_offer({"services": [], "passes": [every]}) is None


def test_trainer_line_shows_cheapest_session() -> None:
    trainer = {
        "services": [{"service_name": "Обучение катанию «с нуля»", "price_cents": 5500}],
        "min_session_price_cents": 4187,
        "min_session_price_currency": "BYN",
    }
    # Дробная цена абонемента — как есть (решение владельца).
    assert trainer_line(trainer) == "Обучение катанию «с нуля» · от\u00a041,87\u00a0BYN за\u00a0занятие"
    assert trainer_line({"services": [{"service_name": "Фигурное катание"}], "min_session_price_cents": None}) == "Фигурное катание"
    assert trainer_line({}) == ""
    rated = {**trainer, "profile": {"rating_avg": 5, "rating_count": 2}}
    assert trainer_line(rated).endswith("★ 5,0 · 2 оценки")
    assert "★" not in trainer_line({**trainer, "profile": {"rating_avg": 5, "rating_count": 0}})


def test_trainer_initial_skips_emoji() -> None:
    assert trainer_initial("🪴 Анна") == "А"
    assert trainer_initial("") == "Т"


async def _trainer_on(
    db_session,
    client: AsyncClient,
    place: dict,
    *,
    first_name: str,
    group_price_cents: int | None = 2500,
    tariffs: tuple[int, int] = (4500, 5000),
) -> int:
    """Тренер на катке: тарифы ``tariffs`` (детский, взрослый), групповая, абонемент 670/16 (41,87)."""
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
        text("UPDATE trainer_services SET group_price_cents = CAST(:g AS INTEGER) WHERE trainer_id = :t"),
        {"t": tid, "g": group_price_cents},
    )
    await db_session.execute(text("DELETE FROM trainer_service_price_variants WHERE trainer_id = :t"), {"t": tid})
    await db_session.execute(
        text(
            "INSERT INTO trainer_service_price_variants (trainer_id, service_id, label, price_cents, sort_order, tier_kind) "
            "SELECT :t, service_id, 'Детский', CAST(:c AS INTEGER), 0, 'child' FROM trainer_services WHERE trainer_id = :t "
            "UNION ALL SELECT :t, service_id, 'Взрослый', CAST(:a AS INTEGER), 1, 'adult' FROM trainer_services WHERE trainer_id = :t"
        ),
        {"t": tid, "c": tariffs[0], "a": tariffs[1]},
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
async def test_place_page_lists_trainers_with_site_links(app_use_test_db, db_session) -> None:
    """На катке — прямые ссылки ``/t/…`` и каталог тренеров; без learn-блока при наличии тренеров."""
    place = await _place(db_session)
    name = f"Анна{uuid.uuid4().hex[:4]}"
    async with _client() as client:
        tid = await _trainer_on(db_session, client, place, first_name=name)
        html = (await client.get(place["path"])).text

    trainers = re.search(r'<section class="b-sec b-sec--place" id="trainers">(.*?)</section>', html, re.S)
    assert trainers, "нет раздела «Тренеры»"
    block = trainers.group(1)
    assert f"{name} Тренерова" in block
    assert f"trainers/{tid}/a_list.jpg" in block
    from src.application.site_trainer_page import trainer_path

    assert f'href="{trainer_path(tid, f"{name} Тренерова")}?via=p{place["arena_id"]}"' in block
    assert f'href="/c/{city_slug(place["city_name"])}/trenery?arena={place["arena_id"]}"' in block
    assert 'id="learn"' not in html
    assert "startapp=trainer_" not in html
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
        # Влад: тарифы 45/50, групповая 25 → «от 25».
        vlad = await _trainer_on(db_session, client, place, first_name=f"Влад{uuid.uuid4().hex[:4]}")
        # Гаевский: тарифы 50/55, без групповой, абонемент 670/16 → 41,87 (вниз); неактивный (2,50) не считается.
        gaev = await _trainer_on(
            db_session, client, place, first_name=f"Саша{uuid.uuid4().hex[:4]}", group_price_cents=None, tariffs=(5000, 5500)
        )
        data = (await client.get(f"/api/public/arenas/{place['arena_id']}/trainers")).json()
    by_id = {t["id"]: t for t in data["items"]}
    assert by_id[vlad]["min_session_price_cents"] == 2500
    assert by_id[gaev]["min_session_price_cents"] == 4187
    assert by_id[gaev]["min_session_price_currency"] == "BYN"


@pytest.mark.asyncio
async def test_pass_offers_floor_scope_and_skip_inactive(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    async with _client() as client:
        tid = await _trainer_on(db_session, client, place, first_name=f"Вера{uuid.uuid4().hex[:4]}")
    sid = await require_seed_service_id(db_session)
    await db_session.execute(
        text(
            "WITH p AS (INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active) "
            "VALUES (:t, 'Узкий', 3, 10000, true) RETURNING id) "
            "INSERT INTO trainer_pass_product_services (pass_product_id, service_id) SELECT id, :s FROM p"
        ),
        {"t": tid, "s": sid},
    )
    await db_session.commit()
    assert await load_pass_offers(db_session, [tid]) == {
        tid: [{"per_session_cents": 4187, "service_ids": None}, {"per_session_cents": 3333, "service_ids": (sid,)}]
    }
    assert await load_pass_offers(db_session, []) == {}
