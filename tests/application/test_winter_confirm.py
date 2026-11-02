"""Владелец 02.11: «залит» только с подтверждением админа / источника. Все переходы (TASK-343)."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from src.application import winter_admin as wa
from src.application import winter_marks as wm
from src.application import winter_queue as wq
from src.application import winter_subscriptions as wsub
from src.application.winter_public import get_point, list_points
from tests.application.winter_helpers import NOW, make_point


async def row(db, aid):
    return (await db.execute(
        text("SELECT state, state_source, pending_confirm FROM seasonal_rink_seasons WHERE arena_id=:a"), {"a": aid}
    )).one()


async def events(db, aid):
    return int((await db.execute(text("SELECT count(*) FROM winter_flood_events WHERE arena_id=:a"), {"a": aid})).scalar_one())


async def open_items(db, aid, kind="confirm_flood"):
    return int((await db.execute(
        text("SELECT count(*) FROM seasonal_moderation_items WHERE arena_id=:a AND kind=:k AND status='open'"),
        {"a": aid, "k": kind})).scalar_one())


async def flooded_marks(db, aid, n, *, source="telegram", ago_h=0.0):
    for i in range(n):
        who = 1000 + i
        await wm.record_mark(
            db, arena_id=aid, kind="ice", value="flooded", source=source, actor=f"tg:{who}", telegram_id=who,
            now=NOW - timedelta(hours=ago_h),
        )


@pytest.mark.asyncio
async def test_ten_marks_without_admin_stay_waiting_with_pending_and_queue_item(db_session):
    aid = await make_point(db_session)
    await flooded_marks(db_session, aid, 10)
    assert tuple(await row(db_session, aid)) == ("waiting", "import", True)
    assert await events(db_session, aid) == 0  # рассылки из отметок нет
    assert await open_items(db_session, aid) == 1
    public = await get_point(db_session, aid, now=NOW)
    assert public["state"] == "waiting" and public["pending"] and public["pending_people"] == 10
    from src.application.winter_page import checked_line

    assert checked_line(public) == "10 человек отметили, что залит · проверяем"


@pytest.mark.asyncio
async def test_pending_hides_crowd_and_hockey_on_unflooded_point(db_session):
    aid = await make_point(db_session)
    await flooded_marks(db_session, aid, 2)
    await wm.record_mark(db_session, arena_id=aid, kind="crowd", value="few", source="telegram", actor="tg:1000", telegram_id=1000, now=NOW)
    public = await get_point(db_session, aid, now=NOW)
    assert public["crowd"] is None and public["hockey"] is None


@pytest.mark.asyncio
async def test_admin_confirms_flooded_and_broadcast_starts(db_session):
    aid = await make_point(db_session)
    await wsub.subscribe_point(db_session, 77, aid)
    await flooded_marks(db_session, aid, 3)
    assert await events(db_session, aid) == 0
    assert await wa.resolve_confirm_flood(db_session, aid, "flooded", admin_id=1, now=NOW)
    assert tuple(await row(db_session, aid)) == ("flooded", "admin", False)
    assert await events(db_session, aid) == 1 and await open_items(db_session, aid) == 0
    assert await wsub.fan_out_events(db_session, NOW + timedelta(minutes=10)) == 1
    # новые отметки после решения не поднимают запрос заново
    await wm.recompute_point(db_session, aid, 2026, NOW + timedelta(hours=1))
    assert (await row(db_session, aid)).state == "flooded" and not (await row(db_session, aid)).pending_confirm


@pytest.mark.asyncio
async def test_admin_not_flooded_returns_waiting_and_old_marks_do_not_come_back(db_session):
    aid = await make_point(db_session)
    await flooded_marks(db_session, aid, 3, ago_h=2)
    assert await wa.resolve_confirm_flood(db_session, aid, "waiting", admin_id=1, now=NOW - timedelta(hours=1))
    await wm.recompute_point(db_session, aid, 2026, NOW)
    assert tuple(await row(db_session, aid)) == ("waiting", "admin", False)
    assert await events(db_session, aid) == 0 and await open_items(db_session, aid) == 0
    # новые отметки после решения снова спрашивают админа
    await flooded_marks(db_session, aid, 2, ago_h=0)
    assert (await row(db_session, aid)).pending_confirm


@pytest.mark.asyncio
async def test_ask_more_closes_request_without_status_change(db_session):
    aid = await make_point(db_session)
    await flooded_marks(db_session, aid, 2)
    assert await wa.resolve_confirm_flood(db_session, aid, "ask_more", admin_id=1, now=NOW)
    state = await row(db_session, aid)
    assert state.state == "waiting" and not state.pending_confirm and await events(db_session, aid) == 0


@pytest.mark.asyncio
async def test_parser_flooded_is_shown_and_broadcasts(db_session):
    aid = await make_point(db_session)
    assert await wm.set_state_source(db_session, aid, "flooded", now=NOW)
    assert tuple(await row(db_session, aid)) == ("flooded", "parser", False)
    assert await events(db_session, aid) == 1
    public = await get_point(db_session, aid, now=NOW)
    assert public["state"] == "flooded" and public["checked_by"] == "source"


@pytest.mark.asyncio
async def test_admin_can_flood_a_point_without_any_marks(db_session):
    aid = await make_point(db_session)
    assert await wm.set_state_admin(db_session, aid, "flooded", admin_id=5, now=NOW)
    assert (await row(db_session, aid)).state == "flooded" and await events(db_session, aid) == 1


@pytest.mark.asyncio
async def test_confirmed_flooded_decays_after_72h_without_marks_but_pending_never_auto_floods(db_session):
    aid = await make_point(db_session)
    await wm.set_state_source(db_session, aid, "flooded", now=NOW - timedelta(days=8))
    await wm.recompute_stale(db_session, NOW)
    assert (await row(db_session, aid)).state == "stale"
    b = await make_point(db_session, name="B")
    await flooded_marks(db_session, b, 4, ago_h=1)
    await wm.recompute_stale(db_session, NOW + timedelta(days=6))  # неделя без админа
    assert (await row(db_session, b)).state == "waiting" and await events(db_session, b) == 0


@pytest.mark.asyncio
async def test_not_flooded_pair_can_cancel_pending_without_admin(db_session):
    aid = await make_point(db_session)
    await flooded_marks(db_session, aid, 2, ago_h=10)
    for who in (2001, 2002):
        await wm.record_mark(db_session, arena_id=aid, kind="ice", value="not_flooded", source="telegram",
                             actor=f"tg:{who}", telegram_id=who, now=NOW)
    # оба порога сразу — спор, а не «залит»
    state = await row(db_session, aid)
    assert state.state == "waiting" and not state.pending_confirm
    assert await open_items(db_session, aid, "dispute") == 1


@pytest.mark.asyncio
async def test_queue_puts_confirm_flood_above_disputes(db_session):
    a = await make_point(db_session, name="A")
    b = await make_point(db_session, name="B")
    await db_session.execute(text("INSERT INTO seasonal_moderation_items (kind, arena_id) VALUES ('dispute', :a)"), {"a": a})
    await flooded_marks(db_session, b, 2)
    first = (await wq.next_items(db_session, 2))[0]
    assert first["kind"] == "confirm_flood" and first["arena_id"] == b
    card = await wa.confirm_flood_card(db_session, b, NOW)
    assert card["people"] == 2 and card["by_source"] == {"telegram": 2} and card["last_at"] is not None


@pytest.mark.asyncio
async def test_list_api_shows_pending_line_not_flooded(db_session):
    aid = await make_point(db_session)
    await flooded_marks(db_session, aid, 2)
    cid = (await db_session.execute(text("SELECT city_id FROM arenas WHERE id=:a"), {"a": aid})).scalar_one()
    item = (await list_points(db_session, cid, now=NOW))["items"][0]
    assert item["state"] == "waiting" and item["pending"] and item["pending_people"] == 2
