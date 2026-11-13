"""TASK-400: каток для плашки единой карточки в выдаче витрины — только при включённом флаге."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.miniapp_trainer_showcase import primary_rink_name
from tests.api.test_public_place_page import _place
from tests.api.test_site_trainers import _trainer_on

ICE = {3: {"name": 'Ледовая "Замок"'}, 7: {"name": "Чижовка"}}


def test_primary_arena_wins_when_it_is_one_of_trainer_arenas() -> None:
    assert primary_rink_name(7, [3, 7], ICE) == "Чижовка"


def test_missing_or_foreign_primary_falls_back_to_smallest_arena_id() -> None:
    # То же правило, что reconcile_primary_arena: нет основного или он не среди площадок — MIN(arena_id).
    assert primary_rink_name(None, [7, 3], ICE) == "Ледовая «Замок»"
    assert primary_rink_name(99, [7, 3], ICE) == "Ледовая «Замок»"


def test_primary_that_is_not_ice_gives_no_rink() -> None:
    # Основной — зал (нет в ледовых площадках): «основного катка» нет, другим катком не подменяем.
    assert primary_rink_name(5, [3, 5], ICE) is None


def test_no_arenas_no_rink() -> None:
    assert primary_rink_name(3, [], ICE) is None


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _showcase_item(
    db_session, monkeypatch, *, flag: bool, arena_name: str, clear_city: bool = False
) -> tuple[dict, str]:
    if flag:
        monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
    else:
        monkeypatch.delenv("UNIFIED_TRAINER_CARD_ENABLED", raising=False)
    async with _client() as client:
        place = await _place(db_session, name=arena_name)
        tid = await _trainer_on(db_session, client, place, first_name=f"Кат{uuid.uuid4().hex[:4]}")
        await db_session.execute(
            text("UPDATE trainers SET primary_arena_id = NULL WHERE id = :t"), {"t": tid}
        )
        if clear_city:
            await db_session.execute(
                text("UPDATE trainer_profiles SET city_id = NULL WHERE trainer_id = :t"), {"t": tid}
            )
        await db_session.commit()
        body = (await client.get(f"/api/public/trainer-showcase?city_id={place['city_id']}")).json()
    return next(t for t in body["items"] if t["id"] == tid), place["city_name"]


@pytest.mark.asyncio
async def test_flag_off_showcase_has_no_new_field(app_use_test_db, db_session, monkeypatch) -> None:
    item, _city = await _showcase_item(db_session, monkeypatch, flag=False, arena_name='"Замок"')
    assert "primary_arena_name" not in item
    assert "city_name" not in item


@pytest.mark.asyncio
async def test_flag_on_showcase_names_primary_rink_publicly(app_use_test_db, db_session, monkeypatch) -> None:
    item, city = await _showcase_item(db_session, monkeypatch, flag=True, arena_name='"Замок"')
    # Основного в БД нет — единственная площадка тренера; имя в публичном виде (ёлочки).
    assert item["primary_arena_name"] == "«Замок»"
    # Город профиля, как в /client/share-trainer. В БД не пишем.
    assert item["city_name"] == city


@pytest.mark.asyncio
async def test_flag_on_without_profile_city_leaves_city_empty(app_use_test_db, db_session, monkeypatch) -> None:
    item, _city = await _showcase_item(
        db_session, monkeypatch, flag=True, arena_name="Чижовка", clear_city=True
    )
    assert item["city_name"] is None
