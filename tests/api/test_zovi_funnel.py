"""TASK-237: воронка открытки пишется в catalog_consumer_events, отчёт её читает (trainer_crm_test)."""

from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import text

from src.api.middleware.http_limits import reset_http_limiters_for_tests
from src.application.zovi_funnel import build_funnel_report, format_funnel_report, report_window
from tests.api.test_ice_invites import _at, _client, _headers, _insert_session, _place

_SECRET = "zovi-funnel-actor-secret-0123456789ab"
_DEV_A = "a" * 32
_DEV_B = "b" * 32
_IP_A = "198.51.100.1"
_IP_B = "198.51.100.2"


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@pytest.fixture(autouse=True)
def _secret_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", _SECRET)
    reset_http_limiters_for_tests()
    yield
    reset_http_limiters_for_tests()


def _as(ip: str, device: str | None = None) -> dict[str, str]:
    headers = _headers()
    headers["X-Forwarded-For"] = ip
    headers["User-Agent"] = f"ua-{ip}"
    if device:
        headers["X-Zovi-Device"] = device
    return headers


async def _events(db_session, kind: str | None = None) -> list:
    sql = "SELECT kind, actor_hash, arena_id, payload FROM catalog_consumer_events WHERE kind LIKE 'invite_%'"
    params = {}
    if kind:
        sql += " AND kind = :kind"
        params["kind"] = kind
    sql += " ORDER BY id"
    return (await db_session.execute(text(sql), params)).all()


async def _create(client, session_id: int, ip: str = _IP_A, device: str | None = _DEV_A, **extra):
    body = {"session_id": session_id, "from_name": "Макс", "to_name": "Аня", "device_token": device, **extra}
    resp = await client.post("/api/public/invites", json=body, headers=_as(ip))
    assert resp.status_code == 201, resp.text
    return resp.json()["code"]


async def _setup(db_session) -> int:
    place = await _place(db_session)
    return await _insert_session(db_session, place["arena_id"], starts_at=_at(days=3))


@pytest.mark.asyncio
async def test_full_pass_writes_one_row_per_step(app_use_test_db, db_session) -> None:
    session_id = await _setup(db_session)
    async with _client() as client:
        code = await _create(client, session_id, src="sys", via="arena_card")
        opened = await client.get(f"/api/public/invites/{code}", params={"src": "sys"}, headers=_as(_IP_B, _DEV_B))
        assert opened.status_code == 200
        again = await client.get(f"/api/public/invites/{code}", params={"src": "sys"}, headers=_as(_IP_B, _DEV_B))
        assert again.status_code == 200
        for act in (1, 3, 2):
            beacon = await client.post(
                f"/api/public/invites/{code}/event",
                content=json.dumps({"kind": "invite_no_attempt", "device_token": _DEV_B, "act": act}),
                headers=_as(_IP_B),
            )
            assert beacon.status_code == 204
        answer = {"device_token": _DEV_B, "tries": 3, "resist_ms": 900, "falls": 1, "tricked": True}
        for _ in range(2):
            resp = await client.post(f"/api/public/invites/{code}/answer", json=answer, headers=_as(_IP_B, _DEV_B))
            assert resp.status_code == 200
        sent = await client.post(
            f"/api/public/invites/{code}/event",
            content=json.dumps({"kind": "invite_send_answer", "device_token": _DEV_B}),
            headers=_as(_IP_B),
        )
        assert sent.status_code == 204
        sent_again = await client.post(
            f"/api/public/invites/{code}/event",
            content=json.dumps({"kind": "invite_send_answer", "device_token": _DEV_B}),
            headers=_as(_IP_B),
        )
        assert sent_again.status_code == 204

    rows = await _events(db_session)
    assert [r.kind for r in rows] == [
        "invite_create",
        "invite_open",
        "invite_no_attempt",
        "invite_yes",
        "invite_send_answer",
    ]
    create, opened_row, no_attempt, yes, send = (r.payload for r in rows)
    assert create["code"] == code and create["device"] == _sha(_DEV_A)
    assert create["via"] == "arena_card" and create["src"] == "sys" and create["audience"] == "one"
    assert opened_row["device"] == _sha(_DEV_B) and opened_row["src"] == "sys"
    assert no_attempt["act"] == 3  # номер акта только растёт
    assert yes["tries"] == 3 and yes["tricked"] is True
    assert {p["code"] for p in (create, opened_row, no_attempt, yes, send)} == {code}
    assert {p["device"] for p in (opened_row, no_attempt, yes, send)} == {_sha(_DEV_B)}
    # один и тот же актёр у получателя на всех звеньях, у создателя — другой
    assert len({r.actor_hash for r in rows[1:]}) == 1 and rows[1].actor_hash
    assert rows[0].actor_hash != rows[1].actor_hash
    assert all(r.arena_id for r in rows)


@pytest.mark.asyncio
async def test_other_device_open_is_a_new_row_and_preview_is_not_open(app_use_test_db, db_session) -> None:
    session_id = await _setup(db_session)
    async with _client() as client:
        code = await _create(client, session_id)
        page = await client.get(f"/zovi/{code}", headers=_as(_IP_B))  # превью-бот без JS
        assert page.status_code == 200
        await client.get(f"/api/public/invites/{code}", headers=_as(_IP_B, _DEV_B))
        await client.get(f"/api/public/invites/{code}", headers=_as("198.51.100.3", "c" * 32))
    assert len(await _events(db_session, "invite_open")) == 2


