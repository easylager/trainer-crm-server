"""TASK-299: строка на главной — итог, ближайший матч, три пропуска, место в лиге."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from src.application.hockey_game import make_pick, score_finished_matches
from src.application.hockey_hub import choose_mode, hub_card, mark_result_seen, suppress_upcoming
from src.application.hockey_leagues import create_league
from src.application.hockey_matches import set_manual_result
from src.ingestion.hockey_sources import MINSK_TZ

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=MINSK_TZ)
SASHA, KATYA = 9102991, 9102992


def test_choose_mode_result_beats_upcoming_and_streak_hides_only_before() -> None:
    assert choose_mode(unseen_result=True, upcoming=True, suppress=True) == "result"
    assert choose_mode(unseen_result=False, upcoming=True, suppress=False) == "before"
    assert choose_mode(unseen_result=False, upcoming=True, suppress=True) is None
    assert choose_mode(unseen_result=False, upcoming=False, suppress=False) is None
    assert suppress_upcoming(had_pick=False, last_finals_picked=[False, False, False]) is False
    assert suppress_upcoming(had_pick=True, last_finals_picked=[False, False, False]) is True
    assert suppress_upcoming(had_pick=True, last_finals_picked=[False, False]) is False
    assert suppress_upcoming(had_pick=True, last_finals_picked=[True, False, False]) is False


async def _match(db_session, mid: str, starts_at: datetime, *, home: str = "Динамо-Минск", away: str = "Барыс") -> int:
    return (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
                VALUES ('hcdinamo', :mid, :home, :away, :starts_at) RETURNING id
                """),
            {"mid": mid, "home": home, "away": away, "starts_at": starts_at},
        )
    ).scalar_one()


async def _final(db_session, match_id: int, *, at: datetime, home: int = 1, away: int = 4) -> None:
    await set_manual_result(db_session, match_id, home_score=home, away_score=away, decided_in="regulation", now=at)


@pytest.mark.asyncio
async def test_newcomer_sees_upcoming_inside_48h(db_session) -> None:
    await _match(db_session, "hub-soon", NOW + timedelta(hours=10))
    card = await hub_card(db_session, SASHA, now=NOW)
    assert card["mode"] == "before"
    assert card["my_pick"] is None
    assert card["match"]["home"]["short"] == "ДМ"
    assert card["match"]["away"]["short"] == "БР"
    assert card["match"]["open"] is True


@pytest.mark.asyncio
async def test_match_in_49h_is_not_on_the_home_row(db_session) -> None:
    await _match(db_session, "hub-49", NOW + timedelta(hours=49))
    assert (await hub_card(db_session, SASHA, now=NOW))["mode"] is None


@pytest.mark.asyncio
async def test_before_includes_my_pick(db_session) -> None:
    mid = await _match(db_session, "hub-pick", NOW + timedelta(hours=5))
    await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=mid, side="home", now=NOW)
    card = await hub_card(db_session, SASHA, now=NOW)
    assert card["mode"] == "before"
    assert card["my_pick"]["side"] == "home"


@pytest.mark.asyncio
async def test_fresh_result_then_seen_then_stale(db_session) -> None:
    played = await _match(db_session, "hub-played", NOW - timedelta(hours=6))
    nxt = await _match(db_session, "hub-next", NOW + timedelta(hours=20))
    await make_pick(
        db_session, player_key=SASHA, display_name="Саша", match_id=played, side="away", now=NOW - timedelta(hours=8)
    )
    await _final(db_session, played, at=NOW - timedelta(hours=3))
    await score_finished_matches(db_session, now=NOW)
    card = await hub_card(db_session, SASHA, now=NOW)
    assert card["mode"] == "result"
    assert card["points"] == 20
    assert card["match"]["result"] == {"home_score": 1, "away_score": 4, "decided_in": "regulation"}
    assert card["place"] is None

    await mark_result_seen(db_session, player_key=SASHA, match_id=played, now=NOW)
    after = await hub_card(db_session, SASHA, now=NOW)
    assert after["mode"] == "before"
    assert after["match"]["id"] == nxt

    stale = await _match(db_session, "hub-stale", NOW - timedelta(hours=30))
    await make_pick(
        db_session,
        player_key=KATYA,
        display_name="Катя",
        match_id=stale,
        side="home",
        now=NOW - timedelta(hours=40),
    )
    await _final(db_session, stale, at=NOW - timedelta(hours=25))
    await score_finished_matches(db_session, now=NOW)
    katya = await hub_card(db_session, KATYA, now=NOW)
    assert katya["mode"] != "result"


