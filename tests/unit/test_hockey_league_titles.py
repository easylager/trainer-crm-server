"""Звания лиги: «Кепка дня», «В чужом шарфе» и остальные — из готовых ходов."""

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
    away: str = "ХК Сочи",
) -> dict:
    return {
        "player_key": player,
        "match_id": match,
        "starts_at": T,
        "status": status,
        "home_team": home,
        "away_team": away,
        "side": side,
        "points": points,
    }


def test_no_cap_title_it_is_worn_on_the_head() -> None:
    # Кепку дня считает «Вечер» лиги (TASK-431) и рисует на голове (TASK-432): званием она не бывает.
    picks = [_p(1, 11, points=50), _p(2, 11, points=0), _p(3, 11, points=0)]
    assert pick_titles(picks) == {}


DINAMO = "Динамо-Минск"
YOUTH = "Юность-Минск"


def test_scarf_for_a_move_against_your_own_team_on_its_next_match() -> None:
    picks = [
        _p(1, 12, points=None, status="scheduled", side="away"),  # болеет за Динамо, дома Динамо, ход за гостей
        _p(2, 12, points=None, status="scheduled", side="home"),
        _p(4, 13, points=None, status="scheduled", side="home", home="ХК Сочи", away=DINAMO),  # Динамо в гостях
    ]
    titles = pick_titles(picks, fans={1: DINAMO, 2: DINAMO, 4: DINAMO})
    assert titles == {
        1: {"id": "scarf", "label": "В чужом шарфе", "detail": ""},
        4: {"id": "scarf", "label": "В чужом шарфе", "detail": ""},
    }


def test_scarf_follows_the_players_own_club_not_dinamo() -> None:
    picks = [_p(1, 20, points=None, status="scheduled", side="away", home=YOUTH, away="Неман")]
    assert pick_titles(picks, fans={1: YOUTH})[1]["id"] == "scarf"
    assert pick_titles(picks, fans={1: "Неман"}) == {}


def test_no_scarf_for_a_match_without_your_team() -> None:
    # Ход за хозяев в матче Экстралиги без Динамо — не против Динамо (раньше давали шарф).
    picks = [_p(1, 20, points=None, status="scheduled", side="home", home=YOUTH, away="Неман")]
    assert pick_titles(picks, fans={1: DINAMO}) == {}


def test_scarf_looks_only_at_the_nearest_match_of_your_team_and_needs_one() -> None:
    picks = [
        _p(1, 30, points=None, status="scheduled", side="home"),  # ближайший матч Динамо — за своих
        _p(1, 31, points=None, status="scheduled", side="away"),  # следующий — против, но ещё не время
    ]
    assert pick_titles(picks, fans={1: DINAMO}) == {}
    assert pick_titles([_p(1, 31, points=None, status="scheduled", side="away")]) == {}


def test_scarf_for_a_move_against_own_team() -> None:
    picks = [_p(1, 11, points=0), _p(2, 11, points=30), _p(1, 12, points=None, status="scheduled", side="away")]
    assert pick_titles(picks, fans={1: "Динамо-Минск"})[1]["id"] == "scarf"


def _s(
    player: int, match: int, home_score: int, away_score: int, *, home: str = "Динамо-Минск", away: str = ""
) -> dict:
    away = away or ("ХК Сочи" if home == "Динамо-Минск" else "Динамо-Минск")
    return {
        **_p(player, match, points=None, status="scheduled", home=home, away=away),
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
    titles = pick_titles(picks)
    assert titles[1] == {"id": "vanga", "label": "Ванга", "detail": "2 точных"}
    one = pick_titles([_p(1, 10, points=50), _p(2, 10, points=20)])
    assert all(t["id"] != "vanga" for t in one.values()), "один точный — ещё не Ванга"
    tie = pick_titles([_p(1, 10, points=50), _p(2, 10, points=50)])
    assert all(t["id"] != "vanga" for t in tie.values())


def test_streak_counts_winners_from_the_latest_match_back() -> None:
    picks = [_p(1, m, points=pts) for m, pts in ((1, 0), (2, 20), (3, 30), (4, 20))] + [_p(2, 4, points=20)]
    assert pick_titles(picks)[1] == {"id": "streak", "label": "Чуйка", "detail": "3 подряд"}
    broken = [_p(1, m, points=pts) for m, pts in ((1, 20), (2, 20), (3, 20), (4, 10))]
    assert 1 not in pick_titles(broken)


def test_optimist_puts_dinamo_two_goals_up_on_average_home_or_away() -> None:
    picks = [_s(1, 20, 5, 1), _s(1, 21, 0, 3, home="ХК Сочи"), _s(2, 20, 2, 1), _s(2, 21, 1, 2, home="ХК Сочи")]
    titles = pick_titles(picks)
    assert titles[1]["id"] == "optimist"
    assert 2 not in titles


def test_optimist_starts_at_exactly_two_goals_on_average() -> None:
    exactly_two = [_s(5, 30, 3, 1), _s(5, 31, 4, 2)]
    assert pick_titles(exactly_two)[5]["id"] == "optimist"
    just_under = [_s(6, 30, 3, 1), _s(6, 31, 2, 1)]
    assert 6 not in pick_titles(just_under)


def test_optimist_counts_only_dinamo_matches() -> None:
    # Экстралига в лиге «всё»: 5:0 Юности — не ход «за Динамо», оптимиста из него не делаем.
    picks = [_s(7, 40, 5, 0, home=YOUTH, away="Неман"), _s(7, 41, 6, 1, home=YOUTH, away="Неман"), _s(7, 42, 1, 1)]
    assert 7 not in pick_titles(picks)
