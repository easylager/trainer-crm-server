"""TASK-334: гонка месяца — окно таблиц, короны, финал месяца, итог на главной."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.hockey_game import make_pick, race_window, score_finished_matches, standings
from src.application.hockey_leagues import create_league, join_by_code, league_table
from src.application.hockey_matches import set_manual_result
from src.application.hockey_races import (
    close_due_races,
    crown_counts,
    ensure_month_race,
    ensure_races,
    fresh_race_result,
    league_crown_wall,
    mark_calendar_synced,
    mark_race_seen,
    race_final_match_id,
    race_winners,
)
from src.ingestion.hockey_sources import MINSK_TZ

NOV = datetime(2026, 11, 10, 12, 0, tzinfo=MINSK_TZ)
DEC_1 = datetime(2026, 12, 1, 12, 0, tzinfo=MINSK_TZ)
SASHA, KATYA, LESHA = 9340001, 9340002, 9340003


async def _match(db_session, mid: str, starts_at: datetime, *, home: str = "Динамо-Минск") -> int:
    return (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
                VALUES ('hcdinamo', :mid, :home, 'Барыс', :starts_at) RETURNING id
                """),
            {"mid": mid, "home": home, "starts_at": starts_at},
        )
    ).scalar_one()


async def _play(db_session, starts_at: datetime, picks: dict[int, tuple[int, int]], *, mid: str, score=(3, 1)) -> int:
    match_id = await _match(db_session, mid, starts_at)
    for player, (h, a) in picks.items():
        await make_pick(
            db_session,
            player_key=player,
            display_name={SASHA: "Саша", KATYA: "Катя", LESHA: "Лёша"}[player],
            match_id=match_id,
            home_score=h,
            away_score=a,
            now=starts_at - timedelta(hours=2),
        )
    await set_manual_result(
        db_session,
        match_id,
        home_score=score[0],
        away_score=score[1],
        decided_in="regulation",
        now=starts_at + timedelta(hours=3),
    )
    await score_finished_matches(db_session, now=starts_at + timedelta(hours=3))
    return match_id


def test_race_window_is_minsk_month_after_first_race_and_season_before() -> None:
    w = race_window(datetime(2026, 11, 30, 22, 30, tzinfo=timezone.utc))  # 1 декабря 01:30 по Минску
    assert w.monthly and w.title == "декабрь"
    assert w.since == datetime(2026, 12, 1, tzinfo=MINSK_TZ)
    assert w.until == datetime(2027, 1, 1, tzinfo=MINSK_TZ)
    before = race_window(datetime(2026, 10, 26, tzinfo=MINSK_TZ))
    assert not before.monthly and before.until == datetime(2026, 11, 1, tzinfo=MINSK_TZ)


@pytest.mark.asyncio
async def test_tables_start_from_zero_each_month(db_session) -> None:
    await _play(db_session, datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ), {SASHA: (3, 1)}, mid="r-nov")
    assert [(s.player_key, s.points) for s in await standings(db_session, now=NOV)] == [(SASHA, 50)]
    assert await standings(db_session, now=DEC_1) == []


@pytest.mark.asyncio
async def test_close_awards_crowns_once_with_ties_and_league_rules(db_session) -> None:
    league = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="ОХМ")
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=league.invite_code)
    await db_session.execute(
        text("UPDATE hockey_league_members SET joined_at = :at WHERE league_id = :l"),
        {"at": datetime(2026, 11, 1, tzinfo=MINSK_TZ), "l": league.id},
    )
    solo = await create_league(db_session, owner_key=LESHA, owner_name="Лёша", name="Один")
    race = await ensure_month_race(db_session, now=NOV)
    # Саша и Катя — по 50, Лёша — 20: в общей таблице ничья на первом месте.
    await _play(
        db_session,
        datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ),
        {SASHA: (3, 1), KATYA: (3, 1), LESHA: (2, 1)},
        mid="r1",
    )
    # Матч ещё не сыгран — гонка не закрывается даже после конца месяца.
    pending = await _match(db_session, "r2", datetime(2026, 11, 30, 19, 0, tzinfo=MINSK_TZ))
    assert await close_due_races(db_session, now=DEC_1) == []
    await set_manual_result(db_session, pending, home_score=2, away_score=0, decided_in="regulation", now=DEC_1)
    await score_finished_matches(db_session, now=DEC_1)

    assert await close_due_races(db_session, now=DEC_1) == [race.id]
    assert await close_due_races(db_session, now=DEC_1 + timedelta(hours=1)) == []
    assert {w["player_key"] for w in await race_winners(db_session, race_id=race.id, league_id=None)} == {SASHA, KATYA}
    assert {w["player_key"] for w in await race_winners(db_session, race_id=race.id, league_id=league.id)} == {
        SASHA,
        KATYA,
    }
    assert await race_winners(db_session, race_id=race.id, league_id=solo.id) == []
    assert (await crown_counts(db_session, league_id=league.id))[SASHA] == 1
    # Пересчёт очков корону не трогает.
    await db_session.execute(text("UPDATE hockey_picks SET points = 0 WHERE player_key = :p"), {"p": KATYA})
    assert (await crown_counts(db_session, league_id=None))[KATYA] == 1


