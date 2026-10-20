"""TASK-306: ближайшие свободные окна тренеров в ответе /arenas/{ref}/trainers."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from src.api.app import app
from src.api.public_list_cache import PUBLIC_JSON_FRESH_CACHE
from src.application.arena_profile import backfill_arena_profiles
from src.infrastructure.db.models import SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE
from src.shared.notification_hours import NOTIFICATION_TZ
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.api.test_public_catalog_integration import _create_active_trainer_via_api
from tests.api.test_webapp_client_miniapp_integration import _ensure_trainer_subscription_tier
from tests.db_catalog_helpers import require_seed_service_id

MINSK = ZoneInfo(NOTIFICATION_TZ)


def _day(offset: int):
    return datetime.now(MINSK).date() + timedelta(days=offset)


async def _slot(
    db_session,
    trainer_id: int,
    *,
    days: int,
    hour: int,
    arena_id: int | None,
    status: str = "available",
    capacity: int = 1,
) -> int:
    row = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, arena_id)
            VALUES (:tid, :d, make_time(:h, 0, 0), make_time(:h + 1, 0, 0), :st, :cap, :aid)
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "d": _day(days),
            "h": hour,
            "st": status,
            "cap": capacity,
            "aid": arena_id,
        },
    )
    return int(row.scalar_one())


async def _bookable_trainer(client, db_session, cid: int, arena_id: int, sid: int, name: str) -> int:
    tid = await _create_active_trainer_via_api(
        client,
        db_session,
        city_id=cid,
        service_ids=[sid],
        arena_ids=[arena_id],
        first_name=name,
        last_name="Окна",
    )
    await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
    return tid


async def _fetch(client, arena_id: int) -> dict:
    resp = await client.get(f"/api/public/arenas/{arena_id}/trainers")
    assert resp.status_code == 200, resp.text
    return resp


def _item(resp, tid: int) -> dict:
    return next(it for it in resp.json()["items"] if it["id"] == tid)


@pytest.mark.asyncio
async def test_windows_only_free_future_slots_on_this_arena(app_use_test_db, db_session) -> None:
    sid = await require_seed_service_id(db_session)
    cid = await _insert_city(db_session, name=f"Win-{uuid.uuid4().hex[:6]}")
    arena = await _insert_arena(db_session, cid, name="Каток окон")
    other = await _insert_arena(db_session, cid, name="Другой каток")
    await backfill_arena_profiles(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _bookable_trainer(client, db_session, cid, arena, sid, "Ольга")
        later = await _slot(db_session, tid, days=3, hour=19, arena_id=arena)
        sooner = await _slot(db_session, tid, days=2, hour=10, arena_id=arena)
        await _slot(db_session, tid, days=2, hour=12, arena_id=other)
        await _slot(db_session, tid, days=2, hour=13, arena_id=None)
        await _slot(db_session, tid, days=2, hour=14, arena_id=arena, status="booked")
        await _slot(db_session, tid, days=2, hour=15, arena_id=arena, status="cancelled")
        await _slot(db_session, tid, days=2, hour=16, arena_id=arena, capacity=3)
        await _slot(db_session, tid, days=-1, hour=10, arena_id=arena)
        await _slot(db_session, tid, days=9, hour=10, arena_id=arena)
        taken = await _slot(db_session, tid, days=2, hour=17, arena_id=arena)
        await db_session.execute(
            text("INSERT INTO clients (telegram_id, first_name) VALUES (:tg, 'К') RETURNING id"),
            {"tg": 9_000_000 + uuid.uuid4().int % 1_000_000},
        )
        client_id = (await db_session.execute(text("SELECT max(id) FROM clients"))).scalar_one()
        await db_session.execute(
            text(
                "INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status) "
                "VALUES (:s, :t, :c, :sv, 'confirmed')"
            ),
            {"s": taken, "t": tid, "c": client_id, "sv": sid},
        )
        await db_session.commit()
        resp = await _fetch(client, arena)
    wins = _item(resp, tid)["windows"]
    assert [w["slot_id"] for w in wins] == [sooner, later]
    assert wins[0]["href"] == f"book?slot_id={sooner}"
    assert wins[0]["time"] == "10:00"
    assert wins[1]["time"] == "19:00"
    assert resp.headers["cache-control"] == PUBLIC_JSON_FRESH_CACHE
    # Прежние поля на месте.
    for key in ("id", "can_book", "open_groups_count"):
        assert key in _item(resp, tid)


@pytest.mark.asyncio
async def test_windows_capped_at_six_in_time_order(app_use_test_db, db_session) -> None:
    sid = await require_seed_service_id(db_session)
    cid = await _insert_city(db_session, name=f"Win-{uuid.uuid4().hex[:6]}")
    arena = await _insert_arena(db_session, cid, name="Каток окон")
    await backfill_arena_profiles(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _bookable_trainer(client, db_session, cid, arena, sid, "Ирина")
        ids = []
        for i in range(8):
            ids.append(await _slot(db_session, tid, days=2 + i % 4, hour=8 + i, arena_id=arena))
        await db_session.commit()
        resp = await _fetch(client, arena)
    wins = _item(resp, tid)["windows"]
    assert len(wins) == 6
    starts = [w["starts_at"] for w in wins]
    assert starts == sorted(starts)


@pytest.mark.asyncio
async def test_no_windows_without_booking_and_day_time_in_arena_zone(app_use_test_db, db_session) -> None:
    sid = await require_seed_service_id(db_session)
    cid = await _insert_city(db_session, name=f"Win-{uuid.uuid4().hex[:6]}")
    arena = await _insert_arena(db_session, cid, name="Каток окон")
    await backfill_arena_profiles(db_session)
    await db_session.execute(
        text("UPDATE arena_profiles SET timezone = 'Asia/Yekaterinburg' WHERE arena_id = :a"),
        {"a": arena},
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _bookable_trainer(client, db_session, cid, arena, sid, "Анна")
        no_booking = await _create_active_trainer_via_api(
            client,
            db_session,
            city_id=cid,
            service_ids=[sid],
            arena_ids=[arena],
            first_name="Без",
            last_name="Записи",
        )
        await _ensure_trainer_subscription_tier(db_session, no_booking, SUBSCRIPTION_TIER_CRM)
        await _slot(db_session, no_booking, days=2, hour=10, arena_id=arena)
        s_tom = await _slot(db_session, tid, days=1, hour=20, arena_id=arena)
        await db_session.commit()
        resp = await _fetch(client, arena)
    assert _item(resp, no_booking)["can_book"] is False
    assert _item(resp, no_booking)["windows"] == []
    win = next(w for w in _item(resp, tid)["windows"] if w["slot_id"] == s_tom)
    # 20:00 по Минску (UTC+3) = 22:00 по Екатеринбургу; «день» тоже в поясе арены.
    assert win["time"] == "22:00"
    assert win["starts_at"].endswith("+05:00")
    local = datetime.fromisoformat(win["starts_at"])
    today = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Yekaterinburg")).date()
    expected = "завтра" if local.date() == today + timedelta(days=1) else "сегодня"
    if local.date() > today + timedelta(days=1):
        expected = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")[local.weekday()]
    assert win["day"] == expected
    assert datetime.fromisoformat(win["ends_at"]) - local == timedelta(hours=1)


@pytest.mark.asyncio
async def test_windows_are_one_query_for_all_trainers(app_use_test_db, db_session) -> None:
    sid = await require_seed_service_id(db_session)
    cid = await _insert_city(db_session, name=f"Win-{uuid.uuid4().hex[:6]}")
    arena = await _insert_arena(db_session, cid, name="Каток окон")
    await backfill_arena_profiles(db_session)
    bind = db_session.sync_session.get_bind()

    async def _slot_queries(client) -> int:
        seen = {"n": 0}

        def _before(conn, cursor, statement, parameters, context, executemany):
            if "FROM slots s" in (statement or "") and "ROW_NUMBER" in statement:
                seen["n"] += 1

        event.listen(bind, "before_cursor_execute", _before)
        try:
            await _fetch(client, arena)
        finally:
            event.remove(bind, "before_cursor_execute", _before)
        return seen["n"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _bookable_trainer(client, db_session, cid, arena, sid, "Первый")
        await _slot(db_session, first, days=2, hour=10, arena_id=arena)
        await db_session.commit()
        one = await _slot_queries(client)
        for i in range(10):
            t = await _bookable_trainer(client, db_session, cid, arena, sid, f"Тренер{i}")
            await _slot(db_session, t, days=2, hour=11 + i % 5, arena_id=arena)
        await db_session.commit()
        many = await _slot_queries(client)
    assert one == many == 1
