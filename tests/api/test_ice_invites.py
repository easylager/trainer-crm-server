"""TASK-231: public invite create / read / answer / status on trainer_crm_test."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.middleware.http_limits import reset_http_limiters_for_tests
from src.application.catalog_consumer_events import public_actor_hash, telegram_actor_hash
from tests.shared.test_telegram_webapp import _build_signed_init_data
from src.application.place_links import place_path
from tests.api.test_public_arenas import _insert_arena, _insert_city

_SECRET = "zovi-invite-actor-secret-0123456789ab"
_IP = "203.0.113.44"
_UA = "zovi-invite-test"
_MINSK = ZoneInfo("Europe/Minsk")
_TOKEN_A = "device-token-aaa1"
_TOKEN_B = "device-token-bbb2"


@pytest.fixture(autouse=True)
def _actor_secret_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", _SECRET)
    reset_http_limiters_for_tests()
    yield
    reset_http_limiters_for_tests()


def _headers(**extra: str) -> dict[str, str]:
    return {"X-Forwarded-For": _IP, "User-Agent": _UA, **extra}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _at(*, days: int) -> datetime:
    moment = datetime.now(timezone.utc) + timedelta(days=days)
    return moment.replace(minute=0, second=0, microsecond=0)


async def _place(db_session) -> dict:
    city = f"Зов{uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=city)
    arena = f"Каток {uuid.uuid4().hex[:4]}"
    arena_id = await _insert_arena(db_session, city_id, name=arena, address="ул. Ледовая, 1")
    return {"city_id": city_id, "city": city, "arena_id": arena_id, "arena": arena}


async def _insert_session(
    db_session,
    arena_id: int,
    *,
    starts_at: datetime,
    kind: str = "public_skate",
    status: str = "active",
    price_adult_minor: int = 2500,
    schedule_basis: str = "live",
) -> int:
    ends_at = starts_at + timedelta(minutes=60)
    local_start = starts_at.astimezone(_MINSK)
    local_end = ends_at.astimezone(_MINSK)
    row = await db_session.execute(
        text("""
            INSERT INTO ice_sessions (
                arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                starts_at_local, ends_at_local, price_adult_minor, currency_code,
                status, schedule_basis, source_id
            ) VALUES (
                :arena_id, :kind, :starts_at, :ends_at, :local_date,
                :starts_local, :ends_local, :price, 'BYN',
                :status, :basis, 'admin'
            )
            RETURNING id
            """),
        {
            "arena_id": arena_id,
            "kind": kind,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "local_date": local_start.date(),
            "starts_local": local_start.time().replace(microsecond=0),
            "ends_local": local_end.time().replace(microsecond=0),
            "price": price_adult_minor,
            "status": status,
            "basis": schedule_basis,
        },
    )
    return int(row.scalar_one())


async def _create(client: AsyncClient, session_id: int, **overrides):
    payload = {"session_id": session_id, "from_name": "Макс", "to_name": "Аня", "show_price": False}
    payload.update(overrides)
    return await client.post("/api/public/invites", json=payload, headers=_headers())


async def _invite_count(db_session) -> int:
    return int((await db_session.execute(text("SELECT COUNT(*) FROM ice_invites"))).scalar_one())


@pytest.mark.asyncio
async def test_create_future_session_returns_code_and_status_link(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    starts = _at(days=3)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=starts)
    projected_id = await _insert_session(
        db_session,
        place["arena_id"],
        starts_at=_at(days=4),
        schedule_basis="projected",
    )
    async with _client() as client:
        created = await _create(client, session_id, to_name="  Аня  ")
        assert created.status_code == 201, created.text
        body = created.json()
        code = body["code"]
        assert len(code) == 8
        assert set(code) <= set("23456789abcdefghjkmnpqrstuvwxyz")
        assert body["invite_path"] == f"/zovi/{code}"
        assert body["status_path"] == f"/zovi/{code}/s/{body['status_key']}"

        projected = await _create(client, projected_id, to_name=None)
        assert projected.status_code == 201, projected.text
        assert "projected" not in projected.text

        child = await _create(client, session_id, parent_code=code, to_name=None)
        assert child.status_code == 201, child.text
        stranger = await _create(client, session_id, parent_code="no-such-code")
        assert stranger.status_code == 201, stranger.text

        before_open = await client.get(f"/api/public/invites/{code}/status", params={"key": body["status_key"]})
        assert before_open.status_code == 200
        assert before_open.json()["first_opened_at"] is None
        assert before_open.json()["answer_count"] == 0

        card = await client.get(f"/api/public/invites/{code}")
        assert card.status_code == 200, card.text
        opened = await client.get(f"/api/public/invites/{code}/status", params={"key": body["status_key"]})
        again = await client.get(f"/api/public/invites/{code}")
        assert again.status_code == 200
        reopened = await client.get(f"/api/public/invites/{code}/status", params={"key": body["status_key"]})

    view = card.json()
    assert view["to_name"] == "Аня"
    assert view["from_name"] == "Макс"
    assert view["kind"] == "public_skate"
    assert view["state"] == "ok"
    assert view["next_session"] is None
    assert "my_answer" not in view
    assert body["status_key"] not in json.dumps(view)
    local = starts.astimezone(_MINSK)
    ends = starts + timedelta(minutes=60)
    assert view["session"]["id"] == session_id
    assert datetime.fromisoformat(view["session"]["starts_at_utc"]) == starts
    assert datetime.fromisoformat(view["session"]["ends_at_utc"]) == ends
    assert view["session"]["starts_at_local"] == local.strftime("%H:%M")
    assert view["session"]["ends_at_local"] == ends.astimezone(_MINSK).strftime("%H:%M")
    assert view["session"]["local_date"] == local.date().isoformat()
    assert view["session"]["arena"]["name"] == place["arena"]
    assert view["session"]["arena"]["address"] == "ул. Ледовая, 1"
    assert view["session"]["arena"]["city"] == place["city"]
    slug = (
        await db_session.execute(
            text("SELECT slug FROM arena_profiles WHERE arena_id = :id"),
            {"id": place["arena_id"]},
        )
    ).scalar_one()
    assert view["session"]["arena"]["public_path"] == place_path(city_name=place["city"], slug=str(slug))

    assert opened.json()["first_opened_at"]
    assert reopened.json()["first_opened_at"] == opened.json()["first_opened_at"]

    stored = (
        await db_session.execute(
            text("""
                SELECT status_key_hash, creator_actor_hash
                FROM ice_invites WHERE code = :code
                """),
            {"code": code},
        )
    ).one()
    assert stored.status_key_hash == hashlib.sha256(body["status_key"].encode()).hexdigest()
    assert stored.status_key_hash != body["status_key"]
    assert stored.creator_actor_hash == public_actor_hash(client_ip=_IP, user_agent=_UA)
    columns = {name for (name,) in (await db_session.execute(text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'ice_invites'
                    """))).all()}
    assert "status_key" not in columns
    parent_of_child = (
        await db_session.execute(
            text("SELECT parent_code FROM ice_invites WHERE code = :code"),
            {"code": child.json()["code"]},
        )
    ).scalar_one()
    parent_of_stranger = (
        await db_session.execute(
            text("SELECT parent_code FROM ice_invites WHERE code = :code"),
            {"code": stranger.json()["code"]},
        )
    ).scalar_one()
    assert parent_of_child == code
    assert parent_of_stranger is None
    group = (
        await db_session.execute(
            text("SELECT to_name FROM ice_invites WHERE code = :code"),
            {"code": projected.json()["code"]},
        )
    ).scalar_one()
    assert group is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["open_ice", "hockey_practice"])
