"""Ожидание слотов тренера: упавшая отправка не теряет подписку; исходы разрешения писать по экранам."""

from __future__ import annotations

import logging
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.client_trainer_edge_use_cases import notify_slot_waitlist, subscribe_notify_slots
from tests.api.test_client_trainer_edges_slice5 import _insert_client, _seed_online_trainer
from tests.api.test_webapp_client_miniapp_integration import _client_auth_headers, patch_client_init_auth


def _tid() -> int:
    return 7_900_000_000 + (uuid.uuid4().int % 1_000_000_000)


async def _seed_future_slot(db_session, trainer_id: int) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:t, CURRENT_DATE + 3, '10:00', '11:00', 'available')
            """
        ),
        {"t": trainer_id},
    )
    await db_session.commit()


async def _seed_past_slot(db_session, trainer_id: int) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:t, CURRENT_DATE - 3, '10:00', '11:00', 'available')
            """
        ),
        {"t": trainer_id},
    )
    await db_session.commit()


async def _subscribe(db_session, trainer_id: int, name: str) -> tuple[int, int]:
    tid = _tid()
    client_id = await _insert_client(db_session, telegram_id=tid, first_name=name)
    await subscribe_notify_slots(client_id, tid, trainer_id, db_session)
    return client_id, tid


async def _is_subscribed(db_session, client_id: int, trainer_id: int) -> bool:
    r = await db_session.execute(
        text("SELECT notify_when_slots FROM client_trainer_edges WHERE client_id = :c AND trainer_id = :t"),
        {"c": client_id, "t": trainer_id},
    )
    return bool(r.scalar_one())


@pytest.mark.asyncio
async def test_failed_send_keeps_subscription_and_successful_one_is_cleared(db_session, caplog) -> None:
    trainer_id = await _seed_online_trainer(db_session)
    await _seed_future_slot(db_session, trainer_id)
    ok_client, ok_tid = await _subscribe(db_session, trainer_id, "Ok")
    bad_client, bad_tid = await _subscribe(db_session, trainer_id, "Bad")

    sent: list[int] = []

    async def send_fn(telegram_id, text_, reply_markup=None):
        if telegram_id == bad_tid:
            raise RuntimeError("Forbidden: bot can't initiate conversation with a user")
        sent.append(telegram_id)

    with caplog.at_level(logging.WARNING):
        notified = await notify_slot_waitlist(trainer_id, "Анна", db_session, send_fn)

    assert notified == 1
    assert sent == [ok_tid]
    assert await _is_subscribed(db_session, ok_client, trainer_id) is False
    assert await _is_subscribed(db_session, bad_client, trainer_id) is True
    warnings = [r for r in caplog.records if "slot waitlist send failed" in r.getMessage()]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "RuntimeError" in msg
    assert str(bad_tid) not in msg and "Forbidden" not in msg


@pytest.mark.asyncio
async def test_all_sent_clears_all(db_session) -> None:
    trainer_id = await _seed_online_trainer(db_session)
    await _seed_future_slot(db_session, trainer_id)
    c1, _ = await _subscribe(db_session, trainer_id, "A")
    c2, _ = await _subscribe(db_session, trainer_id, "B")

    async def send_fn(telegram_id, text_, reply_markup=None):
        return None

    assert await notify_slot_waitlist(trainer_id, "Анна", db_session, send_fn) == 2
    assert await _is_subscribed(db_session, c1, trainer_id) is False
    assert await _is_subscribed(db_session, c2, trainer_id) is False


@pytest.mark.asyncio
async def test_all_failed_keeps_all_and_returns_zero(db_session) -> None:
    trainer_id = await _seed_online_trainer(db_session)
    await _seed_future_slot(db_session, trainer_id)
    c1, _ = await _subscribe(db_session, trainer_id, "A")

    async def send_fn(telegram_id, text_, reply_markup=None):
        raise RuntimeError("down")

    assert await notify_slot_waitlist(trainer_id, "Анна", db_session, send_fn) == 0
    assert await _is_subscribed(db_session, c1, trainer_id) is True


