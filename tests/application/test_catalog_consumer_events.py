"""catalog_consumer_events — WAU, C-B прокси, дедуп (TASK-189)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.catalog_consumer_events import (
    KIND_MINIAPP_CATALOG_ENTRY,
    KIND_PUBLIC_PAGE_VIEW,
    KIND_PUBLIC_TELEGRAM_CTA,
    event_dedup_hash,
    get_catalog_virality_cb_metrics,
    get_catalog_wau,
    is_share_attributed_deeplink_open,
    public_actor_hash,
    record_catalog_consumer_event,
    telegram_actor_hash,
)


@pytest.mark.asyncio
async def test_record_and_wau_dedup(db_session) -> None:
    actor = telegram_actor_hash(4242)
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
async def test_stable_actor_counts_once_per_week(db_session) -> None:
    """AC-1: один telegram_id → один actor_hash на все дни."""
    actor = telegram_actor_hash(9001)
    base = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    for offset in range(7):
        await db_session.execute(
            text(
                """
                INSERT INTO catalog_consumer_events
                    (kind, surface, actor_hash, occurred_at, dedup_key)
                VALUES
                    (:kind, :surface, :actor, :at, :dk)
                """
            ),
            {
                "kind": KIND_PUBLIC_PAGE_VIEW,
                "surface": "place_page",
                "actor": actor,
                "at": base + timedelta(days=offset),
                "dk": event_dedup_hash(
                    kind=KIND_PUBLIC_PAGE_VIEW,
                    surface="place_page",
                    actor_hash=actor,
                    day=(base + timedelta(days=offset)).date(),
                    city_id=1,
                    arena_id=1,
                ),
            },
        )
    await db_session.flush()
    wau = await get_catalog_wau(db_session, days=7, as_of=base + timedelta(days=7))
    assert wau["unique_actors"] == 1


async def _city_and_arenas(db_session, n: int) -> tuple[int, list[int]]:
    city_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO cities (name, country, price_group, is_active, sort_order)
                    VALUES ('Тест-189', 'BY', 'default', true, 0)
                    RETURNING id
                    """
                )
            )
        ).scalar_one()
    )
    arena_ids: list[int] = []
    for i in range(n):
        arena_ids.append(
            int(
                (
                    await db_session.execute(
                        text(
                            """
                            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                            VALUES (:cid, :name, 'ул. Тестовая, 1', true, true)
                            RETURNING id
                            """
                        ),
                        {"cid": city_id, "name": f"Арена-189-{i}"},
                    )
                ).scalar_one()
            )
        )
    await db_session.flush()
    return city_id, arena_ids


@pytest.mark.asyncio
async def test_dedup_per_arena_same_day(db_session) -> None:
    """AC-2: шесть арен → шесть строк."""
    city_id, arena_ids = await _city_and_arenas(db_session, 6)
    actor = telegram_actor_hash(555)
    for arena_id in arena_ids:
        ok = await record_catalog_consumer_event(
            db_session,
            kind=KIND_PUBLIC_PAGE_VIEW,
            surface="place_page",
            actor_hash=actor,
            city_id=city_id,
            arena_id=arena_id,
        )
        assert ok is True
    count = (
        await db_session.execute(
            text(
                """
                SELECT COUNT(*) FROM catalog_consumer_events
                WHERE actor_hash = :a AND kind = :k
                """
            ),
            {"a": actor, "k": KIND_PUBLIC_PAGE_VIEW},
        )
    ).scalar_one()
    assert int(count) == 6


def test_public_actor_hash_stable_across_days() -> None:
    a = public_actor_hash(client_ip="1.2.3.4", user_agent="Test")
    b = public_actor_hash(client_ip="1.2.3.4", user_agent="Test")
    assert a == b
    assert a is not None


def test_bare_catalog_not_share_open() -> None:
    """AC-4."""
    assert is_share_attributed_deeplink_open("catalog", None) is False
    assert is_share_attributed_deeplink_open("catalog_1_skate", None) is True


@pytest.mark.asyncio
async def test_parallel_dedup_key_single_row(db_session) -> None:
    """AC-5: повтор с тем же dedup_key не вставляет вторую строку."""
    city_id, arena_ids = await _city_and_arenas(db_session, 1)
    arena_id = arena_ids[0]
    actor = telegram_actor_hash(8080)
    dk = event_dedup_hash(
        kind=KIND_MINIAPP_CATALOG_ENTRY,
        surface="miniapp_shell",
        actor_hash=actor,
        day=datetime(2026, 10, 6, tzinfo=timezone.utc).date(),
        city_id=city_id,
        arena_id=arena_id,
    )
    assert dk is not None
    for _ in range(3):
        result = await db_session.execute(
            text(
                """
                INSERT INTO catalog_consumer_events
                    (kind, surface, actor_hash, city_id, arena_id, dedup_key, start_param, payload)
                VALUES
                    (:kind, :surface, :actor, :city, :arena, :dk, 'catalog_1_x', '{}'::jsonb)
                ON CONFLICT (dedup_key) WHERE dedup_key IS NOT NULL DO NOTHING
                RETURNING id
                """
            ),
            {
                "kind": KIND_MINIAPP_CATALOG_ENTRY,
                "surface": "miniapp_shell",
                "actor": actor,
                "city": city_id,
                "arena": arena_id,
                "dk": dk,
            },
        )
        if result.first() is None:
            break
    await db_session.flush()
    n = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM catalog_consumer_events WHERE dedup_key = :dk"),
            {"dk": dk},
        )
    ).scalar_one()
    assert int(n) == 1


@pytest.mark.asyncio
async def test_virality_metrics_empty(db_session) -> None:
    metrics = await get_catalog_virality_cb_metrics(db_session, days=7)
    assert metrics["metric"] == "catalog_virality_cb"
    assert "catalog_wau" in metrics


@pytest.mark.asyncio
async def test_cta_and_deeplink_flow(db_session) -> None:
    pub = public_actor_hash(client_ip="10.0.0.1", user_agent="Mozilla")
    await record_catalog_consumer_event(
        db_session,
        kind=KIND_PUBLIC_TELEGRAM_CTA,
        surface="place_page",
        actor_hash=pub,
        start_param="arena_99",
    )
    tg = telegram_actor_hash(777)
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
