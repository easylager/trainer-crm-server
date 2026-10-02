"""TASK-146: честный флаг свежести расписания в публичном API (карточка, лента, сеансы)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_city


async def _job(db_session, arena_id: int, *, last_ok_at: datetime | None, enabled: bool = True) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at,
                                         config, created_at, last_ok_at)
            VALUES (:aid, 'fresh_test_v1', :en, 'daily', now(), '{}'::jsonb, now() - interval '30 days', :ok)
            """
        ),
        {"aid": arena_id, "en": enabled, "ok": last_ok_at},
    )


@pytest.mark.asyncio
async def test_freshness_flags_in_card_list_and_sessions(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    cid = await _insert_city(db_session, name=f"Fresh-{uuid.uuid4().hex[:6]}")
    stale = await _insert_arena(db_session, cid, name="Каток Устаревший")
    fresh = await _insert_arena(db_session, cid, name="Каток Свежий")
    manual = await _insert_arena(db_session, cid, name="Каток Ручной")
    for arena_id in (stale, fresh, manual):
        await _add_future_session(db_session, arena_id, observed_at=now - timedelta(days=1))
    await _job(db_session, stale, last_ok_at=now - timedelta(hours=9))
    await _job(db_session, fresh, last_ok_at=now - timedelta(minutes=10))
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cards = {aid: (await client.get(f"/api/public/arenas/{aid}")).json() for aid in (stale, fresh, manual)}
        listing = await client.get("/api/public/ice/arenas", params={"city_id": cid})
        sessions = await client.get(f"/api/public/arenas/{stale}/sessions")

    st = cards[stale]["freshness"]
    assert st["schedule_stale"] is True
    assert st["schedule_auto"] is True
    # Последнее подтверждение — успешный прогон 9 ч назад, а не observed_at сеанса суточной давности.
    observed = datetime.fromisoformat(st["schedule_observed_at"])
    assert abs((observed - (now - timedelta(hours=9))).total_seconds()) < 60

    fr = cards[fresh]["freshness"]
    assert (fr["schedule_stale"], fr["schedule_auto"]) == (False, True)

    mn = cards[manual]["freshness"]
    assert (mn["schedule_stale"], mn["schedule_auto"]) == (False, False)
    assert mn["schedule_observed_at"] is not None  # observed_at ручного сеанса
    # Старые поля карточки на месте.
    assert "schedule_valid_until" in mn and "source_url" in mn

    assert listing.status_code == 200, listing.text
    by_id = {item["id"]: item for item in listing.json()["items"]}
    assert by_id[stale]["freshness"]["schedule_stale"] is True
    assert by_id[fresh]["freshness"]["schedule_stale"] is False
    assert by_id[manual]["freshness"]["schedule_auto"] is False

    assert sessions.status_code == 200, sessions.text
    assert sessions.json()["freshness"]["schedule_stale"] is True
