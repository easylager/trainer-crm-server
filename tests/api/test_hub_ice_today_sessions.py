"""TASK-148 (AC-4): hub ice_teaser несёт ближайшие сеансы для блока «Сегодня на льду».

Блок дополняет тизер, не заменяя его: вместе с тизером bootstrap отдаёт до 4
ближайших сеансов массового катания (``ice_teaser.sessions``), чтобы фронт не делал
второго запроса. Здесь проверяем контракт поля: порядок по времени, первый сеанс —
тизерный, passthrough цены и валюты.
"""

from __future__ import annotations

import pytest

from src.application.arena_public_use_cases import get_hub_ice_teaser
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_city


@pytest.mark.asyncio
async def test_hub_ice_teaser_carries_upcoming_sessions(app_use_test_db, db_session) -> None:
    """До 4 ближайших сеансов, первый — сам тизер, порядок по времени старта."""
    city_id = await _insert_city(db_session, name="Минск-сеансы")
    soon = await _insert_arena(db_session, city_id, name="Чижовка")
    later = await _insert_arena(db_session, city_id, name="Минск-Арена")
    await _add_future_session(db_session, soon, days_ahead=1, starts_at_local="11:00", price_adult_minor=1200)
    await _add_future_session(db_session, later, days_ahead=1, starts_at_local="18:00", price_adult_minor=800)
    await _add_future_session(db_session, soon, days_ahead=2, starts_at_local="10:00")
    await db_session.flush()

    teaser = await get_hub_ice_teaser(db_session, city_id=city_id)
    assert teaser is not None
    assert teaser["arena_name"] == "Чижовка"
    assert teaser["session_id"] is not None

    sessions = teaser["sessions"]
    assert isinstance(sessions, list)
    assert len(sessions) == 3
    # Первый сеанс списка — тизерный, дальше — по времени старта.
    assert sessions[0]["session_id"] == teaser["session_id"]
    times = [s["starts_at_utc"] for s in sessions]
    assert times == sorted(times)
    # Строки несут то, что нужно блоку: время, место, тип, цену.
    assert sessions[0]["starts_at_local"] == "11:00"
    assert sessions[0]["price_adult_minor"] == 1200
    assert sessions[0]["currency_code"] == "BYN"
    assert sessions[0]["venue_type"] == "ice"
    assert sessions[1]["arena_name"] == "Минск-Арена"
    assert sessions[1]["starts_at_local"] == "18:00"


@pytest.mark.asyncio
async def test_hub_ice_teaser_without_sessions_stays_none(app_use_test_db, db_session) -> None:
    """Нет будущих сеансов — нет ни тизера, ни sessions."""
    city_id = await _insert_city(db_session, name="Город-без-сеансов-148")
    await _insert_arena(db_session, city_id, name="Каток без расписания")
    await db_session.flush()

    teaser = await get_hub_ice_teaser(db_session, city_id=city_id)
    assert teaser is None
