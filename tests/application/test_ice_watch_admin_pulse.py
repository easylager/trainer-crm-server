"""Админский пульс подписок на расписание (клики watch_* + активные/отключённые)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.catalog_consumer_events import KIND_PUBLIC_TELEGRAM_CTA, record_catalog_consumer_event
from src.application.client_ice_watch_use_cases import get_ice_watch_admin_pulse, subscribe_ice_watch
from src.infrastructure.db.models import ICE_WATCH_KIND_SESSIONS
from tests.application.test_ice_watch_delivery import _client, _setup


@pytest.mark.asyncio
async def test_ice_watch_admin_pulse_counts_clicks_and_watches(db_session) -> None:
    city_id, arena_id, tid, client_id = await _setup(db_session)
    other_tid = tid + 1
    other_client = await _client(db_session, telegram_id=other_tid)
    as_of = datetime.now(timezone.utc)
    await record_catalog_consumer_event(
        db_session,
        kind=KIND_PUBLIC_TELEGRAM_CTA,
        surface="place_page",
        actor_hash="actor-watch-1",
        city_id=city_id,
        arena_id=arena_id,
        start_param=f"watch_{arena_id}",
        payload={"ingress": "public_cta"},
        dedup=False,
    )
    # Чужой CTA не входит в счётчик.
    await record_catalog_consumer_event(
        db_session,
        kind=KIND_PUBLIC_TELEGRAM_CTA,
        surface="place_page",
        actor_hash="actor-other",
        city_id=city_id,
        arena_id=arena_id,
        start_param=f"arena_{arena_id}",
        payload={"ingress": "public_cta"},
        dedup=False,
    )
    await subscribe_ice_watch(
        db_session,
        client_id=client_id,
        telegram_id=tid,
        arena_id=arena_id,
        watch_kind=ICE_WATCH_KIND_SESSIONS,
        filter_json={"when": "any", "intent": "skate"},
        city_id=city_id,
    )
    cancelled = await subscribe_ice_watch(
        db_session,
        client_id=other_client,
        telegram_id=other_tid,
        arena_id=arena_id,
        watch_kind=ICE_WATCH_KIND_SESSIONS,
        filter_json={"when": "any", "intent": "skate"},
        city_id=city_id,
    )
    await db_session.execute(
        text("UPDATE client_ice_watches SET active = false WHERE id = :id"),
        {"id": cancelled["id"]},
    )
    await db_session.commit()

    pulse = await get_ice_watch_admin_pulse(db_session, as_of=as_of + timedelta(seconds=1))
    assert pulse["metric"] == "ice_watch_pulse"
    assert pulse["clicks_7d"] >= 1
    assert pulse["clickers_7d"] >= 1
    assert pulse["active"] >= 1
    assert pulse["cancelled"] >= 1
    assert pulse["new_active_7d"] >= 1