@pytest.mark.asyncio
async def test_seen_with_nothing_upcoming_clears_the_row(db_session) -> None:
    played = await _match(db_session, "hub-only", NOW - timedelta(hours=4))
    await make_pick(
        db_session, player_key=SASHA, display_name="Саша", match_id=played, side="home", now=NOW - timedelta(hours=6)
    )
    await _final(db_session, played, at=NOW - timedelta(hours=2))
    await score_finished_matches(db_session, now=NOW)
    await mark_result_seen(db_session, player_key=SASHA, match_id=played, now=NOW)
    assert (await hub_card(db_session, SASHA, now=NOW))["mode"] is None


@pytest.mark.asyncio
async def test_three_misses_hide_the_upcoming_row(db_session) -> None:
    older = await _match(db_session, "hub-old", NOW - timedelta(days=10))
    await make_pick(
        db_session, player_key=SASHA, display_name="Саша", match_id=older, side="home", now=NOW - timedelta(days=11)
    )
    await _final(db_session, older, at=NOW - timedelta(days=9))
    for index, hours in enumerate((30, 50, 70), start=1):
        missed = await _match(db_session, f"hub-miss-{index}", NOW - timedelta(hours=hours + 3))
        await _final(db_session, missed, at=NOW - timedelta(hours=hours))
    await _match(db_session, "hub-still-soon", NOW + timedelta(hours=8))
    await score_finished_matches(db_session, now=NOW)
    assert (await hub_card(db_session, SASHA, now=NOW))["mode"] is None


@pytest.mark.asyncio
async def test_result_beats_upcoming_match(db_session) -> None:
    played = await _match(db_session, "hub-both-played", NOW - timedelta(hours=5))
    await _match(db_session, "hub-both-next", NOW + timedelta(hours=4))
    await make_pick(
        db_session, player_key=SASHA, display_name="Саша", match_id=played, side="away", now=NOW - timedelta(hours=7)
    )
    await _final(db_session, played, at=NOW - timedelta(hours=3))
    await score_finished_matches(db_session, now=NOW)
    card = await hub_card(db_session, SASHA, now=NOW)
    assert card["mode"] == "result"
    assert card["match"]["id"] == played


@pytest.mark.asyncio
async def test_place_is_the_best_league(db_session) -> None:
    played = await _match(db_session, "hub-league", NOW - timedelta(hours=5), away="Ак Барс")
    await make_pick(
        db_session,
        player_key=SASHA,
        display_name="Саша",
        match_id=played,
        side="away",
        now=NOW - timedelta(hours=7),
    )
    await make_pick(
        db_session,
        player_key=KATYA,
        display_name="Катя",
        match_id=played,
        home_score=1,
        away_score=4,
        now=NOW - timedelta(hours=7),
    )
    await _final(db_session, played, at=NOW - timedelta(hours=3))
    await score_finished_matches(db_session, now=NOW)
    strong = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="ОХМ")
    weak = await create_league(db_session, owner_key=KATYA, owner_name="Катя", name="Двор")
    await db_session.execute(
        text("INSERT INTO hockey_league_members (league_id, player_key) VALUES (:l, :p)"),
        {"l": weak.id, "p": SASHA},
    )
    card = await hub_card(db_session, SASHA, now=NOW)
    assert card["mode"] == "result"
    assert card["points"] == 20
    assert card["place"] == {"league_name": strong.name, "rank": 1}
    assert card["match"]["away"]["short"] == "АБ"


@pytest.mark.asyncio
async def test_pick_on_upcoming_overrides_three_misses(db_session) -> None:
    older = await _match(db_session, "hub-o2", NOW - timedelta(days=10))
    await make_pick(
        db_session, player_key=SASHA, display_name="Саша", match_id=older, side="home", now=NOW - timedelta(days=11)
    )
    await _final(db_session, older, at=NOW - timedelta(days=9))
    for index, hours in enumerate((30, 50, 70), start=1):
        missed = await _match(db_session, f"hub-m2-{index}", NOW - timedelta(hours=hours + 3))
        await _final(db_session, missed, at=NOW - timedelta(hours=hours))
    soon = await _match(db_session, "hub-soon-2", NOW + timedelta(hours=8))
    # Сходил на ближайший матч из Telegram — вернулся, это уже не пропуск.
    await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=soon, side="home", now=NOW)
    await score_finished_matches(db_session, now=NOW)
    card = await hub_card(db_session, SASHA, now=NOW)
    assert card["mode"] == "before" and card["my_pick"]["side"] == "home"