async def test_create_accepts_open_ice_and_hockey(app_use_test_db, db_session, kind: str) -> None:
    place = await _place(db_session)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=2), kind=kind)
    async with _client() as client:
        created = await _create(client, session_id)
        assert created.status_code == 201, created.text
        card = await client.get(f"/api/public/invites/{created.json()['code']}")
    assert card.status_code == 200
    assert card.json()["kind"] == kind
    assert card.json()["state"] == "ok"


@pytest.mark.asyncio
async def test_create_rejects_past_hidden_and_missing_session(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    past_id = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=-3))
    hidden = await _place(db_session)
    await db_session.execute(
        text("UPDATE arenas SET is_active = false WHERE id = :id"),
        {"id": hidden["arena_id"]},
    )
    hidden_id = await _insert_session(db_session, hidden["arena_id"], starts_at=_at(days=2))
    missing = int((await db_session.execute(text("SELECT COALESCE(MAX(id), 0) + 1000 FROM ice_sessions"))).scalar_one())
    before = await _invite_count(db_session)
    async with _client() as client:
        past = await _create(client, past_id)
        hidden_resp = await _create(client, hidden_id)
        missing_resp = await _create(client, missing)
    assert past.status_code == 422
    assert "уже прошёл" in past.json()["detail"]
    assert hidden_resp.status_code == 422
    assert "скрыт" in hidden_resp.json()["detail"]
    assert missing_resp.status_code == 422
    assert "не найден" in missing_resp.json()["detail"]
    assert await _invite_count(db_session) == before


