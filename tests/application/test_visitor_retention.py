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
async def test_weeks_buckets_new_vs_returning_and_channels(db_session) -> None:
    before = await get_visitor_retention(db_session, now=NOW)
    # Текущая неделя (с 16.11), сайт: A — 1 день (два захода в один день), B — 2 дня, C — 5 дней.
    await _visit(db_session, "ret-a", 16, 9)
    await _visit(db_session, "ret-a", 16, 15)
    await _visit(db_session, "ret-b", 16)
    await _visit(db_session, "ret-b", 17)
    for d in (16, 17, 18, 19, 20):
        await _visit(db_session, "ret-c", d)
    # Бот не считается; C заходил и неделей раньше (9.11) — там он «новый», на этой неделе «вернувшийся».
    await _visit(db_session, "ret-bot", 16, ua="bot")
    await _visit(db_session, "ret-c", 9)
    # Mini App: D — 1 день на этой неделе, первый визит за историю — тоже на ней.
    await _visit(db_session, "ret-d", 17, kind="miniapp_catalog_entry")
    await db_session.commit()
    after = await get_visitor_retention(db_session, now=NOW)

    def delta(block_b, block_a, keys):
        return [block_a[k] - block_b[k] for k in keys]

    keys = ("total", "d1", "d2", "d3_4", "d5p", "new")
    assert len(after["weeks"]) == WEEKS
    cur_a = after["weeks"][0]
    assert cur_a["current"] and cur_a["week_start"] == "2026-11-16"
    # Сайт: A (1 день, новый), B (2 дня, новый), C (5 дней, вернувшийся).
    site = delta(before["channels"]["site"]["weeks"][0], after["channels"]["site"]["weeks"][0], keys)
    assert site == [3, 1, 1, 0, 1, 2]
    # Mini App: один новый.
    app = delta(before["channels"]["app"]["weeks"][0], after["channels"]["app"]["weeks"][0], keys)
    assert app == [1, 1, 0, 0, 0, 1]
    # «Всего» — сумма каналов; «вернувшиеся» = всего − новые.
    assert delta(before["weeks"][0], cur_a, keys) == [4, 2, 1, 0, 1, 3]
    assert cur_a["came_back"] == cur_a["total"] - cur_a["new"]
    # Неделей раньше C — один из «1 дня» и «новый».
    prev_b, prev_a = before["channels"]["site"]["weeks"][1], after["channels"]["site"]["weeks"][1]
    assert prev_a["week_start"] == "2026-11-09"
    assert delta(prev_b, prev_a, ("total", "d1", "new")) == [1, 1, 1]
    # За всё время: C — 6 разных дней (5+), A — 1, B — 2 (D в другом канале).
    allb, alla = before["channels"]["site"]["all_time"], after["channels"]["site"]["all_time"]
    assert delta(allb, alla, ("total", "d1", "d2", "d5p")) == [3, 1, 1, 1]


@pytest.mark.asyncio
async def test_stats_endpoint_returns_retention(app_use_test_db, db_session) -> None:
    from src.application.stats_use_cases import get_platform_stats

    data = (await get_platform_stats(db_session))["visitor_retention"]
    assert data["metric"] == "visitor_retention" and len(data["weeks"]) == WEEKS
    assert set(data["channels"]) == {"site", "app"}
    assert {"total", "d1", "d2", "d3_4", "d5p", "returned", "new", "came_back", "came_back_pct"} <= set(data["all_time"])
