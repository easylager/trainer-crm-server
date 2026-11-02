"""TASK-335: ×2 на матч месяца — поставить, перенести, закрепить на старте; двойные очки в таблицах."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from src.application.hockey_game import (
    DoubleUnavailable,
    PicksClosed,
    make_pick,
    my_double,
    score_finished_matches,
    set_double,
    standings,
)
from src.application.hockey_matches import set_manual_result
from src.ingestion.hockey_sources import MINSK_TZ

NOV = datetime(2026, 11, 10, 12, 0, tzinfo=MINSK_TZ)
SASHA, KATYA = 9350001, 9350002


async def _match(db_session, mid: str, starts_at: datetime) -> int:
    return (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
                VALUES ('hcdinamo', :mid, 'Динамо-Минск', 'Барыс', :starts_at) RETURNING id
                """),
            {"mid": mid, "starts_at": starts_at},
        )
    ).scalar_one()


async def _pick(db_session, match_id: int, player: int, **kw) -> None:
    await make_pick(db_session, player_key=player, display_name="x", match_id=match_id, now=NOV, **kw)


@pytest.mark.asyncio
async def test_trump_needs_a_pick_and_works_in_any_week(db_session) -> None:
    october = await _match(db_session, "d-oct", datetime(2026, 10, 30, 19, 0, tzinfo=MINSK_TZ))
    oct_now = datetime(2026, 10, 26, tzinfo=MINSK_TZ)
    await make_pick(db_session, player_key=SASHA, display_name="x", match_id=october, side="home", now=oct_now)
    assert await set_double(db_session, player_key=SASHA, match_id=october, on=True, now=oct_now) == october
    nov = await _match(db_session, "d-nov", datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ))
    with pytest.raises(DoubleUnavailable) as no_pick:
        await set_double(db_session, player_key=SASHA, match_id=nov, on=True, now=NOV)
    assert no_pick.value.reason == "no_pick"


@pytest.mark.asyncio
async def test_trump_one_per_week_moves_until_start_then_locks(db_session) -> None:
    # Пн-вс по Минску: 16-22 ноября — одна неделя, 28 ноября — следующая, 2 декабря — третья.
    first = await _match(db_session, "d1", datetime(2026, 11, 17, 19, 0, tzinfo=MINSK_TZ))
    second = await _match(db_session, "d2", datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ))
    next_week = await _match(db_session, "d3", datetime(2026, 11, 28, 19, 0, tzinfo=MINSK_TZ))
    for m in (first, second, next_week):
        await _pick(db_session, m, SASHA, side="home")
    assert await set_double(db_session, player_key=SASHA, match_id=first, on=True, now=NOV) == first
    assert await set_double(db_session, player_key=SASHA, match_id=second, on=True, now=NOV) == second
    doubled = (await db_session.execute(text("SELECT match_id FROM hockey_picks WHERE doubled"))).scalars().all()
    assert doubled == [second]
    # Другая неделя — свой козырь.
    assert await set_double(db_session, player_key=SASHA, match_id=next_week, on=True, now=NOV) == next_week
    after_start = datetime(2026, 11, 20, 19, 5, tzinfo=MINSK_TZ)
    cur = await my_double(db_session, player_key=SASHA, now=after_start)
    assert (cur["match_id"], cur["locked"]) == (second, True)
    with pytest.raises(PicksClosed):
        await set_double(db_session, player_key=SASHA, match_id=second, on=False, now=after_start)
    late = await _match(db_session, "d4", datetime(2026, 11, 22, 19, 0, tzinfo=MINSK_TZ))
    await make_pick(db_session, player_key=SASHA, display_name="x", match_id=late, side="home", now=after_start)
    with pytest.raises(DoubleUnavailable) as used:
        await set_double(db_session, player_key=SASHA, match_id=late, on=True, now=after_start)
    assert used.value.reason == "used"


