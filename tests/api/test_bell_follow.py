"""Колокольчик сайта: follow_arena_<id> -> подписка при открытии мини-аппа + события охвата."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth import MiniAppPlatform
from src.api.miniapp_auth.principal_keys import VK_CLIENT_SESSION_TELEGRAM_SURROGATE_BASE
from src.application.place_links import (
    follow_start_param,
    is_valid_start_param,
    parse_follow_start_param,
    parse_place_deep_link,
    place_start_param,
    public_telegram_cta_url,
)
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.api.test_webapp_client_miniapp_integration import _client_auth_headers, patch_client_init_auth

EVENT_TYPES = (
    "bell_follow_subscribed",
    "write_access_granted",
    "write_access_denied",
    "write_access_already",
    "write_access_unsupported",
)


def _tid() -> int:
    return 7_900_000_000 + (uuid.uuid4().int % 1_000_000_000)


# --- ссылка и разбор (без БД) ---------------------------------------------------------


def test_follow_param_builds_and_parses() -> None:
    assert follow_start_param(42) == "follow_arena_42"
    assert is_valid_start_param("follow_arena_42")
    assert parse_follow_start_param("follow_arena_42") == 42
    assert parse_follow_start_param(" follow_arena_42 ") == 42


@pytest.mark.parametrize(
    "value",
    [
        "arena_42",
        "arena_42_s_9",
        "follow_arena_0",
        "follow_arena_",
        "follow_arena_042",
        "follow_arena_4_s_1",
        "watch_42",
        None,
        "",
    ],
)
def test_follow_param_rejects_everything_else(value) -> None:
    assert parse_follow_start_param(value) is None


def test_old_arena_links_are_unchanged_and_not_follow() -> None:
    assert place_start_param(42) == "arena_42"
    assert place_start_param(42, 9001) == "arena_42_s_9001"
    assert parse_place_deep_link("arena_42") == (42, None)
    # новый токен не должен читаться как место: иначе шеринг и бот начнут вести себя иначе
    assert parse_place_deep_link("follow_arena_42") is None


def test_cta_url_carries_follow_param_and_arena_scope() -> None:
    url = public_telegram_cta_url(
        "https://glideclub.by",
        start_param=follow_start_param(7),
        surface="selection_page",
        city_id=3,
        arena_id=7,
    )
    assert url is not None
    assert "startapp=follow_arena_7" in url
    assert "arena_id=7" in url


def test_city_hub_bell_href_uses_follow_param_only_there() -> None:
    from src.application.city_hub_page import _b_phone_block

    view = {"city": {"id": 3, "name": "Минск"}}
    rink = {"id": 7, "name": "Тестовый каток", "phone": "+375291234567"}
    html = _b_phone_block(view, rink, base_url="https://glideclub.by")
    assert 'class="b-follow"' in html
    assert "startapp=follow_arena_7" in html
    assert "startapp=arena_7" not in html


# --- подписка при открытии ------------------------------------------------------------


async def _events(db_session, event_type: str) -> list[dict]:
    r = await db_session.execute(
        text("SELECT actor_id, client_id, payload FROM platform_audit_events WHERE event_type = :t ORDER BY id"),
        {"t": event_type},
    )
    return [dict(m) for m in r.mappings().all()]


async def _arena(db_session) -> int:
    city_id = await _insert_city(db_session, name=f"Колокольск {uuid.uuid4().hex[:6]}")
    return await _insert_arena(db_session, city_id, name="Юность")


@pytest.mark.asyncio
async def test_bell_follow_subscribes_idempotently_and_keeps_notification_state(app_use_test_db, db_session) -> None:
    arena_id = await _arena(db_session)
    tid = _tid()
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(
                "/api/webapp/client/bell-follow", headers=_client_auth_headers(), json={"arena_id": arena_id}
            )
            assert first.status_code == 200, first.text
            body = first.json()
            assert body["created"] is True
            assert body["arena_name"] == "Юность"
            assert body["watch"]["kind"] == "sessions"

            # человек уже получил уведомление: повторное открытие не должно его «обнулить»
            await db_session.execute(
                text("UPDATE client_ice_watches SET last_notified_at = now() WHERE arena_id = :a"), {"a": arena_id}
            )
            await db_session.commit()

            second = await client.post(
                "/api/webapp/client/bell-follow", headers=_client_auth_headers(), json={"arena_id": arena_id}
            )
            assert second.status_code == 200, second.text
            assert second.json()["created"] is False
            assert second.json()["watch"]["id"] == body["watch"]["id"]

    rows = (
        await db_session.execute(
            text("SELECT watch_kind, active, last_notified_at FROM client_ice_watches WHERE arena_id = :a"),
            {"a": arena_id},
        )
    ).all()
    assert len(rows) == 1
    assert rows[0][0] == "sessions" and rows[0][1] is True
    assert rows[0][2] is not None

    events = await _events(db_session, "bell_follow_subscribed")
    mine = [e for e in events if e["payload"].get("arena_id") == arena_id]
    assert [e["payload"]["created"] for e in mine] == [True, False]
    assert all(e["payload"]["surface"] == "site_bell" for e in mine)
    assert str(tid) not in str(mine)  # telegram id в журнал не попадает


@pytest.mark.asyncio
async def test_bell_follow_unknown_arena_is_404(app_use_test_db, db_session) -> None:
    with patch_client_init_auth(_tid()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/webapp/client/bell-follow", headers=_client_auth_headers(), json={"arena_id": 2_000_000_000}
            )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_bell_follow_rejected_for_max(app_use_test_db, db_session) -> None:
    arena_id = await _arena(db_session)
    vk_uid = 100_000 + (uuid.uuid4().int % 800_000)
    with patch_client_init_auth(vk_uid, platform=MiniAppPlatform.MAX):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/webapp/client/bell-follow",
                headers=_client_auth_headers(MiniAppPlatform.MAX),
                json={"arena_id": arena_id},
            )
            o = await client.post(
                "/api/webapp/client/bell-follow/outcome",
                headers=_client_auth_headers(MiniAppPlatform.MAX),
                json={"arena_id": arena_id, "outcome": "granted"},
            )
    assert r.status_code == 409 and r.json()["detail"] == "channel_unsupported"
    assert o.status_code == 409
    surrogate = -(VK_CLIENT_SESSION_TELEGRAM_SURROGATE_BASE + vk_uid)
    count = await db_session.execute(
        text("SELECT COUNT(*) FROM client_ice_watches WHERE telegram_id = :t"), {"t": surrogate}
    )
    assert count.scalar() == 0


# --- события исхода -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_access_outcomes_are_recorded(app_use_test_db, db_session) -> None:
    arena_id = await _arena(db_session)
    tid = _tid()
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/webapp/client/bell-follow", headers=_client_auth_headers(), json={"arena_id": arena_id}
            )
            for outcome, retry in (("denied", False), ("granted", True), ("already", False), ("unsupported", False)):
                r = await client.post(
                    "/api/webapp/client/bell-follow/outcome",
                    headers=_client_auth_headers(),
                    json={"arena_id": arena_id, "outcome": outcome, "retry": retry},
                )
                assert r.status_code == 200, r.text
            bad = await client.post(
                "/api/webapp/client/bell-follow/outcome",
                headers=_client_auth_headers(),
                json={"arena_id": arena_id, "outcome": "success"},
            )
            assert bad.status_code == 400

    for event_type, retry in (
        ("write_access_denied", False),
        ("write_access_granted", True),
        ("write_access_already", False),
        ("write_access_unsupported", False),
    ):
        rows = [e for e in await _events(db_session, event_type) if e["payload"].get("arena_id") == arena_id]
        assert len(rows) == 1, event_type
        assert rows[0]["payload"]["retry"] is retry
        assert rows[0]["client_id"] is not None


def test_bell_events_hidden_from_admin_timeline() -> None:
    from src.application.platform_audit_use_cases import ADMIN_TIMELINE_EXCLUDED_EVENT_TYPES

    assert set(EVENT_TYPES) <= ADMIN_TIMELINE_EXCLUDED_EVENT_TYPES
