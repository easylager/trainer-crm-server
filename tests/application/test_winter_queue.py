"""Приоритет очереди админа, строка сводки и правило молчания (TASK-343)."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from src.application import winter_asks, winter_marks, winter_subscriptions
from src.application import winter_queue as wq
from src.application.winter_report import winter_summary
from tests.application.winter_helpers import NOW, make_point


async def _item(db, kind, arena, age_h, ref=None):
    await db.execute(
        text("INSERT INTO seasonal_moderation_items (kind, arena_id, ref_id, created_at) VALUES (:k, :a, :r, :c)"),
        {"k": kind, "a": arena, "r": ref, "c": NOW - timedelta(hours=age_h)},
    )


@pytest.mark.asyncio
async def test_disputes_and_doubtful_come_before_new_photos_and_points(db_session):
    a, b, c, d = [await make_point(db_session, name=n) for n in "ABCD"]
    await _item(db_session, "new_point", a, 50)          # самая старая, но самая низкая
    await _item(db_session, "photo_first", b, 30, ref=1)
    await _item(db_session, "gone", c, 5)
    await _item(db_session, "dispute", d, 1)             # самая свежая, но первая
    order = [i["kind"] for i in await wq.next_items(db_session, 10)]
    assert order == ["dispute", "gone", "photo_first", "new_point"]
    only = await wq.next_items(db_session, 10, kinds=("photo_first",))
    assert [i["kind"] for i in only] == ["photo_first"]


@pytest.mark.asyncio
async def test_same_priority_oldest_first(db_session):
    a, b = await make_point(db_session, name="A"), await make_point(db_session, name="B")
    await _item(db_session, "gone", a, 2)
    await _item(db_session, "gone", b, 9)
    assert [i["arena_id"] for i in await wq.next_items(db_session, 10)] == [b, a]


@pytest.mark.asyncio
async def test_summary_line_has_queue_breakdown_age_and_unconfirmed(db_session):
    a, b = await make_point(db_session, name="A"), await make_point(db_session, name="B")
    await _item(db_session, "dispute", a, 3)
    await _item(db_session, "new_point", b, 10)
    s = await winter_summary(db_session, NOW)
    assert "очередь админа 2 (споры 1, новые точки 1), старейшая 10 ч" in s["line"]
    assert "не подтверждено на сезон 2" in s["line"]
    assert "ВНИМАНИЕ" not in s["line"] and s["queue_info"]["alarm"] is False


@pytest.mark.asyncio
async def test_alarm_when_oldest_over_24h_or_more_than_20(db_session):
    a = await make_point(db_session, name="A")
    await _item(db_session, "gone", a, 30)
    q = await wq.queue_overview(db_session, NOW)
    assert q["alarm"] and "ВНИМАНИЕ" in wq.queue_line(q) and "сами ничего не публикуем" in wq.queue_line(q)
    await db_session.execute(text("DELETE FROM seasonal_moderation_items"))
    for i in range(21):
        await _item(db_session, "new_point", await make_point(db_session, name=f"P{i}"), 1)
    assert (await wq.queue_overview(db_session, NOW))["alarm"]


@pytest.mark.asyncio
async def test_pending_import_run_is_counted(db_session):
    await db_session.execute(text(
        "INSERT INTO winter_import_runs (season, file_sha256, status, diff) VALUES (2026, 'x', 'pending', '{}')"))
    q = await wq.queue_overview(db_session, NOW)
    assert q["import_runs"] == 1 and "сверка 1" in wq.queue_line(q)


@pytest.mark.asyncio
async def test_seven_days_of_admin_silence_publish_nothing(db_session):
    """Весь фоновый цикл при неделе молчания: ни фото, ни кандидат, ни «под вопросом», ни дифф сами не меняются."""
    cand = await make_point(db_session, name="OSM", state="hidden")
    await db_session.execute(text("UPDATE seasonal_rink_seasons SET hidden_reason='candidate' WHERE arena_id=:a"), {"a": cand})
    doubtful = await make_point(db_session, name="Под вопросом")
    await db_session.execute(text("UPDATE seasonal_rink_seasons SET doubtful=true WHERE arena_id=:a"), {"a": doubtful})
    photo_point = await make_point(db_session, name="С фото")
    pid = (await db_session.execute(text(
        "INSERT INTO seasonal_rink_photos (arena_id, author_telegram_id, storage_key) VALUES (:a, 9, 'k') RETURNING id"), {"a": photo_point})).scalar_one()
    await _item(db_session, "new_point", cand, 24 * 7)
    await _item(db_session, "gone", doubtful, 24 * 7)
    await _item(db_session, "photo_first", photo_point, 24 * 7, ref=pid)
    await db_session.execute(text(
        "INSERT INTO winter_import_runs (season, file_sha256, status, diff) VALUES (2026, 'z', 'pending', '{\"counts\": {}}')"))

    later = NOW + timedelta(days=7)
    await winter_marks.recompute_stale(db_session, later)
    await winter_subscriptions.fan_out_events(db_session, later)
    await winter_asks.expire_ignored(db_session, later)
    await winter_summary(db_session, later)

    assert (await db_session.execute(text("SELECT count(*) FROM seasonal_moderation_items WHERE status='open'"))).scalar_one() == 3
    assert (await db_session.execute(text("SELECT status, published FROM seasonal_rink_photos WHERE id=:i"), {"i": pid})).one() == ("pending", False)
    assert (await db_session.execute(text("SELECT state, hidden_reason FROM seasonal_rink_seasons WHERE arena_id=:a"), {"a": cand})).one() == ("hidden", "candidate")
    assert (await db_session.execute(text("SELECT doubtful, state FROM seasonal_rink_seasons WHERE arena_id=:a"), {"a": doubtful})).one() == (True, "waiting")
    assert (await db_session.execute(text("SELECT status FROM winter_import_runs"))).scalar_one() == "pending"
    assert (await db_session.execute(text("SELECT count(*) FROM seasonal_rink_seasons WHERE state='flooded'"))).scalar_one() == 0
    assert (await db_session.execute(text("SELECT count(*) FROM winter_flood_events"))).scalar_one() == 0
