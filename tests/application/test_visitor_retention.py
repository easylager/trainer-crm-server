"""Админские «Возвраты посетителей»: корзины 1 / 2 / 3–4 / 5+ дней по неделям и за всё время."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from src.application.visitor_retention import WEEKS, get_visitor_retention

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)  # воскресенье; неделя пн 16.11 – вс 22.11
PV = "public_page_view"


async def _visit(db, actor: str, day: int, hour: int = 12, *, kind: str = PV, ua: str | None = None) -> None:
    payload = f'{{"ua_class": "{ua}"}}' if ua else "{}"
    await db.execute(
        text(
            "INSERT INTO catalog_consumer_events (kind, surface, actor_hash, occurred_at, payload) "
            "VALUES (:k, 'site', :a, :w, CAST(:p AS jsonb))"
        ),
        {"k": kind, "a": actor, "w": datetime(2026, 11, day, hour, tzinfo=timezone.utc), "p": payload},
    )


@pytest.mark.asyncio
async def test_weeks_buckets_and_all_time(db_session) -> None:
    before = await get_visitor_retention(db_session, now=NOW)
    # Текущая неделя (с 16.11): A — 1 день (два захода в один день), B — 2 дня, C — 5 дней.
    await _visit(db_session, "ret-a", 16, 9)
    await _visit(db_session, "ret-a", 16, 15)
    await _visit(db_session, "ret-b", 16)
    await _visit(db_session, "ret-b", 17, kind="miniapp_catalog_entry")
    for d in (16, 17, 18, 19, 20):
        await _visit(db_session, "ret-c", d)
    # Бот и без хэша не считаются; C заходил и неделей раньше (9.11) — там он «1 день».
    await _visit(db_session, "ret-bot", 16, ua="bot")
    await _visit(db_session, "ret-c", 9)
    await db_session.commit()
    after = await get_visitor_retention(db_session, now=NOW)

    assert len(after["weeks"]) == WEEKS
    cur_b, cur_a = before["weeks"][0], after["weeks"][0]
    assert cur_a["current"] and cur_a["week_start"] == "2026-11-16"
    assert [cur_a[k] - cur_b[k] for k in ("total", "d1", "d2", "d3_4", "d5p")] == [3, 1, 1, 0, 1]
    assert cur_a["returned"] - cur_b["returned"] == 2
    prev_b, prev_a = before["weeks"][1], after["weeks"][1]
    assert prev_a["week_start"] == "2026-11-09" and not prev_a["current"]
    assert [prev_a[k] - prev_b[k] for k in ("total", "d1")] == [1, 1]
    # За всё время C — 6 разных дней (5+), A — 1, B — 2.
    allb, alla = before["all_time"], after["all_time"]
    assert [alla[k] - allb[k] for k in ("total", "d1", "d2", "d5p")] == [3, 1, 1, 1]


@pytest.mark.asyncio
async def test_stats_endpoint_returns_retention(app_use_test_db, db_session) -> None:
    from src.application.stats_use_cases import get_platform_stats

    data = (await get_platform_stats(db_session))["visitor_retention"]
    assert data["metric"] == "visitor_retention" and len(data["weeks"]) == WEEKS
    assert set(data["all_time"]) == {"total", "d1", "d2", "d3_4", "d5p", "returned", "returned_pct"}