@pytest.mark.asyncio
async def test_trump_returns_on_cancel_and_technical_defeat(db_session) -> None:
    from src.application.hockey_matches import set_manual_result as manual

    m = await _match(db_session, "c1", datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ))
    other = await _match(db_session, "c2", datetime(2026, 11, 21, 19, 0, tzinfo=MINSK_TZ))
    for x in (m, other):
        await _pick(db_session, x, SASHA, side="home")
    await set_double(db_session, player_key=SASHA, match_id=m, on=True, now=NOV)
    # Техническое поражение = отмена: без очков, козырь свободен.
    await manual(db_session, m, home_score=5, away_score=0, decided_in="technical", now=NOV)
    await score_finished_matches(db_session, now=NOV)
    row = (
        await db_session.execute(
            text("SELECT doubled, trump_week, points FROM hockey_picks WHERE match_id = :m"), {"m": m}
        )
    ).one()
    assert (row.doubled, row.trump_week, row.points) == (False, None, None)
    assert await set_double(db_session, player_key=SASHA, match_id=other, on=True, now=NOV) == other


@pytest.mark.asyncio
async def test_trump_follows_a_moved_match_or_returns_on_collision(db_session) -> None:
    from src.application.hockey_game import on_match_moved

    sun = await _match(db_session, "m1", datetime(2026, 11, 22, 19, 0, tzinfo=MINSK_TZ))
    mon_busy = await _match(db_session, "m2", datetime(2026, 11, 24, 19, 0, tzinfo=MINSK_TZ))
    for x in (sun, mon_busy):
        await _pick(db_session, x, SASHA, side="home")
        await _pick(db_session, x, KATYA, side="home")
    await set_double(db_session, player_key=SASHA, match_id=sun, on=True, now=NOV)
    await set_double(db_session, player_key=KATYA, match_id=sun, on=True, now=NOV)
    await set_double(
        db_session, player_key=KATYA, match_id=mon_busy, on=True, now=NOV
    )  # у Кати уже козырь на следующей неделе? нет — переехал
    # Саша: перенос воскресенья на вторник следующей недели — козырь едет за матчем.
    new = datetime(2026, 11, 24, 17, 0, tzinfo=MINSK_TZ)
    await db_session.execute(text("UPDATE hockey_matches SET starts_at = :t WHERE id = :m"), {"t": new, "m": sun})
    res = await on_match_moved(db_session, match_id=sun, starts_at=new)
    assert res["released"] == [] or KATYA in res["released"]
    wk = (
        await db_session.execute(
            text("SELECT trump_week FROM hockey_picks WHERE match_id = :m AND player_key = :p"), {"m": sun, "p": SASHA}
        )
    ).scalar_one()
    assert wk.isoformat() == "2026-11-23"


@pytest.mark.asyncio
async def test_pick_closes_a_minute_before_start_and_late_pick_is_voided_on_move(db_session) -> None:
    from src.application.hockey_game import on_match_moved

    starts = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    m = await _match(db_session, "p1", starts)
    with pytest.raises(PicksClosed):
        await make_pick(
            db_session, player_key=SASHA, display_name="x", match_id=m, side="home", now=starts - timedelta(seconds=59)
        )
    await make_pick(
        db_session, player_key=SASHA, display_name="x", match_id=m, side="home", now=starts - timedelta(minutes=5)
    )
    # Перенесли на 17:00 того же дня, ход сделан в 18:55 — после нового срока: аннулируется.
    earlier = datetime(2026, 11, 20, 17, 0, tzinfo=MINSK_TZ)
    await db_session.execute(
        text("UPDATE hockey_picks SET picked_at = :t WHERE match_id = :m"), {"t": starts - timedelta(minutes=5), "m": m}
    )
    res = await on_match_moved(db_session, match_id=m, starts_at=earlier)
    assert res["voided"] == [SASHA]
    assert (
        await db_session.execute(text("SELECT count(*) FROM hockey_picks WHERE match_id = :m"), {"m": m})
    ).scalar_one() == 0


@pytest.mark.asyncio
async def test_two_trumps_in_one_week_are_rejected_by_the_index(db_session) -> None:
    from sqlalchemy.exc import IntegrityError

    a = await _match(db_session, "u1", datetime(2026, 11, 17, 19, 0, tzinfo=MINSK_TZ))
    b = await _match(db_session, "u2", datetime(2026, 11, 18, 19, 0, tzinfo=MINSK_TZ))
    for x in (a, b):
        await _pick(db_session, x, SASHA, side="home")
    await set_double(db_session, player_key=SASHA, match_id=a, on=True, now=NOV)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE hockey_picks SET doubled = true, trump_week = '2026-11-16' WHERE match_id = :m"), {"m": b}
            )


