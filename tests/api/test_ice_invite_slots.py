"""TASK-234: список сеансов для приглашения совпадает с правилами создания."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.middleware.http_limits import reset_http_limiters_for_tests
from tests.api.test_ice_invites import _create, _headers, _insert_session
from tests.api.test_public_arenas import _insert_arena, _insert_city

_MINSK = ZoneInfo("Europe/Minsk")


@pytest.fixture(autouse=True)
def _limits() -> None:
    reset_http_limiters_for_tests()
    yield
    reset_http_limiters_for_tests()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _local(*, days: int, hour: int, minute: int = 0) -> datetime:
    moment = datetime.now(_MINSK) + timedelta(days=days)
    return moment.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _utc(*, days: int, hour: int, minute: int = 0) -> datetime:
    return _local(days=days, hour=hour, minute=minute).astimezone(timezone.utc)


async def _place(db_session) -> dict:
    city = f"Слот{uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=city)
    arena = f"Каток {uuid.uuid4().hex[:4]}"
    arena_id = await _insert_arena(db_session, city_id, name=arena, address="ул. Ледовая, 1")
    return {"city_id": city_id, "city": city, "arena_id": arena_id, "arena": arena}


def _ids(body: dict) -> set[int]:
    found = set()
    for arena in body["arenas"]:
        for session in arena["sessions"]:
            found.add(int(session["id"]))
    return found


@pytest.mark.asyncio
async def test_list_is_future_active_public_kinds_only(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    later = await _place(db_session)
    day = _local(days=2, hour=12).date()
    skate = await _insert_session(db_session, place["arena_id"], starts_at=_utc(days=2, hour=19), price_adult_minor=900)
    open_ice = await _insert_session(
        db_session, place["arena_id"], starts_at=_utc(days=2, hour=12), kind="open_ice", price_adult_minor=None
    )
    hockey = await _insert_session(
        db_session, place["arena_id"], starts_at=_utc(days=2, hour=21), kind="hockey_practice", price_adult_minor=2500
    )
    projected = await _insert_session(
        db_session,
        place["arena_id"],
        starts_at=_utc(days=2, hour=18),
        schedule_basis="projected",
        price_adult_minor=1500,
    )
    other_city = await _insert_session(db_session, later["arena_id"], starts_at=_utc(days=2, hour=15))
    past_local = _local(days=-2, hour=19)
    past = await _insert_session(db_session, place["arena_id"], starts_at=past_local.astimezone(timezone.utc))
    cancelled = await _insert_session(
        db_session, place["arena_id"], starts_at=_utc(days=2, hour=16), status="cancelled"
    )
    school = await _insert_session(db_session, place["arena_id"], starts_at=_utc(days=2, hour=11), kind="school_group")
    hidden_arena = await _insert_arena(db_session, place["city_id"], name="Скрытый каток", address="ул. Тихая, 1")
    await db_session.execute(text("UPDATE arenas SET is_active = false WHERE id = :id"), {"id": hidden_arena})
    hidden_id = await _insert_session(db_session, hidden_arena, starts_at=_utc(days=2, hour=13))
    early_arena = await _insert_arena(db_session, place["city_id"], name="Ранний каток", address="пр. Победителей, 1")
    early = await _insert_session(db_session, early_arena, starts_at=_utc(days=2, hour=10), price_adult_minor=900)

    async with _client() as client:
        resp = await client.get(
            "/api/public/invites/slots",
            params={"city_id": place["city_id"], "date": day.isoformat()},
            headers=_headers(),
        )
        past_resp = await client.get(
            "/api/public/invites/slots",
            params={"city_id": place["city_id"], "date": past_local.date().isoformat()},
            headers=_headers(),
        )
    assert resp.status_code == 200, resp.text
    assert past_resp.status_code == 200, past_resp.text
    assert past not in _ids(past_resp.json())
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["date"] == day.isoformat()
    assert body["city_id"] == place["city_id"]
    assert body["next_date"] is None
    assert "projected" not in resp.text
    found = _ids(body)
    assert found == {skate, open_ice, hockey, projected, early}
    assert past not in found
    assert cancelled not in found
    assert school not in found
    assert hidden_id not in found
    assert other_city not in found
    assert body["arenas"][0]["id"] == early_arena
    assert body["arenas"][0]["sessions"][0]["id"] == early
    assert body["arenas"][0]["sessions"][0]["price"] == "9 BYN"
    by_id = {item["id"]: item for arena in body["arenas"] for item in arena["sessions"]}
    assert by_id[open_ice]["price"] is None
    assert by_id[open_ice]["kind"] == "open_ice"
    assert by_id[hockey]["kind"] == "hockey_practice"
    assert by_id[skate]["price"] == "9 BYN"
    assert by_id[early]["starts_at_local"] == "10:00"
    main = next(arena for arena in body["arenas"] if arena["id"] == place["arena_id"])
    assert [item["id"] for item in main["sessions"]] == [open_ice, projected, skate, hockey]


@pytest.mark.asyncio
async def test_every_listed_session_can_be_invited(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    day = _local(days=3, hour=12).date()
    kept = await _insert_session(db_session, place["arena_id"], starts_at=_utc(days=3, hour=18))
    dropped = await _insert_session(db_session, place["arena_id"], starts_at=_utc(days=-1, hour=18))
    async with _client() as client:
        listed = await client.get(
            "/api/public/invites/slots",
            params={"city_id": place["city_id"], "date": day.isoformat()},
            headers=_headers(),
        )
        assert listed.status_code == 200, listed.text
        ids = _ids(listed.json())
        assert kept in ids
        assert dropped not in ids
        for session_id in ids:
            created = await _create(client, session_id, to_name=None)
            assert created.status_code == 201, created.text


@pytest.mark.asyncio
async def test_minsk_midnight_belongs_to_that_calendar_day(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    local = _local(days=4, hour=0, minute=30)
    starts = local.astimezone(timezone.utc)
    assert starts.date() == local.date() - timedelta(days=1)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=starts)
    async with _client() as client:
        own = await client.get(
            "/api/public/invites/slots",
            params={"city_id": place["city_id"], "date": local.date().isoformat()},
            headers=_headers(),
        )
        previous = await client.get(
            "/api/public/invites/slots",
            params={"city_id": place["city_id"], "date": (local.date() - timedelta(days=1)).isoformat()},
            headers=_headers(),
        )
    assert own.status_code == 200, own.text
    assert session_id in _ids(own.json())
    assert own.json()["arenas"][0]["sessions"][0]["starts_at_local"] == "00:30"
    assert session_id not in _ids(previous.json())


@pytest.mark.asyncio
async def test_next_date_when_the_day_is_empty(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    local = _local(days=20, hour=12)
    far_day = local.date()
    await _insert_session(db_session, place["arena_id"], starts_at=local.astimezone(timezone.utc))
    async with _client() as client:
        too_far = await client.get(
            "/api/public/invites/slots",
            params={"city_id": place["city_id"], "date": (far_day - timedelta(days=15)).isoformat()},
            headers=_headers(),
        )
        close = await client.get(
            "/api/public/invites/slots",
            params={"city_id": place["city_id"], "date": (far_day - timedelta(days=14)).isoformat()},
            headers=_headers(),
        )
        filled = await client.get(
            "/api/public/invites/slots",
            params={"city_id": place["city_id"], "date": far_day.isoformat()},
            headers=_headers(),
        )
    assert too_far.status_code == 200, too_far.text
    assert too_far.json()["arenas"] == []
    assert too_far.json()["next_date"] is None
    assert close.json()["arenas"] == []
    assert close.json()["next_date"] == far_day.isoformat()
    assert filled.json()["next_date"] is None
    assert _ids(filled.json())


@pytest.mark.asyncio
async def test_unknown_and_hidden_city_are_404(app_use_test_db, db_session) -> None:
    hidden = await _insert_city(db_session, name=f"Скрыт{uuid.uuid4().hex[:4]}")
    await db_session.execute(text("UPDATE cities SET is_active = false WHERE id = :id"), {"id": hidden})
    missing = int((await db_session.execute(text("SELECT COALESCE(MAX(id), 0) + 1000 FROM cities"))).scalar_one())
    async with _client() as client:
        unknown = await client.get(
            "/api/public/invites/slots",
            params={"city_id": missing, "date": "2026-10-17"},
            headers=_headers(),
        )
        inactive = await client.get(
            "/api/public/invites/slots",
            params={"city_id": hidden, "date": "2026-10-17"},
            headers=_headers(),
        )
    assert unknown.status_code == 404
    assert inactive.status_code == 404


@pytest.mark.asyncio
async def test_session_id_resolves_city_and_day(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    local = _local(days=5, hour=19, minute=15)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=local.astimezone(timezone.utc))
    async with _client() as client:
        resp = await client.get(
            "/api/public/invites/slots",
            params={"session_id": session_id},
            headers=_headers(),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["city_id"] == place["city_id"]
    assert body["date"] == local.date().isoformat()
    assert session_id in _ids(body)
    assert body["arenas"][0]["sessions"][0]["starts_at_local"] == "19:15"