@pytest.mark.asyncio
async def test_bad_names_are_422_and_write_nothing(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=2))
    before = await _invite_count(db_session)
    async with _client() as client:
        digits = await _create(client, session_id, from_name="Макс1")
        long_name = await _create(client, session_id, from_name="А" * 21)
        stopped = await _create(client, session_id, to_name="хуй")
    for response, field in ((digits, "from_name"), (long_name, "from_name"), (stopped, "to_name")):
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)
        assert field in response.json()["detail"]
    assert await _invite_count(db_session) == before


@pytest.mark.asyncio
async def test_get_gone_after_delete_offers_next_same_kind(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    original = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=3))
    await _insert_session(db_session, place["arena_id"], starts_at=_at(days=1), kind="hockey_practice")
    nxt = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=5))
    other = await _place(db_session)
    lone = await _insert_session(db_session, other["arena_id"], starts_at=_at(days=2))
    async with _client() as client:
        created = await _create(client, original)
        alone = await _create(client, lone)
        await db_session.execute(text("DELETE FROM ice_sessions WHERE id = :id"), {"id": original})
        await db_session.execute(text("DELETE FROM ice_sessions WHERE id = :id"), {"id": lone})
        gone = await client.get(f"/api/public/invites/{created.json()['code']}")
        empty = await client.get(f"/api/public/invites/{alone.json()['code']}")
    assert gone.status_code == 200, gone.text
    body = gone.json()
    assert body["state"] == "gone"
    assert body["session"]["id"] is None
    assert body["session"]["arena"]["id"] == place["arena_id"]
    assert body["next_session"]["id"] == nxt
    assert body["next_session"]["kind"] == "public_skate"
    assert empty.json()["state"] == "gone"
    assert empty.json()["next_session"] is None


@pytest.mark.asyncio
async def test_get_past_offers_next_session(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    original = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=3))
    nxt = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=6))
    async with _client() as client:
        created = await _create(client, original)
        code = created.json()["code"]
        await db_session.execute(
            text("""
                UPDATE ice_sessions
                SET starts_at_utc = starts_at_utc - interval '5 days',
                    ends_at_utc = ends_at_utc - interval '5 days',
                    local_date = local_date - 5
                WHERE id = :id
                """),
            {"id": original},
        )
        await db_session.execute(
            text("""
                UPDATE ice_invites
                SET starts_at_utc = starts_at_utc - interval '5 days',
                    ends_at_utc = ends_at_utc - interval '5 days'
                WHERE code = :code
                """),
            {"code": code},
        )
        card = await client.get(f"/api/public/invites/{code}")
    assert card.status_code == 200, card.text
    assert card.json()["state"] == "past"
    assert card.json()["next_session"]["id"] == nxt


@pytest.mark.asyncio
async def test_two_devices_two_answers_same_device_keeps_the_first(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=2))
    async with _client() as client:
        created = await _create(client, session_id)
        code = created.json()["code"]
        key = created.json()["status_key"]
        first = await client.post(
            f"/api/public/invites/{code}/answer",
            json={"device_token": _TOKEN_A, "tries": 2, "resist_ms": 1500, "falls": 1, "tricked": False},
            headers=_headers(),
        )
        again = await client.post(
            f"/api/public/invites/{code}/answer",
            json={"device_token": _TOKEN_A, "tries": 9, "resist_ms": 9, "falls": 5, "tricked": True},
            headers=_headers(),
        )
        second = await client.post(
            f"/api/public/invites/{code}/answer",
            json={"device_token": _TOKEN_B, "tries": 4, "resist_ms": 800, "falls": 0, "tricked": True},
            headers=_headers(),
        )
        mine = await client.get(f"/api/public/invites/{code}", headers=_headers(**{"X-Zovi-Device": _TOKEN_A}))
        other = await client.get(f"/api/public/invites/{code}", headers=_headers(**{"X-Zovi-Device": _TOKEN_B}))
        plain = await client.get(f"/api/public/invites/{code}", headers=_headers())
        status = await client.get(f"/api/public/invites/{code}/status", params={"key": key})
    assert first.status_code == 200, first.text
    assert again.status_code == 200, again.text
    assert second.status_code == 200, second.text
    assert first.json()["tries"] == 2
    assert again.json() == first.json()
    assert second.json()["tries"] == 4
    assert mine.json()["my_answer"]["tries"] == 2
    assert mine.json()["my_answer"]["falls"] == 1
    assert other.json()["my_answer"]["tries"] == 4
    assert "my_answer" not in plain.json()
    body = status.json()
    assert body["answer_count"] == 2
    assert {item["tries"] for item in body["answers"]} == {2, 4}
    dumped = json.dumps(body)
    assert _TOKEN_A not in dumped
    assert "responder_key" not in dumped
    assert "status_key" not in dumped
    rows = (
        await db_session.execute(
            text("""
                SELECT a.responder_key, a.tries
                FROM ice_invite_answers a
                JOIN ice_invites i ON i.id = a.invite_id
                WHERE i.code = :code
                """),
            {"code": code},
        )
    ).all()
    assert len(rows) == 2
    keys = {row.responder_key for row in rows}
    assert hashlib.sha256(_TOKEN_A.encode()).hexdigest() in keys
    assert hashlib.sha256(_TOKEN_B.encode()).hexdigest() in keys
    assert all(_TOKEN_A not in row.responder_key and _TOKEN_B not in row.responder_key for row in rows)


