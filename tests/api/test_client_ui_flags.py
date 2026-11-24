"""TASK-366: флаг новой навигации your-season и сигнал вкладки «Записи»."""

from __future__ import annotations

import random

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import text

from src.api.app import app
from src.application.client_ui_flags import has_trainer_history, season_ui_bucket, season_ui_enabled
from src.shared.config import Settings, get_settings
from tests.api.test_webapp_client_miniapp_integration import _client_auth_headers, patch_client_init_auth
from tests.conftest import unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id


def _settings(ids: list[int] | None = None, percent: int = 0) -> Settings:
    return Settings(client_season_ui_telegram_ids=ids, client_season_ui_percent=percent)


@pytest.fixture
def season_env(monkeypatch: pytest.MonkeyPatch):
    def apply(ids: str | None = None, percent: str | None = None) -> None:
        for name, value in (("CLIENT_SEASON_UI_TELEGRAM_IDS", ids), ("CLIENT_SEASON_UI_PERCENT", percent)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def test_ui_flags_env_parsing(season_env) -> None:
    season_env()
    assert get_settings().client_season_ui_telegram_ids is None
    assert get_settings().client_season_ui_percent == 0
    season_env(ids="11, 22,33", percent="10")
    assert get_settings().client_season_ui_telegram_ids == [11, 22, 33]
    assert get_settings().client_season_ui_percent == 10
    season_env(ids="[44,55]")
    assert get_settings().client_season_ui_telegram_ids == [44, 55]
    season_env(ids="")
    assert get_settings().client_season_ui_telegram_ids is None


@pytest.mark.parametrize("percent", ["-1", "101"])
def test_ui_flags_percent_out_of_range_fails_startup(season_env, percent: str) -> None:
    with pytest.raises(ValidationError):
        season_env(percent=percent)
        get_settings()


def test_ui_flags_off_by_default() -> None:
    s = _settings()
    assert not any(season_ui_enabled(k, s) for k in range(-500, 500))


def test_ui_flags_allowlist_wins_at_zero_percent() -> None:
    s = _settings(ids=[777, -1_000_000_000_042])
    assert season_ui_enabled(777, s) is True
    assert season_ui_enabled(-1_000_000_000_042, s) is True
    assert season_ui_enabled(778, s) is False


def test_ui_flags_percent_rollout() -> None:
    assert all(season_ui_enabled(k, _settings(percent=100)) for k in range(-500, 500))
    rng = random.Random(366)
    keys = [rng.randrange(1, 10**10) for _ in range(10_000)]
    s10 = _settings(percent=10)
    share = sum(season_ui_enabled(k, s10) for k in keys) / len(keys)
    assert 0.08 <= share <= 0.12, share
    assert [season_ui_enabled(k, s10) for k in keys[:200]] == [season_ui_enabled(k, s10) for k in keys[:200]]
    assert season_ui_bucket(12345) == season_ui_bucket(12345)


async def _insert_client(db_session, *, telegram_id: int | None) -> int:
    r = await db_session.execute(
        text("INSERT INTO clients (first_name, telegram_id, is_sandbox) VALUES ('Flags', :tid, false) RETURNING id"),
        {"tid": telegram_id},
    )
    return int(r.scalar_one())


async def _insert_trainer(db_session) -> int:
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    return int(r.scalar_one())


async def _insert_booking(db_session, *, client_id: int, status: str) -> None:
    trainer_id = await _insert_trainer(db_session)
    service_id = await require_seed_service_id(db_session)
    slot_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
                VALUES (:tid, DATE '2025-01-15', TIME '09:00', TIME '10:00', 'available') RETURNING id
                """
            ),
            {"tid": trainer_id},
        )
    ).scalar_one()
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status)
            VALUES (:tid, :cid, :sid, :svc, :st)
            """
        ),
        {"tid": trainer_id, "cid": client_id, "sid": slot_id, "svc": service_id, "st": status},
    )


