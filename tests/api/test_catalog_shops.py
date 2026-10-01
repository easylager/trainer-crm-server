"""TASK-146: ледовый магазин — площадка каталога, но не место работы тренера."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.catalog_use_cases import list_arenas
from tests.api.test_admin_arena_profile import patch_admin_principal
from tests.api.test_public_arenas import _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _admin_create_shop(city_id: int, name: str) -> int:
    with patch_admin_principal():
        async with _client() as client:
            resp = await client.post(
                "/api/webapp/admin/arenas",
                json={
                    "city_id": city_id,
                    "name": name,
                    "address": "ул. Карла Маркса, 15",
                    "latitude": 53.9,
                    "longitude": 27.56,
                    "venue_type": "shop",
                },
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["venue_type"] == "shop"
            arena_id = int(resp.json()["id"])
            patch = await client.patch(
                f"/api/webapp/admin/arenas/{arena_id}",
                json={
                    "phone": "+375291234567",
                    "amenities": {"retail": True, "skate_sharpening": True, "repair": False},
                },
            )
            assert patch.status_code == 200, patch.text
    return arena_id


@pytest.mark.asyncio
async def test_admin_creates_shop_and_sees_its_type(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Магазинск {uuid.uuid4().hex[:6]}")
    await db_session.commit()
    name = f"Коньки и Точка {uuid.uuid4().hex[:6]}"
    shop_id = await _admin_create_shop(city_id, name)

    with patch_admin_principal():
        async with _client() as client:
            listed = await client.get("/api/webapp/admin/arenas", params={"city_id": city_id, "q": name})
    assert listed.status_code == 200, listed.text
    body = listed.json()
    row = next(a for a in body["items"] if a["id"] == shop_id)
    assert row["venue_type"] == "shop"
    assert row["amenities"] == {"retail": True, "skate_sharpening": True, "repair": False}
    assert "shop" in {o["key"] for o in body["venue_types"]}


@pytest.mark.asyncio
async def test_admin_rejects_unknown_venue_type_and_rink_retail(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Опечаткино {uuid.uuid4().hex[:6]}")
    rink_id = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:6]}")
    await db_session.commit()
    with patch_admin_principal():
        async with _client() as client:
            bad_type = await client.post(
                "/api/webapp/admin/arenas",
                json={"city_id": city_id, "name": "X", "venue_type": "store"},
            )
            rink_retail = await client.patch(
                f"/api/webapp/admin/arenas/{rink_id}", json={"amenities": {"retail": True}}
            )
            # Тип и удобства в одном PATCH: удобства сверяются уже с новым типом.
            converted = await client.patch(
                f"/api/webapp/admin/arenas/{rink_id}",
                json={"venue_type": "shop", "amenities": {"retail": True}},
            )
    assert bad_type.status_code == 400
    assert rink_retail.status_code == 400
    assert converted.status_code == 200, converted.text


@pytest.mark.asyncio
async def test_shop_hidden_from_default_list_but_reachable_by_chip(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Ленточный {uuid.uuid4().hex[:6]}")
    rink_id = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:6]}")
    await db_session.commit()
    shop_id = await _admin_create_shop(city_id, f"Магазин {uuid.uuid4().hex[:6]}")

    async with _client() as client:
        default = await client.get("/api/public/ice/arenas", params={"city_id": city_id})
        shops = await client.get("/api/public/ice/arenas", params={"city_id": city_id, "venue_type": "shop"})
    assert default.status_code == 200, default.text
    ids = {item["id"] for item in default.json()["items"]}
    assert rink_id in ids
    assert shop_id not in ids
    facets = {f["key"]: f["count"] for f in default.json()["venue_type_facets"]}
    assert facets.get("shop") == 1, "чип «Магазин» обязан быть виден, иначе до магазина не дойти"

    shop_items = shops.json()["items"]
    assert [i["id"] for i in shop_items] == [shop_id]
    assert shop_items[0]["venue_chip"] == "Магазин"
    assert shop_items[0]["venue_cta"] == "Открыть карточку магазина"


@pytest.mark.asyncio
async def test_search_by_service_word_finds_the_workshop(app_use_test_db, db_session) -> None:
    """«заточка» ищут словом услуги, а не названием мастерской."""
    city_id = await _insert_city(db_session, name=f"Точильск {uuid.uuid4().hex[:6]}")
    await db_session.commit()
    name = f"Лезвие {uuid.uuid4().hex[:6]}"
    shop_id = await _admin_create_shop(city_id, name)

    async with _client() as client:
        found = await client.get("/api/public/search", params={"q": "заточка коньков"})
        not_repair = await client.get("/api/public/search", params={"q": "ремонт"})
    assert found.status_code == 200, found.text
    arena_group = next(g for g in found.json()["groups"] if g["type"] == "arena")
    hit = next((i for i in arena_group["items"] if i["id"] == shop_id), None)
    assert hit is not None
    assert hit["venue_type"] == "shop"
    # repair=False — «известно, что нет»; такая мастерская по «ремонту» не находится.
    repair_group = next(g for g in not_repair.json()["groups"] if g["type"] == "arena")
    assert shop_id not in {i["id"] for i in repair_group["items"]}


@pytest.mark.asyncio
async def test_trainer_pickers_never_offer_a_shop(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Тренерск {uuid.uuid4().hex[:6]}")
    rink_id = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:6]}")
    await db_session.commit()
    shop_id = await _admin_create_shop(city_id, f"Магазин {uuid.uuid4().hex[:6]}")

    public_ids = {a["id"] for a in await list_arenas(db_session, city_id)}
    trainer_ids = {a["id"] for a in await list_arenas(db_session, city_id, include_unconfirmed=True)}
    assert rink_id in public_ids and rink_id in trainer_ids
    assert shop_id not in public_ids
    assert shop_id not in trainer_ids

    row = (await db_session.execute(text("SELECT venue_type FROM arenas WHERE id = :id"), {"id": shop_id})).scalar_one()
    assert row == "shop"