@pytest.mark.asyncio
async def test_doubled_exact_counts_as_100_and_still_exact(db_session) -> None:
    m = await _match(db_session, "d5", datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ))
    await _pick(db_session, m, SASHA, home_score=3, away_score=1)
    await _pick(db_session, m, KATYA, home_score=3, away_score=1)
    await set_double(db_session, player_key=SASHA, match_id=m, on=True, now=NOV)
    done = datetime(2026, 11, 20, 22, 0, tzinfo=MINSK_TZ)
    await set_manual_result(db_session, m, home_score=3, away_score=1, decided_in="regulation", now=done)
    await score_finished_matches(db_session, now=done)
    rows = {s.player_key: s for s in await standings(db_session, now=done + timedelta(days=1))}
    assert (rows[SASHA].points, rows[SASHA].exact, rows[SASHA].rank) == (100, 1, 1)
    assert (rows[KATYA].points, rows[KATYA].exact) == (50, 1)


@pytest.mark.asyncio
async def test_friends_scores_open_at_kickoff_only_for_my_leagues(db_session) -> None:
    from src.application.hockey_leagues import create_league, friends_moves, join_by_code

    stranger = 9350009
    league = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="ОХМ")
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=league.invite_code)
    starts = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    m = await _match(db_session, "f1", starts)
    await _pick(db_session, m, SASHA, side="home")
    await _pick(db_session, m, KATYA, home_score=3, away_score=1)
    await _pick(db_session, m, stranger, side="away")
    await set_double(db_session, player_key=KATYA, match_id=m, on=True, now=NOV)

    assert await friends_moves(db_session, player_key=SASHA, match_ids=[m], now=starts - timedelta(minutes=1)) == {
        m: []
    }
    live = await friends_moves(db_session, player_key=SASHA, match_ids=[m], now=starts + timedelta(minutes=5))
    assert live[m] == [
        {"display_name": "x", "side": "home", "home_score": 3, "away_score": 1, "doubled": True, "points": None}
    ]
    done = starts + timedelta(hours=3)
    await set_manual_result(db_session, m, home_score=3, away_score=1, decided_in="regulation", now=done)
    await score_finished_matches(db_session, now=done)
    after = await friends_moves(db_session, player_key=SASHA, match_ids=[m], now=done)
    assert after[m][0]["points"] == 100


@pytest.mark.asyncio
async def test_trump_closes_with_the_picks_a_minute_before_start(db_session) -> None:
    """Козырь ставится, снимается и переносится ровно пока открыт ход: граница та же, 60 секунд до старта."""
    start = datetime(2026, 11, 17, 19, 0, tzinfo=MINSK_TZ)
    first = await _match(db_session, "b1", start)
    second = await _match(db_session, "b2", datetime(2026, 11, 19, 19, 0, tzinfo=MINSK_TZ))
    for m in (first, second):
        await _pick(db_session, m, SASHA, side="home")
    open_at = start - timedelta(seconds=61)
    closed_at = start - timedelta(seconds=59)

    # За 61 с — ставится; за 59 с — уже нет.
    assert await set_double(db_session, player_key=SASHA, match_id=first, on=True, now=open_at) == first
    await _pick(db_session, first, KATYA, side="home")
    with pytest.raises(PicksClosed):
        await set_double(db_session, player_key=KATYA, match_id=first, on=True, now=closed_at)

    # Закрепление видно клиенту: за 61 с не закреплён, за 59 с закреплён.
    assert (await my_double(db_session, player_key=SASHA, now=open_at))["locked"] is False
    assert (await my_double(db_session, player_key=SASHA, now=closed_at))["locked"] is True

    # За 59 с козырь с этого матча не снять и не перенести.
    with pytest.raises(PicksClosed):
        await set_double(db_session, player_key=SASHA, match_id=first, on=False, now=closed_at)
    with pytest.raises(DoubleUnavailable) as locked:
        await set_double(db_session, player_key=SASHA, match_id=second, on=True, now=closed_at)
    assert locked.value.reason == "used"
    doubled = (await db_session.execute(text("SELECT match_id FROM hockey_picks WHERE doubled"))).scalars().all()
    assert doubled == [first]

    # За 61 с перенос ещё работает, а снять козырь можно.
    assert await set_double(db_session, player_key=SASHA, match_id=second, on=True, now=open_at) == second
    assert await set_double(db_session, player_key=SASHA, match_id=second, on=False, now=open_at) is None