async def _insert_pass(db_session, *, client_id: int) -> None:
    trainer_id = await _insert_trainer(db_session)
    product_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active)
                VALUES (:tid, 'Pack', 8, 8000, true) RETURNING id
                """
            ),
            {"tid": trainer_id},
        )
    ).scalar_one()
    await db_session.execute(
        text(
            """
            INSERT INTO pass_instances (client_id, pass_product_id, sessions_remaining, sessions_total, price_cents, status)
            VALUES (:cid, :pid, 0, 8, 8000, 'expired')
            """
        ),
        {"cid": client_id, "pid": product_id},
    )


@pytest.mark.asyncio
async def test_trainer_history_catalog_only_is_false(db_session) -> None:
    tid = unique_test_telegram_id()
    await _insert_client(db_session, telegram_id=tid)
    assert await has_trainer_history(db_session, tid) is False
    assert await has_trainer_history(db_session, unique_test_telegram_id()) is False


@pytest.mark.asyncio
async def test_trainer_history_any_booking_status_counts(db_session) -> None:
    tid = unique_test_telegram_id()
    client_id = await _insert_client(db_session, telegram_id=tid)
    await _insert_booking(db_session, client_id=client_id, status="cancelled")
    assert await has_trainer_history(db_session, tid) is True


@pytest.mark.asyncio
async def test_trainer_history_pass_on_linked_profile_counts(db_session) -> None:
    tid = unique_test_telegram_id()
    await _insert_client(db_session, telegram_id=tid)
    child_id = await _insert_client(db_session, telegram_id=None)
    await db_session.execute(
        text(
            """
            INSERT INTO client_profile_links (account_telegram_id, profile_client_id, role, is_default)
            VALUES (:tid, :cid, 'guardian', false)
            """
        ),
        {"tid": tid, "cid": child_id},
    )
    assert await has_trainer_history(db_session, tid) is False
    await _insert_pass(db_session, client_id=child_id)
    assert await has_trainer_history(db_session, tid) is True


async def _get_flags(tid: int) -> dict:
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/webapp/client/ui-flags", headers=_client_auth_headers())
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    return r.json()


@pytest.mark.asyncio
async def test_ui_flags_endpoint(app_use_test_db, db_session, season_env) -> None:
    tid = unique_test_telegram_id()
    client_id = await _insert_client(db_session, telegram_id=tid)
    await _insert_booking(db_session, client_id=client_id, status="completed")
    await db_session.commit()

    season_env()
    assert await _get_flags(tid) == {
        "season_ui": False, "bookings_tab": False, "fast_tabs": False, "search_board": False,
        "redesign_s1": False,
        "redesign_s5": False,
    }

    season_env(ids=str(tid))
    assert await _get_flags(tid) == {
        "season_ui": True, "bookings_tab": True, "fast_tabs": False, "search_board": False,
        "redesign_s1": False,
        "redesign_s5": False,
    }

    other = unique_test_telegram_id()
    season_env(ids=f"{tid},{other}")
    assert await _get_flags(other) == {
        "season_ui": True, "bookings_tab": False, "fast_tabs": False, "search_board": False,
        "redesign_s1": False,
        "redesign_s5": False,
    }


@pytest.mark.asyncio
async def test_ui_flags_redesign_s1(app_use_test_db, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    """TASK-445: redesign_s1 — свой список; «Записи» в меню есть у всех, даже без истории."""
    tid = unique_test_telegram_id()
    client_id = await _insert_client(db_session, telegram_id=tid)
    await db_session.commit()
    monkeypatch.delenv("CLIENT_SEASON_UI_TELEGRAM_IDS", raising=False)
    monkeypatch.delenv("CLIENT_SEASON_UI_PERCENT", raising=False)
    monkeypatch.delenv("CLIENT_REDESIGN_S1_PERCENT", raising=False)
    monkeypatch.setenv("CLIENT_REDESIGN_S1_TELEGRAM_IDS", str(tid))
    get_settings.cache_clear()
    try:
        flags = await _get_flags(tid)
        assert flags["redesign_s1"] is True
        # «Записи» у редизайна всегда — вкладка есть и у новичка без единой записи.
        assert flags["bookings_tab"] is True
        assert flags["season_ui"] is False
        other = await _get_flags(unique_test_telegram_id())
        assert other["redesign_s1"] is False
        assert other["bookings_tab"] is False
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ui_flags_redesign_s5(app_use_test_db, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    """TASK-446: redesign_s5 — свой список и своя корзина, независим от redesign_s1."""
    tid = unique_test_telegram_id()
    await _insert_client(db_session, telegram_id=tid)
    await db_session.commit()
    monkeypatch.delenv("CLIENT_SEASON_UI_TELEGRAM_IDS", raising=False)
    monkeypatch.delenv("CLIENT_REDESIGN_S1_TELEGRAM_IDS", raising=False)
    monkeypatch.delenv("CLIENT_REDESIGN_S5_PERCENT", raising=False)
    monkeypatch.setenv("CLIENT_REDESIGN_S5_TELEGRAM_IDS", str(tid))
    get_settings.cache_clear()
    try:
        flags = await _get_flags(tid)
        assert flags["redesign_s5"] is True
        assert flags["redesign_s1"] is False
        assert flags["season_ui"] is False
        assert (await _get_flags(unique_test_telegram_id()))["redesign_s5"] is False
    finally:
        get_settings.cache_clear()

    # Своя корзина: redesign_s5_percent=100 включает именно s5, не трогая s1.
    monkeypatch.delenv("CLIENT_REDESIGN_S5_TELEGRAM_IDS", raising=False)
    monkeypatch.setenv("CLIENT_REDESIGN_S5_PERCENT", "100")
    get_settings.cache_clear()
    try:
        assert (await _get_flags(tid))["redesign_s5"] is True
        assert (await _get_flags(tid))["redesign_s1"] is False
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ui_flags_search_board_by_list(app_use_test_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """TASK-438: search_board по своему списку, без season_ui."""
    tid = unique_test_telegram_id()
    monkeypatch.delenv("CLIENT_SEASON_UI_TELEGRAM_IDS", raising=False)
    monkeypatch.delenv("CLIENT_SEARCH_BOARD_PERCENT", raising=False)
    monkeypatch.setenv("CLIENT_SEARCH_BOARD_TELEGRAM_IDS", str(tid))
    get_settings.cache_clear()
    try:
        assert (await _get_flags(tid))["search_board"] is True
        assert (await _get_flags(unique_test_telegram_id()))["search_board"] is False
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ui_flags_endpoint_requires_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/webapp/client/ui-flags")
    assert r.status_code == 401
