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
async def test_double_needs_a_pick_and_a_month_race(db_session) -> None:
    october = await _match(db_session, "d-oct", datetime(2026, 10, 30, 19, 0, tzinfo=MINSK_TZ))
    await make_pick(
        db_session,
        player_key=SASHA,
        display_name="x",
        match_id=october,
        side="home",
        now=datetime(2026, 10, 26, tzinfo=MINSK_TZ),
    )
    with pytest.raises(DoubleUnavailable) as no_race:
        await set_double(
            db_session, player_key=SASHA, match_id=october, on=True, now=datetime(2026, 10, 26, tzinfo=MINSK_TZ)
        )
    assert no_race.value.reason == "no_race"
    nov = await _match(db_session, "d-nov", datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ))
    with pytest.raises(DoubleUnavailable) as no_pick:
        await set_double(db_session, player_key=SASHA, match_id=nov, on=True, now=NOV)
    assert no_pick.value.reason == "no_pick"


@pytest.mark.asyncio
async def test_double_moves_until_start_then_locks(db_session) -> None:
    first = await _match(db_session, "d1", datetime(2026, 11, 15, 19, 0, tzinfo=MINSK_TZ))
    second = await _match(db_session, "d2", datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ))
    december = await _match(db_session, "d3", datetime(2026, 12, 2, 19, 0, tzinfo=MINSK_TZ))
    for m in (first, second, december):
        await _pick(db_session, m, SASHA, side="home")
    assert await set_double(db_session, player_key=SASHA, match_id=first, on=True, now=NOV) == first
    assert await set_double(db_session, player_key=SASHA, match_id=second, on=True, now=NOV) == second
    assert await my_double(db_session, player_key=SASHA, now=NOV) == {"match_id": second, "locked": False}
    # Другой месяц — свой ×2, ноябрьский не мешает.
    assert await set_double(db_session, player_key=SASHA, match_id=december, on=True, now=NOV) == december
    after_start = datetime(2026, 11, 20, 19, 5, tzinfo=MINSK_TZ)
    assert await my_double(db_session, player_key=SASHA, now=after_start) == {"match_id": second, "locked": True}
    with pytest.raises(PicksClosed):
        await set_double(db_session, player_key=SASHA, match_id=second, on=False, now=after_start)
    late = await _match(db_session, "d4", datetime(2026, 11, 28, 19, 0, tzinfo=MINSK_TZ))
    await make_pick(db_session, player_key=SASHA, display_name="x", match_id=late, side="home", now=after_start)
    with pytest.raises(DoubleUnavailable) as used:
        await set_double(db_session, player_key=SASHA, match_id=late, on=True, now=after_start)
    assert used.value.reason == "used"


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
