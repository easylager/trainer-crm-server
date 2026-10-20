"""Звания лиги: «Кепка позора», «В чужом шарфе» и остальные — из готовых ходов."""

from __future__ import annotations

from datetime import datetime, timezone

from src.application.hockey_leagues import pick_titles

T = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)


def _p(
    player: int,
    match: int,
    *,
    points: int | None,
    status: str = "final",
    side: str = "home",
    home: str = "Динамо-Минск",
) -> dict:
    return {
        "player_key": player,
        "match_id": match,
        "starts_at": T,
        "status": status,
        "home_team": home,
        "side": side,
        "points": points,
    }


def test_cap_goes_to_the_lowest_score_of_the_last_match_only() -> None:
    picks = [
        _p(1, 10, points=0),  # прошлый матч: кепку уже не носит
        _p(2, 10, points=50),
        _p(1, 11, points=50),
        _p(2, 11, points=0),
        _p(3, 11, points=0),
    ]
    titles = pick_titles(picks, next_match_id=None)
    assert titles[2] == {"id": "cap", "label": "Кепка позора", "detail": "0 очков"}
    assert titles[3]["id"] == "cap"
    assert 1 not in titles


def test_no_cap_when_everyone_scored_the_same_or_played_alone() -> None:
    assert pick_titles([_p(1, 11, points=20), _p(2, 11, points=20)], next_match_id=None) == {}
    assert pick_titles([_p(1, 11, points=0)], next_match_id=None) == {}


def test_scarf_bets_against_dinamo_on_the_next_match_home_and_away() -> None:
    picks = [
        _p(1, 12, points=None, status="scheduled", side="away"),  # дома Динамо, ход за гостей
        _p(2, 12, points=None, status="scheduled", side="home"),
        _p(3, 13, points=None, status="scheduled", side="home", home="ХК Сочи"),  # не ближайший матч
    ]
    titles = pick_titles(picks, next_match_id=12)
    assert titles == {1: {"id": "scarf", "label": "В чужом шарфе", "detail": ""}}
    away = [_p(4, 13, points=None, status="scheduled", side="home", home="ХК Сочи")]
    assert pick_titles(away, next_match_id=13)[4]["id"] == "scarf"


def test_cap_wins_over_scarf_for_one_person() -> None:
    picks = [_p(1, 11, points=0), _p(2, 11, points=30), _p(1, 12, points=None, status="scheduled", side="away")]
    assert pick_titles(picks, next_match_id=12)[1]["id"] == "cap"
    assert pick_titles(picks, next_match_id=12)[1]["detail"] == "0 очков"


def _s(player: int, match: int, home_score: int, away_score: int, *, home: str = "Динамо-Минск") -> dict:
    return {
        **_p(player, match, points=None, status="scheduled", home=home),
        "pick_home": home_score,
        "pick_away": away_score,
    }


def test_vanga_is_the_single_leader_in_exact_scores() -> None:
    picks = [
        _p(1, 10, points=50),
        _p(2, 10, points=20),
        _p(1, 11, points=50),
        _p(2, 11, points=50),
        _p(2, 12, points=20),
    ]
    titles = pick_titles(picks, next_match_id=None)
    assert titles[1] == {"id": "vanga", "label": "Ванга", "detail": "2 точных"}
    one = pick_titles([_p(1, 10, points=50), _p(2, 10, points=20)], next_match_id=None)
    assert all(t["id"] != "vanga" for t in one.values()), "один точный — ещё не Ванга"
    tie = pick_titles([_p(1, 10, points=50), _p(2, 10, points=50)], next_match_id=None)
    assert all(t["id"] != "vanga" for t in tie.values())


def test_streak_counts_winners_from_the_latest_match_back() -> None:
    picks = [_p(1, m, points=pts) for m, pts in ((1, 0), (2, 20), (3, 30), (4, 20))] + [_p(2, 4, points=20)]
    assert pick_titles(picks, next_match_id=None)[1] == {"id": "streak", "label": "Чуйка", "detail": "3 подряд"}
    broken = [_p(1, m, points=pts) for m, pts in ((1, 20), (2, 20), (3, 20), (4, 10))]
    assert 1 not in pick_titles(broken, next_match_id=None)


def test_optimist_puts_dinamo_two_goals_up_on_average_home_or_away() -> None:
    picks = [_s(1, 20, 5, 1), _s(1, 21, 0, 3, home="ХК Сочи"), _s(2, 20, 2, 1), _s(2, 21, 1, 2, home="ХК Сочи")]
    titles = pick_titles(picks, next_match_id=None)
    assert titles[1]["id"] == "optimist"
    assert 2 not in titles


def test_optimist_starts_at_exactly_two_goals_on_average() -> None:
    exactly_two = [_s(5, 30, 3, 1), _s(5, 31, 4, 2)]
    assert pick_titles(exactly_two, next_match_id=None)[5]["id"] == "optimist"
    just_under = [_s(6, 30, 3, 1), _s(6, 31, 2, 1)]
    assert 6 not in pick_titles(just_under, next_match_id=None)