@pytest.mark.asyncio
async def test_retro_slot_rule_unchanged_no_send_and_subscriptions_stay(db_session) -> None:
    trainer_id = await _seed_online_trainer(db_session)
    await _seed_past_slot(db_session, trainer_id)
    c1, _ = await _subscribe(db_session, trainer_id, "A")
    calls: list[int] = []

    async def send_fn(telegram_id, text_, reply_markup=None):
        calls.append(telegram_id)

    assert await notify_slot_waitlist(trainer_id, "Анна", db_session, send_fn) == 0
    assert calls == []
    assert await _is_subscribed(db_session, c1, trainer_id) is True


# --- исходы разрешения по экранам ---------------------------------------------------------


async def _events(db_session, event_type: str) -> list[dict]:
    r = await db_session.execute(
        text("SELECT actor_id, client_id, payload FROM platform_audit_events WHERE event_type = :t ORDER BY id"),
        {"t": event_type},
    )
    return [dict(m) for m in r.mappings().all()]


@pytest.mark.asyncio
async def test_surface_outcomes_are_recorded_with_surface_and_ids(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    trainer_id = await _seed_online_trainer(db_session)
    tid = _tid()
    cases = [
        ("booking", "granted", {}),
        ("slot_wait", "denied", {"trainer_id": trainer_id}),
        ("slot_wait", "already", {"trainer_id": trainer_id}),
        ("arena_watch", "unsupported", {"arena_id": 41}),
    ]
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            links = {}
            for surface, outcome, ids in cases:
                r = await client.post(
                    "/api/webapp/client/write-access/outcome",
                    headers=_client_auth_headers(),
                    json={"surface": surface, "outcome": outcome, **ids},
                )
                assert r.status_code == 200, r.text
                assert r.json()["ok"] is True
                links[(surface, outcome)] = r.json()["bot_link"]
            for bad in (
                {"surface": "nowhere", "outcome": "granted"},
                {"surface": "booking", "outcome": "success"},
            ):
                r = await client.post(
                    "/api/webapp/client/write-access/outcome", headers=_client_auth_headers(), json=bad
                )
                assert r.status_code == 400

    assert links[("arena_watch", "unsupported")] == "https://t.me/glide_test_bot?start=watch_41"
    assert links[("booking", "granted")] == "https://t.me/glide_test_bot"

    for event_type, surface, extra_key in (
        ("write_access_granted", "booking", None),
        ("write_access_denied", "slot_wait", "trainer_id"),
        ("write_access_already", "slot_wait", "trainer_id"),
        ("write_access_unsupported", "arena_watch", "arena_id"),
    ):
        rows = [e for e in await _events(db_session, event_type) if e["payload"].get("surface") == surface]
        assert len(rows) == 1, event_type
        payload = rows[0]["payload"]
        if extra_key:
            assert payload[extra_key] in (trainer_id, 41)
        assert str(tid) not in str(rows[0]["actor_id"]), "только хэш актора"
        assert str(tid) not in str(payload)


@pytest.mark.asyncio
async def test_surface_outcome_rejected_for_non_telegram(app_use_test_db, db_session) -> None:
    from src.api.miniapp_auth import MiniAppPlatform

    with patch_client_init_auth(100_000 + (uuid.uuid4().int % 800_000), platform=MiniAppPlatform.MAX):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/webapp/client/write-access/outcome",
                headers=_client_auth_headers(MiniAppPlatform.MAX),
                json={"surface": "booking", "outcome": "granted"},
            )
    assert r.status_code == 409


def test_surface_events_hidden_from_admin_timeline() -> None:
    from src.application.platform_audit_use_cases import ADMIN_TIMELINE_EXCLUDED_EVENT_TYPES

    assert {
        "write_access_granted",
        "write_access_denied",
        "write_access_already",
        "write_access_unsupported",
    } <= ADMIN_TIMELINE_EXCLUDED_EVENT_TYPES