@pytest.mark.asyncio
async def test_answer_on_gone_is_409(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=2))
    async with _client() as client:
        created = await _create(client, session_id)
        code = created.json()["code"]
        await db_session.execute(text("DELETE FROM ice_sessions WHERE id = :id"), {"id": session_id})
        refused = await client.post(
            f"/api/public/invites/{code}/answer",
            json={"device_token": _TOKEN_A, "tries": 1, "resist_ms": 10, "falls": 0, "tricked": False},
            headers=_headers(),
        )
    assert refused.status_code == 409
    count = int(
        (
            await db_session.execute(
                text("""
                    SELECT COUNT(*)
                    FROM ice_invite_answers a
                    JOIN ice_invites i ON i.id = a.invite_id
                    WHERE i.code = :code
                    """),
                {"code": code},
            )
        ).scalar_one()
    )
    assert count == 0


@pytest.mark.asyncio
async def test_status_wrong_key_matches_unknown_code(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=2))
    async with _client() as client:
        created = await _create(client, session_id)
        code = created.json()["code"]
        unknown = await client.get("/api/public/invites/abcdefgh/status", params={"key": "nope"})
        wrong = await client.get(f"/api/public/invites/{code}/status", params={"key": "not-the-key"})
        missing_card = await client.get("/api/public/invites/abcdefgh")
    assert unknown.status_code == 404
    assert wrong.status_code == 404
    assert unknown.json() == wrong.json()
    assert unknown.json()["detail"] == "Приглашение не найдено."
    assert missing_card.status_code == 404
    assert missing_card.json() == unknown.json()


@pytest.mark.asyncio
async def test_twenty_first_create_is_429(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("API_RATE_LIMIT_INVITE_MAX_REQUESTS", "20")
    monkeypatch.setenv("API_RATE_LIMIT_INVITE_WINDOW_SEC", "3600")
    reset_http_limiters_for_tests()
    place = await _place(db_session)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=2))
    async with _client() as client:
        statuses = [(await _create(client, session_id)).status_code for _ in range(20)]
        blocked = await _create(client, session_id)
    assert statuses == [201] * 20
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Too many requests"


@pytest.mark.asyncio
async def test_price_is_omitted_unless_sender_asked(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=2), price_adult_minor=2500)
    async with _client() as client:
        hidden = await _create(client, session_id, show_price=False)
        shown = await _create(client, session_id, show_price=True)
        hidden_card = await client.get(f"/api/public/invites/{hidden.json()['code']}")
        shown_card = await client.get(f"/api/public/invites/{shown.json()['code']}")
    hidden_raw = json.dumps(hidden_card.json(), ensure_ascii=False)
    assert "price" not in hidden_raw
    assert "2500" not in hidden_raw
    assert "25 BYN" not in hidden_raw
    assert shown_card.json()["session"]["price"] == "25 BYN"


class _ClientBot:
    def __init__(self, token: str) -> None:
        self.telegram_bot_token_client = token
        self.vk_mini_app_protected_key = ""


@pytest.mark.asyncio
async def test_create_with_telegram_init_data_stores_telegram_actor_hash(
    app_use_test_db, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "123456:ABC-DEF"
    user_id = 424242
    monkeypatch.setattr("src.api.miniapp_auth.deps.Settings", lambda: _ClientBot(token))
    raw = _build_signed_init_data(token, user_id=user_id, auth_date=int(time.time()))
    place = await _place(db_session)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=2))
    async with _client() as client:
        created = await client.post(
            "/api/public/invites",
            json={"session_id": session_id, "from_name": "Макс", "to_name": "Аня"},
            headers=_headers(**{"X-Telegram-Init-Data": raw}),
        )
    assert created.status_code == 201, created.text
    stored = (
        await db_session.execute(
            text("SELECT creator_actor_hash FROM ice_invites WHERE code = :code"),
            {"code": created.json()["code"]},
        )
    ).scalar_one()
    assert stored == telegram_actor_hash(user_id)
    assert stored != public_actor_hash(client_ip=_IP, user_agent=_UA)
    telegram_id = (
        await db_session.execute(
            text("SELECT creator_telegram_id FROM ice_invites WHERE code = :code"),
            {"code": created.json()["code"]},
        )
    ).scalar_one()
    assert telegram_id == user_id