@pytest.mark.asyncio
async def test_no_crown_with_zero_points(db_session) -> None:
    race = await ensure_month_race(db_session, now=NOV)
    await _play(db_session, datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ), {SASHA: (1, 4)}, mid="r0", score=(3, 1))
    assert await close_due_races(db_session, now=DEC_1) == [race.id]
    assert await race_winners(db_session, race_id=race.id, league_id=None) == []


@pytest.mark.asyncio
async def test_final_is_named_only_after_calendar_sync_and_skips_cancelled(db_session) -> None:
    race = await ensure_month_race(db_session, now=NOV)
    last = await _match(db_session, "f1", datetime(2026, 11, 28, 19, 0, tzinfo=MINSK_TZ))
    cancelled = await _match(db_session, "f2", datetime(2026, 11, 30, 19, 0, tzinfo=MINSK_TZ))
    await db_session.execute(text("UPDATE hockey_matches SET status = 'cancelled' WHERE id = :id"), {"id": cancelled})
    assert await race_final_match_id(db_session, race) is None
    await mark_calendar_synced(db_session, now=NOV)
    race = await ensure_month_race(db_session, now=NOV)
    assert await race_final_match_id(db_session, race) == last


@pytest.mark.asyncio
async def test_result_shows_a_day_then_after_seen_hides(db_session) -> None:
    race = await ensure_month_race(db_session, now=NOV)
    await _play(db_session, datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ), {SASHA: (3, 1)}, mid="s1")
    await close_due_races(db_session, now=DEC_1)
    assert (await fresh_race_result(db_session, player_key=SASHA, now=DEC_1)).id == race.id
    assert await fresh_race_result(db_session, player_key=KATYA, now=DEC_1) is None
    assert await fresh_race_result(db_session, player_key=SASHA, now=DEC_1 + timedelta(hours=25)) is None
    await mark_race_seen(db_session, player_key=SASHA, race_id=race.id, now=DEC_1)
    assert await fresh_race_result(db_session, player_key=SASHA, now=DEC_1) is None


@pytest.mark.asyncio
async def test_ensure_races_creates_previous_month_and_wall(db_session) -> None:
    league = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="ОХМ")
    current = await ensure_races(db_session, now=DEC_1)
    assert current.title == "декабрь"
    wall = await league_crown_wall(db_session, league_id=league.id, now=DEC_1)
    assert [w["title"] for w in wall] == ["ноябрь", "декабрь", "январь", "февраль", "март", "апрель"]
    assert [w["state"] for w in wall][:3] == ["counting", "running", "ahead"]
    assert await ensure_month_race(db_session, now=datetime(2026, 10, 20, tzinfo=MINSK_TZ)) is None


@pytest.mark.asyncio
async def test_league_table_in_month_counts_after_joining(db_session) -> None:
    league = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="ОХМ")
    await db_session.execute(
        text("UPDATE hockey_league_members SET joined_at = :at WHERE league_id = :l"),
        {"at": datetime(2026, 10, 1, tzinfo=MINSK_TZ), "l": league.id},
    )
    await _play(db_session, datetime(2026, 10, 30, 19, 0, tzinfo=MINSK_TZ), {SASHA: (3, 1)}, mid="t-oct")
    await _play(db_session, datetime(2026, 11, 5, 19, 0, tzinfo=MINSK_TZ), {SASHA: (2, 1)}, mid="t-nov")
    rows = await league_table(db_session, league_id=league.id, player_key=SASHA, now=NOV)
    # 2:1 при итоге 3:1 — победитель и шайбы гостей: 30; октябрьские 50 в ноябрь не попадают.
    assert [(r.player_key, r.points) for r in rows] == [(SASHA, 30)]
