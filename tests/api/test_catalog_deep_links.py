"""TASK-146: /start arena_<id> и /start catalog_<city>[_<intent>] — одна кнопка на нужный экран."""

from __future__ import annotations

import uuid

import pytest

from src.application.catalog_deep_links import build_catalog_deep_link_reply, is_catalog_deep_link
from tests.api.test_public_arenas import _insert_arena, _insert_city

BASE = "https://glide.example"


@pytest.mark.asyncio
async def test_place_payload_opens_that_card(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Диплинск {uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, city_id, name="Каток <Север>")
    reply = await build_catalog_deep_link_reply(db_session, f"arena_{arena_id}", webapp_base_url=BASE)
    assert reply is not None
    assert reply["url"] == f"{BASE}/webapp/arena?ref={arena_id}"
    focused = await build_catalog_deep_link_reply(
        db_session, f"arena_{arena_id}_s_77", webapp_base_url=BASE
    )
    assert focused is not None
    assert focused["url"] == f"{BASE}/webapp/arena?ref={arena_id}&s=77"
    assert reply["button_text"] == "Открыть карточку катка"
    assert "&lt;Север&gt;" in reply["text"], "имя экранируется: ответ уходит с parse_mode=HTML"


@pytest.mark.asyncio
async def test_missing_place_is_not_a_dead_end(app_use_test_db, db_session) -> None:
    reply = await build_catalog_deep_link_reply(db_session, "arena_999999999", webapp_base_url=BASE)
    assert reply is not None and reply["url"] == f"{BASE}/webapp/ice"


@pytest.mark.asyncio
async def test_catalog_payload_keeps_city_and_filter(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Каталожск {uuid.uuid4().hex[:6]}")
    shops = await build_catalog_deep_link_reply(db_session, f"catalog_{city_id}_shop", webapp_base_url=BASE)
    coaches = await build_catalog_deep_link_reply(db_session, f"catalog_{city_id}_coach", webapp_base_url=BASE)
    assert shops["url"] == f"{BASE}/webapp/ice?city_id={city_id}&venue=shop"
    assert shops["button_text"] == "Магазины"
    assert coaches["url"] == f"{BASE}/webapp/ice?city_id={city_id}&intent=coach"
    weekend = await build_catalog_deep_link_reply(
        db_session, f"catalog_{city_id}_skate_weekend", webapp_base_url=BASE
    )
    assert weekend["url"] == f"{BASE}/webapp/ice?city_id={city_id}&intent=skate&when=weekend"
    assert weekend["button_text"] == "Покататься"
    unknown_city = await build_catalog_deep_link_reply(db_session, "catalog_999999999", webapp_base_url=BASE)
    assert unknown_city["url"] == f"{BASE}/webapp/ice"


@pytest.mark.asyncio
async def test_foreign_payloads_and_http_base_are_left_alone(app_use_test_db, db_session) -> None:
    assert not is_catalog_deep_link("cert_ABC")
    assert not is_catalog_deep_link("col_studio")
    assert await build_catalog_deep_link_reply(db_session, "cert_ABC", webapp_base_url=BASE) is None
    # Telegram не откроет WebApp по http:// — лучше обычный /start, чем мёртвая кнопка.
    assert await build_catalog_deep_link_reply(db_session, "arena_1", webapp_base_url="http://localhost") is None
