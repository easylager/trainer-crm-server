"""API tests for typical session load (TASK-290)."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.deps import get_admin_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.arena_profile import backfill_arena_profiles
from src.application.session_load import invalidate_session_load_cache


@contextmanager
def patch_admin_principal(user_id: int = 4242) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)
    app.dependency_overrides[get_admin_miniapp_principal] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_admin_miniapp_principal, None)


async def _insert_arena_with_profile(db_session) -> tuple[int, str]:
    r = await db_session.execute(
        text("SELECT id FROM cities WHERE country = 'BY' ORDER BY id LIMIT 1")
    )
    cid = int(r.scalar_one())
    ins = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
            VALUES (:cid, :name, 'ул. Ледовая, 1', true, true)
            RETURNING id
            """
        ),
        {"cid": cid, "name": f"LoadArena-{uuid.uuid4().hex[:6]}"},
    )
    aid = int(ins.scalar_one())
    await backfill_arena_profiles(db_session)
    slug_row = await db_session.execute(
        text("SELECT slug FROM arena_profiles WHERE arena_id = :aid"),
        {"aid": aid},
    )
    slug = str(slug_row.scalar_one())
    return aid, slug


@pytest.mark.asyncio
async def test_public_skate_has_typical_load_fields(db_session) -> None:
    aid, slug = await _insert_arena_with_profile(db_session)
    day = date.today() + timedelta(days=14)
    start = datetime.now(timezone.utc) + timedelta(days=14)
    end = start + timedelta(hours=1)
    await db_session.execute(
        text(
            """
            INSERT INTO ice_sessions (
                arena_id, kind, status, starts_at_utc, ends_at_utc,
                local_date, starts_at_local, ends_at_local, currency_code
            )
            VALUES (:aid, 'public_skate', 'active', :start, :end, :day, '14:00', '15:00', 'BYN')
            """
        ),
        {
            "aid": aid,
            "day": day,
            "start": start,
            "end": end,
        },
    )
    await db_session.commit()
    invalidate_session_load_cache()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/public/arenas/{slug}/sessions",
            params={"from": day.isoformat(), "to": day.isoformat()},
        )
    assert resp.status_code == 200
    data = resp.json()
    sessions = data["days"][0]["sessions"]
    skate = next(s for s in sessions if s["kind"] == "public_skate")
    assert skate["typical_load_level"] in ("calm", "medium", "busy")
    assert skate["typical_load_label"]


@pytest.mark.asyncio
async def test_admin_global_rule_changes_public_response(db_session) -> None:
    aid, slug = await _insert_arena_with_profile(db_session)
    day = date(2026, 10, 20)  # Monday
    await db_session.execute(
        text(
            """
            INSERT INTO ice_sessions (
                arena_id, kind, status, starts_at_utc, ends_at_utc,
                local_date, starts_at_local, ends_at_local, currency_code
            )
            VALUES (:aid, 'public_skate', 'active', :start, :end, :day, '10:00', '11:00', 'BYN')
            """
        ),
        {
            "aid": aid,
            "day": day,
            "start": datetime(2026, 10, 20, 7, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc),
        },
    )
    await db_session.commit()
    invalidate_session_load_cache()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = await client.get(
            f"/api/public/arenas/{slug}/sessions",
            params={"from": day.isoformat(), "to": day.isoformat()},
        )
        level_before = before.json()["days"][0]["sessions"][0]["typical_load_level"]

        with patch_admin_principal():
            put = await client.put(
                "/api/webapp/admin/session-load/global",
                json={
                    "day_group": "mon_thu",
                    "intervals": [
                        {"starts_from": "00:00", "starts_before": "23:59", "level": "busy"},
                    ],
                },
            )
        assert put.status_code == 200
        invalidate_session_load_cache()
        after = await client.get(
            f"/api/public/arenas/{slug}/sessions",
            params={"from": day.isoformat(), "to": day.isoformat()},
        )
    level_after = after.json()["days"][0]["sessions"][0]["typical_load_level"]
    assert level_before == "calm"
    assert level_after == "busy"


@pytest.mark.asyncio
async def test_city_day_sessions_carry_typical_load(db_session) -> None:
    """День города: у сеанса нет local_date в словаре — уровень всё равно считается от дня страницы."""
    from src.application.ice_city_day import get_city_ice_day

    aid, _slug = await _insert_arena_with_profile(db_session)
    cid = int((await db_session.execute(text("SELECT city_id FROM arenas WHERE id = :a"), {"a": aid})).scalar_one())
    day = date.today() + timedelta(days=10)
    while day.weekday() != 5:  # суббота: 14:00 на steady — людно
        day += timedelta(days=1)
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=11)
    await db_session.execute(
        text(
            """
            INSERT INTO ice_sessions (
                arena_id, kind, status, starts_at_utc, ends_at_utc,
                local_date, starts_at_local, ends_at_local, currency_code
            )
            VALUES (:aid, 'public_skate', 'active', :start, :end, :day, '14:00', '15:00', 'BYN')
            """
        ),
        {"aid": aid, "day": day, "start": start, "end": start + timedelta(hours=1)},
    )
    await db_session.commit()
    invalidate_session_load_cache()

    out = await get_city_ice_day(db_session, city_id=cid, on_date=day)
    mine = [s for a in out["arenas"] if a["arena_id"] == aid for s in a["sessions"]]
    assert mine and mine[0]["typical_load_level"] == "busy"
    assert mine[0]["typical_load_label"] == "Людно"
    assert "arena_id" not in mine[0]