@pytest.mark.asyncio
async def test_two_invites_same_arena_same_day_same_actor_are_two_creates(app_use_test_db, db_session) -> None:
    session_id = await _setup(db_session)
    async with _client() as client:
        first = await _create(client, session_id)
        second = await _create(client, session_id)
    assert first != second
    rows = await _events(db_session, "invite_create")
    assert len(rows) == 2
    assert rows[0].actor_hash == rows[1].actor_hash
    assert rows[0].arena_id == rows[1].arena_id


@pytest.mark.asyncio
async def test_without_secret_events_are_written_and_report_warns(
    app_use_test_db, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CATALOG_ACTOR_HMAC_SECRET")
    monkeypatch.setattr("src.application.catalog_consumer_events._actor_hmac_secret", lambda: None)
    session_id = await _setup(db_session)
    async with _client() as client:
        code = await _create(client, session_id)
        await client.get(f"/api/public/invites/{code}", headers=_as(_IP_B, _DEV_B))
    rows = await _events(db_session)
    assert [r.kind for r in rows] == ["invite_create", "invite_open"]
    assert all(r.actor_hash is None for r in rows)
    report = await build_funnel_report(db_session, days=1)
    assert report.created >= 1 and report.recipients >= 1
    assert report.actor_linking_warning and "недоступна" in report.actor_linking_warning
    since, until = report_window(1)
    printed = "\n".join(format_funnel_report(report, days=1, since=since, until=until))
    assert "ПРЕДУПРЕЖДЕНИЕ" in printed


@pytest.mark.asyncio
async def test_beacon_ignores_unknown_kind_code_and_garbage(app_use_test_db, db_session) -> None:
    session_id = await _setup(db_session)
    async with _client() as client:
        code = await _create(client, session_id)
        for body in (
            {"kind": "invite_yes", "device_token": _DEV_B},  # серверный вид клиенту не доверяем
            {"kind": "invite_open", "device_token": _DEV_B},
            {"kind": "whatever", "device_token": _DEV_B},
            {"kind": "invite_send_answer", "device_token": "short"},
            {"kind": "invite_send_answer"},
        ):
            resp = await client.post(f"/api/public/invites/{code}/event", json=body, headers=_as(_IP_B))
            assert resp.status_code == 204, body
        missing = await client.post(
            "/api/public/invites/zzzzzzzz/event",
            json={"kind": "invite_send_answer", "device_token": _DEV_B},
            headers=_as(_IP_B),
        )
        assert missing.status_code == 204
        for raw in (b"not json", b"[1,2]", b""):
            resp = await client.post(f"/api/public/invites/{code}/event", content=raw, headers=_as(_IP_B))
            assert resp.status_code == 204
    assert [r.kind for r in await _events(db_session)] == ["invite_create"]


@pytest.mark.asyncio
async def test_beacon_rate_limit(app_use_test_db, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("API_RATE_LIMIT_INVITE_EVENT_MAX_REQUESTS", "3")
    monkeypatch.setenv("API_RATE_LIMIT_INVITE_EVENT_WINDOW_SEC", "600")
    reset_http_limiters_for_tests()
    async with _client() as client:
        statuses = []
        for _ in range(5):
            resp = await client.post(
                "/api/public/invites/abcd2345/event",
                json={"kind": "invite_send_answer", "device_token": _DEV_B},
                headers=_as(_IP_B),
            )
            statuses.append(resp.status_code)
    assert statuses == [204, 204, 204, 429, 429]


@pytest.mark.asyncio
async def test_event_write_failure_does_not_break_create(
    app_use_test_db, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_a, **_k):
        raise RuntimeError("events table gone")

    monkeypatch.setattr("src.application.zovi_funnel_events.record_catalog_consumer_event", boom)
    session_id = await _setup(db_session)
    async with _client() as client:
        code = await _create(client, session_id)
        opened = await client.get(f"/api/public/invites/{code}", headers=_as(_IP_B, _DEV_B))
    assert opened.status_code == 200
    assert await _events(db_session) == []
    count = (
        await db_session.execute(text("SELECT COUNT(*) FROM ice_invites WHERE code = :c"), {"c": code})
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_full_pass_shows_up_in_report(app_use_test_db, db_session) -> None:
    session_id = await _setup(db_session)
    async with _client() as client:
        code = await _create(client, session_id, src="sys", via="ice_list")
        await client.get(f"/api/public/invites/{code}", params={"src": "copy"}, headers=_as(_IP_B, _DEV_B))
        await client.post(
            f"/api/public/invites/{code}/event",
            json={"kind": "invite_no_attempt", "device_token": _DEV_B, "act": 2},
            headers=_as(_IP_B),
        )
        await client.post(
            f"/api/public/invites/{code}/answer",
            json={"device_token": _DEV_B, "tries": 2, "resist_ms": 10, "falls": 0, "tricked": False},
            headers=_as(_IP_B, _DEV_B),
        )
        await client.post(
            f"/api/public/invites/{code}/event",
            json={"kind": "invite_send_answer", "device_token": _DEV_B},
            headers=_as(_IP_B),
        )
        # B создаёт своё, по ссылке от A: parent_code, device и actor сходятся
        await _create(client, session_id, ip=_IP_B, device=_DEV_B, parent_code=code, via="arena_card")
    report = await build_funnel_report(db_session, days=1)
    assert (report.created, report.recipients, report.no_attempt, report.yes, report.send_answer, report.converted) == (
        2,
        1,
        1,
        1,
        1,
        1,
    )
    assert report.k == 1.0
    assert report.signals_any == {"actor": 1, "device": 1, "parent": 1}
    assert report.actor_linking_warning is None
    assert {row.key: row.recipients for row in report.slices["src"]} == {"copy": 1}
    assert report.max_act == {2: 1}
