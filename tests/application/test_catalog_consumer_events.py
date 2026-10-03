"""catalog_consumer_events — WAU, C-B прокси, дедуп."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from src.application.catalog_consumer_events import (
    KIND_MINIAPP_CATALOG_ENTRY,
    KIND_PUBLIC_PAGE_VIEW,
    KIND_PUBLIC_TELEGRAM_CTA,
    get_catalog_virality_cb_metrics,
    get_catalog_wau,
    public_actor_hash,
    record_catalog_consumer_event,
    telegram_actor_hash,
)


@pytest.mark.asyncio
async def test_record_and_wau_dedup(db_session) -> None:
    day = datetime.now(timezone.utc).date()
    actor = telegram_actor_hash(4242, day)
    ok1 = await record_catalog_consumer_event(
        db_session,
        kind=KIND_MINIAPP_CATALOG_ENTRY,
        surface="miniapp_ice",
        actor_hash=actor,
        start_param="catalog_1_skate_weekend",
    )
    ok2 = await record_catalog_consumer_event(
        db_session,
        kind=KIND_MINIAPP_CATALOG_ENTRY,
        surface="miniapp_ice",
        actor_hash=actor,
    )
    assert ok1 is True
    assert ok2 is False
    wau = await get_catalog_wau(db_session, days=7)
    assert wau["unique_actors"] >= 1


@pytest.mark.asyncio
async def test_public_actor_hash_stable() -> None:
    day = datetime.now(timezone.utc).date()
    a = public_actor_hash(client_ip="1.2.3.4", user_agent="Test", day=day)
    b = public_actor_hash(client_ip="1.2.3.4", user_agent="Test", day=day)
    assert a == b
    assert a is not None


@pytest.mark.asyncio
async def test_virality_metrics_empty(db_session) -> None:
    metrics = await get_catalog_virality_cb_metrics(db_session, days=7)
    assert metrics["metric"] == "catalog_virality_cb"
    assert "catalog_wau" in metrics


@pytest.mark.asyncio
async def test_cta_and_deeplink_flow(db_session) -> None:
    day = datetime.now(timezone.utc).date()
    pub = public_actor_hash(client_ip="10.0.0.1", user_agent="Mozilla", day=day)
    await record_catalog_consumer_event(
        db_session,
        kind=KIND_PUBLIC_TELEGRAM_CTA,
        surface="place_page",
        actor_hash=pub,
        start_param="arena_99",
    )
    tg = telegram_actor_hash(777, day)
    await record_catalog_consumer_event(
        db_session,
        kind=KIND_MINIAPP_CATALOG_ENTRY,
        surface="miniapp_shell",
        actor_hash=tg,
        start_param="arena_99",
    )
    row = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM catalog_consumer_events WHERE kind = :k"),
            {"k": KIND_PUBLIC_TELEGRAM_CTA},
        )
    ).scalar_one()
    assert int(row) >= 1
