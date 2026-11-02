"""Отметки, статус, споры, «точки больше нет» (TASK-343, края из каталога S*, W*, X*)."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from src.application import winter_marks as wm
from tests.application.winter_helpers import NOW, SEASON, make_client, make_point


async def state_of(db, aid):
    return (await db.execute(text("SELECT state FROM seasonal_rink_seasons WHERE arena_id=:a"), {"a": aid})).scalar_one()


async def mark(db, aid, value, source, who, *, kind="ice", ago_h=0.0, **kw):
    actor = f"tg:{who}" if source != "site" else f"site:{who}"
    return await wm.record_mark(
        db, arena_id=aid, kind=kind, value=value, source=source, actor=actor,
        telegram_id=who if source != "site" else None, now=NOW - timedelta(hours=ago_h), **kw,
    )


@pytest.mark.asyncio
async def test_site_alone_never_floods(db_session):
    aid = await make_point(db_session)
    for i in range(6):
        await mark(db_session, aid, "flooded", "site", f"d{i}")
    assert await state_of(db_session, aid) == "waiting"


@pytest.mark.asyncio
async def test_telegram_pair_only_makes_pending_and_no_event(db_session):
    aid = await make_point(db_session)
    r1 = await mark(db_session, aid, "flooded", "telegram", 1)
    assert not r1.state_changed and not r1.pending_confirm
    r2 = await mark(db_session, aid, "flooded", "miniapp", 2)
    assert r2.state == "waiting" and r2.pending_confirm and r2.flood_event_id is None
    n = (await db_session.execute(text("SELECT count(*) FROM winter_flood_events WHERE arena_id=:a"), {"a": aid})).scalar_one()
    assert n == 0


@pytest.mark.asyncio
async def test_not_flooded_pair_returns_to_waiting(db_session):
    aid = await make_point(db_session, state="flooded", state_source="engine")
    await mark(db_session, aid, "not_flooded", "telegram", 1, ago_h=1)
    r = await mark(db_session, aid, "not_flooded", "telegram", 2)
    assert r.state == "waiting"


@pytest.mark.asyncio
async def test_dispute_goes_to_admin_queue_and_clears(db_session):
    aid = await make_point(db_session)
    await mark(db_session, aid, "flooded", "telegram", 1, ago_h=10)
    await mark(db_session, aid, "flooded", "telegram", 2, ago_h=9)
    await mark(db_session, aid, "not_flooded", "telegram", 3, ago_h=2)
    r = await mark(db_session, aid, "not_flooded", "telegram", 4, ago_h=1)
    assert r.dispute
    q = (await db_session.execute(text("SELECT count(*) FROM seasonal_moderation_items WHERE kind='dispute' AND status='open' AND arena_id=:a"), {"a": aid})).scalar_one()
    assert q == 1
    # один из спорщиков передумал -> спор снят, карточка закрыта сама
    r = await mark(db_session, aid, "flooded", "telegram", 4)
    assert not r.dispute
    q = (await db_session.execute(text("SELECT count(*) FROM seasonal_moderation_items WHERE kind='dispute' AND status='open' AND arena_id=:a"), {"a": aid})).scalar_one()
    assert q == 0


@pytest.mark.asyncio
async def test_site_rate_limit_three_hours_per_point(db_session):
    aid = await make_point(db_session)
    await mark(db_session, aid, "flooded", "site", "dev", ago_h=2.9)
    with pytest.raises(wm.MarkError) as e:
        await mark(db_session, aid, "many", "site", "dev", kind="crowd")
    assert e.value.code == "rate_limited" and e.value.retry_after_sec > 0


@pytest.mark.asyncio
async def test_site_daily_and_burst_limits(db_session):
    points = [await make_point(db_session, name=f"P{i}") for i in range(12)]
    for i, p in enumerate(points[:3]):
        await mark(db_session, p, "flooded", "site", "bot", ago_h=0.5 + i)  # разнесены по часам
    # 4 точки за минуту
    for p in points[3:6]:
        await mark(db_session, p, "flooded", "site", "burst")
    with pytest.raises(wm.MarkError) as e:
        await mark(db_session, points[6], "flooded", "site", "burst")
    assert e.value.code == "rate_limited"
    # 10 за сутки
    for i, p in enumerate(points[:10]):
        try:
            await mark(db_session, p, "flooded", "site", "daily", ago_h=20 - i * 2)
        except wm.MarkError:
            pass
    with pytest.raises(wm.MarkError):
        await mark(db_session, points[11], "flooded", "site", "daily")


@pytest.mark.asyncio
async def test_idempotency_key_returns_same_result_without_second_mark(db_session):
    aid = await make_point(db_session)
    await mark(db_session, aid, "flooded", "telegram", 1, idem_key="u-1")
    again = await mark(db_session, aid, "flooded", "telegram", 1, idem_key="u-1")
    assert again.duplicate
    n = (await db_session.execute(text("SELECT count(*) FROM seasonal_rink_marks WHERE arena_id=:a"), {"a": aid})).scalar_one()
    assert n == 1


@pytest.mark.asyncio
async def test_hidden_or_inactive_points_reject_marks(db_session):
    hidden = await make_point(db_session, state="hidden")
    with pytest.raises(wm.MarkError) as e:
        await mark(db_session, hidden, "flooded", "telegram", 1)
    assert e.value.code == "not_found"
    dead = await make_point(db_session, name="Снесён")
    await db_session.execute(text("UPDATE arenas SET is_active=false WHERE id=:a"), {"a": dead})
    with pytest.raises(wm.MarkError):
        await mark(db_session, dead, "flooded", "telegram", 1)


@pytest.mark.asyncio
async def test_bad_values_and_sources_rejected(db_session):
    aid = await make_point(db_session)
    with pytest.raises(wm.MarkError):
        await mark(db_session, aid, "frozen", "telegram", 1)
    with pytest.raises(wm.MarkError):
        await mark(db_session, aid, "flooded", "carrier-pigeon", 1)


@pytest.mark.asyncio
async def test_bad_ice_is_flag_and_crowd_lives_two_hours(db_session):
    aid = await make_point(db_session)
    r = await mark(db_session, aid, "bad", "telegram", 1)
    assert r.quality == "bad" and r.state == "waiting"
    await mark(db_session, aid, "many", "telegram", 2, kind="crowd", ago_h=3)
    n = (await db_session.execute(text("SELECT count(*) FROM seasonal_rink_marks WHERE arena_id=:a AND kind='crowd'"), {"a": aid})).scalar_one()
    assert n == 1  # хранится, но в статусе не участвует (виден 2 ч — на чтении)


@pytest.mark.asyncio
async def test_stale_after_72h_without_marks(db_session):
    aid = await make_point(db_session, state="flooded", state_source="parser", state_at=NOW - timedelta(days=8))
    assert await wm.recompute_stale(db_session, NOW) == 1
    assert await state_of(db_session, aid) == "stale"


@pytest.mark.asyncio
async def test_admin_flooded_holds_for_seven_days_and_makes_event(db_session):
    aid = await make_point(db_session)
    assert await wm.set_state_admin(db_session, aid, "flooded", admin_id=1, now=NOW - timedelta(days=5))
    n = (await db_session.execute(text("SELECT count(*) FROM winter_flood_events WHERE arena_id=:a"), {"a": aid})).scalar_one()
    assert n == 1
    await wm.recompute_stale(db_session, NOW)
    assert await state_of(db_session, aid) == "flooded"  # 5 суток < 7
    await wm.recompute_stale(db_session, NOW + timedelta(days=3))
    assert await state_of(db_session, aid) == "stale"


@pytest.mark.asyncio
async def test_gone_signal_rules(db_session):
    aid = await make_point(db_session)
    assert (await wm.signal_gone(db_session, arena_id=aid, telegram_id=None, now=NOW)).reason == "login_required"
    await make_client(db_session, 900, age_days=2)
    assert (await wm.signal_gone(db_session, arena_id=aid, telegram_id=900, now=NOW)).reason == "account_too_new"
    for t in (901, 902):
        await make_client(db_session, t)
    await wm.signal_gone(db_session, arena_id=aid, telegram_id=901, now=NOW)
    await wm.signal_gone(db_session, arena_id=aid, telegram_id=901, now=NOW)  # повтор того же человека не считается
    r = await wm.signal_gone(db_session, arena_id=aid, telegram_id=902, now=NOW)
    assert r.queued is None
    await make_client(db_session, 903)
    r = await wm.signal_gone(db_session, arena_id=aid, telegram_id=903, now=NOW)
    assert r.queued == "gone"
    row = (await db_session.execute(text("SELECT state, doubtful FROM seasonal_rink_seasons WHERE arena_id=:a"), {"a": aid})).one()
    assert row.state == "waiting" and row.doubtful  # не скрыта
    q = (await db_session.execute(text("SELECT count(*) FROM seasonal_moderation_items WHERE kind='gone' AND status='open'"))).scalar_one()
    assert q == 1


@pytest.mark.asyncio
async def test_gone_on_live_flooded_point_is_a_dispute_not_a_flag(db_session):
    aid = await make_point(db_session, state="flooded", state_source="engine")
    for t in (1, 2, 3):
        await make_client(db_session, t)
        r = await wm.signal_gone(db_session, arena_id=aid, telegram_id=t, now=NOW)
    assert r.queued == "dispute"
    assert not (await db_session.execute(text("SELECT doubtful FROM seasonal_rink_seasons WHERE arena_id=:a"), {"a": aid})).scalar_one()


@pytest.mark.asyncio
async def test_gone_resolution_keep_resets_counter_hide_hides(db_session):
    aid = await make_point(db_session)
    for t in (1, 2, 3):
        await make_client(db_session, t)
        await wm.signal_gone(db_session, arena_id=aid, telegram_id=t, now=NOW)
    await wm.resolve_gone(db_session, aid, point_exists=True, admin_id=7, now=NOW)
    assert not (await db_session.execute(text("SELECT doubtful FROM seasonal_rink_seasons WHERE arena_id=:a"), {"a": aid})).scalar_one()
    r = await wm.signal_gone(db_session, arena_id=aid, telegram_id=1, now=NOW + timedelta(hours=1))
    assert r.queued is None  # старые сигналы не воскресают
    await wm.resolve_gone(db_session, aid, point_exists=False, admin_id=7, now=NOW)
    assert await state_of(db_session, aid) == "hidden"


@pytest.mark.asyncio
async def test_admin_confirmed_point_is_shielded_for_30_days(db_session):
    aid = await make_point(db_session)
    await wm.set_state_admin(db_session, aid, "waiting", admin_id=1, now=NOW - timedelta(days=10))
    for t in (1, 2, 3):
        await make_client(db_session, t)
        r = await wm.signal_gone(db_session, arena_id=aid, telegram_id=t, now=NOW)
    assert r.queued == "dispute"
