"""TASK-438: вкладка «Поиск» — флаг search_board, подмена /webapp/ice и API ленты сеансов."""

from __future__ import annotations

import uuid
from urllib.parse import quote
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

import src.api.app as app_module
from src.api.app import app
from src.application.client_ui_flags import search_board_enabled
from src.application.ice_board import get_ice_board
from src.application.ice_session_use_cases import create_ice_session
from src.shared.config import Settings, get_settings
from tests.api.test_client_fast_tabs_shell import _init_data
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.api.test_webapp_client_miniapp_integration import _client_auth_headers, patch_client_init_auth
from tests.conftest import unique_test_telegram_id

_UID = 7_438_000_001
_MINSK = ZoneInfo("Europe/Minsk")


@pytest.fixture
def board_env(monkeypatch: pytest.MonkeyPatch):
    def apply(ids: str | None) -> None:
        if ids is None:
            monkeypatch.delenv("CLIENT_SEARCH_BOARD_TELEGRAM_IDS", raising=False)
        else:
            monkeypatch.setenv("CLIENT_SEARCH_BOARD_TELEGRAM_IDS", ids)
        monkeypatch.delenv("CLIENT_SEARCH_BOARD_PERCENT", raising=False)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def test_search_board_flag_is_independent_of_season_ui() -> None:
    s = Settings(client_search_board_telegram_ids=[5])
    assert search_board_enabled(5, s) is True
    assert search_board_enabled(6, s) is False
    assert not any(search_board_enabled(k, Settings(client_season_ui_percent=100)) for k in range(-200, 200))
    assert all(search_board_enabled(k, Settings(client_search_board_percent=100)) for k in range(-200, 200))


def _ice(query: str = "") -> str:
    with TestClient(app) as client:
        r = client.get("/webapp/ice" + query)
    assert r.status_code == 200
    return r.text


@pytest.fixture
def board_file(tmp_path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "ice-board.html"
    path.write_text("<html><head></head><body>ICE-BOARD-MARK __FONT_V__</body></html>", encoding="utf-8")
    monkeypatch.setattr(app_module, "_ICE_BOARD_PATH", path)
    return path


def test_ice_page_without_flag_is_the_old_page(board_env, board_file) -> None:
    board_env(None)
    init = "?init_data=" + quote(_init_data(_UID), safe="")
    plain = _ice()
    assert "ICE-BOARD-MARK" not in plain
    assert _ice(init) == plain


def test_ice_page_with_flag_serves_board_unless_deep_link(board_env, board_file) -> None:
    board_env(str(_UID))
    init = "init_data=" + quote(_init_data(_UID), safe="")
    plain = _ice()
    board = _ice(f"?{init}&city_id=1")
    assert "ICE-BOARD-MARK" in board and "__FONT_V__" not in board
    for deep in ("venue=shop", "intent=skate", "arena=5", "season=winter"):
        assert _ice(f"?{init}&{deep}") == _ice(f"?{deep}"), deep
        assert "ICE-BOARD-MARK" not in _ice(f"?{init}&{deep}"), deep
    assert "ICE-BOARD-MARK" not in plain


def test_ice_page_with_flag_falls_back_when_board_file_missing(board_env, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_ICE_BOARD_PATH", tmp_path / "missing.html")
    board_env(str(_UID))
    assert _ice("?init_data=" + quote(_init_data(_UID), safe="")) == _ice()


async def _session(db_session, arena_id: int, when: datetime, kind: str, **prices) -> int:
    local = when.astimezone(_MINSK)
    created = await create_ice_session(
        db_session,
        arena_id,
        local_date=local.date(),
        starts_at_local=local.strftime("%H:%M"),
        duration_minutes=60,
        kind=kind,
        **prices,
    )
    await db_session.flush()
    return int(created["id"])


@pytest.mark.asyncio
async def test_ice_board_groups_and_counts_future_sessions(app_use_test_db, db_session) -> None:
    now = datetime.now(_MINSK)
    tomorrow = (now + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    cid = await _insert_city(db_session, name=f"Поиск{uuid.uuid4().hex[:6]}")
    arena = await _insert_arena(db_session, cid, name="Каток Б")
    other = await _insert_arena(db_session, cid, name="Каток А")
    past = await _session(db_session, arena, now - timedelta(hours=2), "public_skate")
    ids = {
        "skate": await _session(db_session, arena, tomorrow, "public_skate", price_adult_minor=1200, price_rental_minor=1000),
        "family": await _session(db_session, other, tomorrow, "family_skate"),
        "hockey": await _session(db_session, arena, tomorrow + timedelta(hours=2), "hockey_practice"),
        "figure": await _session(db_session, arena, tomorrow + timedelta(hours=4), "figure_free"),
    }

    board = await get_ice_board(db_session, city_id=cid, day_from=now.date() - timedelta(days=1), days=3)
    got = {s["session_id"]: s for s in board["sessions"]}
    assert past not in got
    assert set(ids.values()) <= set(got)
    assert got[ids["skate"]]["group"] == "skate" and got[ids["family"]]["group"] == "skate"
    assert got[ids["hockey"]]["group"] == "hockey" and got[ids["figure"]]["group"] == "figure"
    assert got[ids["skate"]]["price_adult"] == "12 BYN" and got[ids["skate"]]["price_rental"] == "10 BYN"
    assert got[ids["family"]]["price_adult"] == "" and got[ids["family"]]["thumb"] is None
    # Сортировка: дата, начало, арена — «Каток А» раньше «Каток Б» в 12:00.
    order = [s["session_id"] for s in board["sessions"]]
    assert order.index(ids["family"]) < order.index(ids["skate"]) < order.index(ids["hockey"])
    by_day = {d["date"]: d for d in board["days"]}
    assert len(board["days"]) == 3
    assert by_day[tomorrow.date().isoformat()] == {
        "date": tomorrow.date().isoformat(), "skate": 2, "hockey": 1, "figure": 1,
    }
    assert board["city"]["timezone"] == "Europe/Minsk"
    assert board["today"] == now.date().isoformat()
    assert board["matches"] == []


@pytest.mark.asyncio
async def test_ice_board_api_flag_gate(app_use_test_db, db_session, board_env) -> None:
    tid = unique_test_telegram_id()
    cid = await _insert_city(db_session, name=f"Поиск{uuid.uuid4().hex[:6]}")
    await db_session.commit()
    url = f"/api/webapp/client/ice-board?city_id={cid}&days=2"
    board_env(None)
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            off = await client.get(url, headers=_client_auth_headers())
            board_env(str(tid))
            on = await client.get(url, headers=_client_auth_headers())
            bad = await client.get(url.replace("days=2", "days=8"), headers=_client_auth_headers())
    assert off.status_code == 403 and off.json() == {"detail": "search_board_off"}
    assert on.status_code == 200, on.text
    assert on.headers["cache-control"] == "no-store"
    body = on.json()
    assert set(body) == {"city", "today", "now_local", "days", "sessions", "matches"}
    assert len(body["days"]) == 2 and body["sessions"] == []
    assert bad.status_code == 422
