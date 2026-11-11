"""TASK-379: sessions_left_today on GET /api/public/ice/arenas.

«Сегодня» — календарный день арены. Прошедшие сеансы не входят: их уже
отсекает предикат будущих сеансов (starts_at_utc > now).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from src.api.app import app
from src.api.public_list_cache import PUBLIC_JSON_LIST_CACHE
from src.application.arena_public_use_cases import list_public_ice_arenas
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_city

MINSK = ZoneInfo("Europe/Minsk")
NEW_YORK = ZoneInfo("America/New_York")

# Порядок ключей карточки ленты до аддитивного поля. Новый ключ — последний.
_ITEM_KEYS_BEFORE = (
    "id",
    "slug",
    "city_id",
    "city_name",
    "public_path",
    "name",
    "district",
    "address",
    "latitude",
    "longitude",
    "on_map",
    "distance_km",
    "venue_type",
    "venue_chip",
    "venue_icon",
    "venue_cta",
    "tier",
    "thumb",
    "card",
    "currency_code",
    "live",
    "live_line",
    "freshness",
    "phone",
    "schedule_mode",
    "schedule_reopen_date",
    "schedule_mode_note",
)
_LIVE_SESSION_KEYS = (
    "kind",
    "session_id",
    "outside_window",
    "text",
    "local_date",
    "starts_at_local",
    "price_adult_minor",
    "price_child_minor",
    "price_rental_minor",
    "currency_code",
    "more_count",
    "schedule_basis",
)


def _count_statements(bind):
    counts = {"n": 0, "sql": []}

    def _before(conn, cursor, statement, parameters, context, executemany):
        sql = (statement or "").lstrip()
        if sql[:12].upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            counts["n"] += 1
            counts["sql"].append(" ".join(sql.split()))

    event.listen(bind, "before_cursor_execute", _before)
    return counts, _before


async def _set_tz(db_session, arena_id: int, tz_name: str) -> None:
    await db_session.execute(
        text("UPDATE arena_profiles SET timezone = :tz WHERE arena_id = :id"),
        {"tz": tz_name, "id": arena_id},
    )
    await db_session.flush()


async def _session_at(
    db_session,
    arena_id: int,
    when_local: datetime,
    *,
    kind: str = "public_skate",
) -> int:
    created = await create_ice_session(
        db_session,
        arena_id,
        local_date=when_local.date(),
        starts_at_local=when_local.strftime("%H:%M"),
        duration_minutes=30,
        kind=kind,
        price_adult_minor=850,
    )
    await db_session.flush()
    return int(created["id"])


def _item(payload: dict, arena_id: int) -> dict:
    return next(it for it in payload["items"] if int(it["id"]) == arena_id)


def _assert_previous_fields(item: dict, *, more: int) -> None:
    assert tuple(k for k in item if k != "sessions_left_today") == _ITEM_KEYS_BEFORE
    assert list(item)[-1] == "sessions_left_today"
    assert isinstance(item["sessions_left_today"], int)
    assert item["sessions_left_today"] >= 0
    live = item["live"]
    assert tuple(live) == _LIVE_SESSION_KEYS
    assert live["more_count"] == more
    assert live["kind"] == "session"


@pytest.mark.asyncio
async def test_sessions_left_today_is_subset_of_future(app_use_test_db, db_session) -> None:
    """Сегодня 3 оставшихся при 5 будущих; прошедший сегодня и ОХМ не считаются."""
    cid = await _insert_city(db_session, name=f"TodayN-{uuid.uuid4().hex[:6]}")
    aid = await _insert_arena(db_session, cid, name="Три из пяти")
    await _set_tz(db_session, aid, "Europe/Minsk")
    await _session_at(db_session, aid, datetime(2026, 11, 11, 9, 0, tzinfo=MINSK))
    await _session_at(db_session, aid, datetime(2026, 11, 11, 12, 0, tzinfo=MINSK))
    await _session_at(
        db_session, aid, datetime(2026, 11, 11, 15, 0, tzinfo=MINSK), kind="open_ice"
    )
    await _session_at(db_session, aid, datetime(2026, 11, 11, 18, 0, tzinfo=MINSK))
    await _session_at(
        db_session, aid, datetime(2026, 11, 11, 19, 30, tzinfo=MINSK), kind="hockey_practice"
    )
    await _session_at(db_session, aid, datetime(2026, 11, 12, 12, 0, tzinfo=MINSK))
    await _session_at(db_session, aid, datetime(2026, 11, 13, 12, 0, tzinfo=MINSK))

    now = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)  # 11:00 Минск
    payload = await list_public_ice_arenas(db_session, city_id=cid, intent="skate", now=now)
    item = _item(payload, aid)
    assert item["sessions_left_today"] == 3
    _assert_previous_fields(item, more=4)
    assert "ещё 4" in item["live"]["text"]


@pytest.mark.asyncio
async def test_sessions_left_today_zero_when_only_tomorrow(app_use_test_db, db_session) -> None:
    cid = await _insert_city(db_session, name=f"Today0-{uuid.uuid4().hex[:6]}")
    aid = await _insert_arena(db_session, cid, name="Только завтра")
    await _set_tz(db_session, aid, "Europe/Minsk")
    await _session_at(db_session, aid, datetime(2026, 11, 12, 12, 0, tzinfo=MINSK))

    now = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)
    payload = await list_public_ice_arenas(db_session, city_id=cid, intent="skate", now=now)
    item = _item(payload, aid)
    assert item["sessions_left_today"] == 0
    _assert_previous_fields(item, more=0)
    assert "ещё" not in item["live"]["text"]


@pytest.mark.asyncio
async def test_sessions_left_today_midnight_boundary(app_use_test_db, db_session) -> None:
    """До полуночи поздний сеанс ещё «сегодня»; сразу после — уже нет, ночной — да."""
    cid = await _insert_city(db_session, name=f"Midnight-{uuid.uuid4().hex[:6]}")
    aid = await _insert_arena(db_session, cid, name="Полночь")
    await _set_tz(db_session, aid, "Europe/Minsk")
    await _session_at(db_session, aid, datetime(2026, 11, 11, 23, 40, tzinfo=MINSK))
    await _session_at(db_session, aid, datetime(2026, 11, 12, 0, 20, tzinfo=MINSK))
    await _session_at(db_session, aid, datetime(2026, 11, 12, 10, 0, tzinfo=MINSK))
    await _session_at(db_session, aid, datetime(2026, 11, 13, 12, 0, tzinfo=MINSK))

    before = datetime(2026, 11, 11, 20, 30, tzinfo=timezone.utc)  # 23:30 Минск, 11 ноя
    after = datetime(2026, 11, 11, 21, 10, tzinfo=timezone.utc)  # 00:10 Минск, 12 ноя

    early = await list_public_ice_arenas(db_session, city_id=cid, intent="skate", now=before)
    late = await list_public_ice_arenas(db_session, city_id=cid, intent="skate", now=after)
    early_item = _item(early, aid)
    late_item = _item(late, aid)
    assert early_item["sessions_left_today"] == 1
    assert early_item["live"]["more_count"] == 3
    assert late_item["sessions_left_today"] == 2
    assert late_item["live"]["more_count"] == 2


@pytest.mark.asyncio
async def test_sessions_left_today_uses_arena_timezone(app_use_test_db, db_session) -> None:
    """В Минске уже 12 ноября, в Нью-Йорке ещё 11-е: «сегодня» у каждого своё."""
    cid = await _insert_city(db_session, name=f"Tz-{uuid.uuid4().hex[:6]}")
    minsk = await _insert_arena(db_session, cid, name="Минск")
    nyc = await _insert_arena(db_session, cid, name="Нью-Йорк")
    await _set_tz(db_session, minsk, "Europe/Minsk")
    await _set_tz(db_session, nyc, "America/New_York")

    await _session_at(db_session, minsk, datetime(2026, 11, 12, 2, 0, tzinfo=MINSK))
    await _session_at(db_session, minsk, datetime(2026, 11, 13, 12, 0, tzinfo=MINSK))
    await _session_at(db_session, nyc, datetime(2026, 11, 11, 18, 0, tzinfo=NEW_YORK))
    await _session_at(db_session, nyc, datetime(2026, 11, 11, 20, 0, tzinfo=NEW_YORK))
    await _session_at(db_session, nyc, datetime(2026, 11, 12, 10, 0, tzinfo=NEW_YORK))

    now = datetime(2026, 11, 11, 22, 30, tzinfo=timezone.utc)
    payload = await list_public_ice_arenas(db_session, city_id=cid, intent="skate", now=now)
    assert _item(payload, minsk)["sessions_left_today"] == 1
    assert _item(payload, nyc)["sessions_left_today"] == 2
    assert _item(payload, minsk)["live"]["more_count"] == 1
    assert _item(payload, nyc)["live"]["more_count"] == 2


@pytest.mark.asyncio
async def test_ice_arenas_http_keeps_cache_and_query_count(app_use_test_db, db_session) -> None:
    """Поле едет в JSON ленты; кэш и число запросов (список + медиа) прежние."""
    cid = await _insert_city(db_session, name=f"Http-{uuid.uuid4().hex[:6]}")
    aid = await _insert_arena(db_session, cid, name="По проводу")
    await _set_tz(db_session, aid, "Europe/Minsk")
    await _add_future_session(db_session, aid, days_ahead=1, starts_at_local="14:00")
    await _add_future_session(db_session, aid, days_ahead=3, starts_at_local="16:00")
    await db_session.flush()

    bind = db_session.sync_session.get_bind()
    counts, hook = _count_statements(bind)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/public/ice/arenas", params={"city_id": cid, "intent": "skate"})
    finally:
        event.remove(bind, "before_cursor_execute", hook)

    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == PUBLIC_JSON_LIST_CACHE
    assert "max-age=120" in resp.headers["cache-control"]
    body = resp.json()
    assert set(body) == {
        "items",
        "for_you",
        "ice_company",
        "total",
        "intent",
        "venue_type",
        "venue_type_facets",
        "season_facet",
        "service_count",
        "next_cursor",
        "window",
        "outdoor_live",
    }
    item = _item(body, aid)
    assert item["sessions_left_today"] == 0
    _assert_previous_fields(item, more=1)
    assert counts["n"] == 2
    list_sql = [sql for sql in counts["sql"] if "sessions_left_today" in sql]
    assert len(list_sql) == 1
    assert list_sql[0].lstrip().upper().startswith("SELECT")
