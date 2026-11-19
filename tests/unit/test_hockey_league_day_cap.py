"""Кепка дня лиги (TASK-431): средние очки за ход за игровой день, все ветки правила."""

from __future__ import annotations

from src.application.hockey_league_evening import CAP_MIN_CONTENDERS, cap_min_moves, day_cap


def test_threshold_constants_are_the_owners_numbers() -> None:
    assert CAP_MIN_CONTENDERS == 2
    assert [cap_min_moves(n) for n in (1, 2, 3, 4, 5)] == [1, 1, 2, 2, 3]


def test_worst_average_per_move_gets_the_cap() -> None:
    # Пример из шторки правил: вечер из 4 матчей.
    stats = {1: (80, 4), 2: (50, 3), 3: (10, 3), 4: (20, 1)}
    cap = day_cap(stats, matches=4, complete=True)
    assert cap.holders == {3}
    assert cap.contenders == {1, 2, 3}  # Дима с одним ходом не в споре
    assert cap.decided and cap.in_play and cap.need_moves == 2


def test_average_not_total_decides() -> None:
    # Сравниваем очки за ход, а не сумму: 30 за два хода (15) хуже 60 за три (20); один ход из четырёх — не в споре.
    stats = {1: (60, 3), 2: (30, 2), 3: (45, 3), 4: (0, 1)}
    assert day_cap(stats, matches=4, complete=True).holders == {2, 3}  # 15 = 15: ничья по худшему


def test_half_of_the_day_is_enough_to_be_in_the_race() -> None:
    stats = {1: (0, 2), 2: (50, 4), 3: (40, 4)}
    assert day_cap(stats, matches=4, complete=True).holders == {1}
    odd = {1: (0, 2), 2: (50, 3), 3: (40, 3)}
    assert day_cap(odd, matches=3, complete=True).holders == {1}  # ceil(3/2) = 2
    short = {1: (0, 1), 2: (50, 3), 3: (40, 3), 4: (30, 3)}
    assert day_cap(short, matches=3, complete=True).holders == {4}


def test_two_in_the_race_are_enough() -> None:
    # Владелец 2026-11-19: вдвоём тоже играют. Третий не ходил — кепка и капитан всё равно есть.
    stats = {1: (0, 2), 2: (50, 2), 3: (0, 0)}
    cap = day_cap(stats, matches=2, complete=True)
    assert cap.holders == {1} and cap.captains == {2} and cap.in_play
    alone = day_cap({1: (50, 2), 3: (0, 0)}, matches=2, complete=True)
    assert alone.holders == frozenset() and alone.decided and not alone.in_play  # в споре один — не с кем


def test_tie_at_the_bottom_caps_everyone_at_the_bottom() -> None:
    stats = {1: (0, 2), 2: (0, 2), 3: (40, 2)}
    assert day_cap(stats, matches=2, complete=True).holders == {1, 2}


def test_all_equal_no_cap() -> None:
    stats = {1: (20, 2), 2: (40, 4), 3: (10, 1)}  # у всех по 10 за ход
    cap = day_cap(stats, matches=2, complete=True)
    assert cap.holders == frozenset() and cap.in_play
    stats = {1: (20, 2), 2: (20, 2), 3: (20, 2)}
    cap = day_cap(stats, matches=2, complete=True)
    assert cap.holders == frozenset() and cap.in_play


def test_unfinished_day_is_not_decided() -> None:
    stats = {1: (0, 2), 2: (50, 2), 3: (40, 2)}
    cap = day_cap(stats, matches=3, complete=False)
    assert cap.holders == frozenset() and not cap.decided
    assert cap.contenders == {1, 2, 3}  # кто в споре — видно и до решения


def test_one_team_league_day_is_one_match() -> None:
    stats = {1: (0, 1), 2: (20, 1), 3: (50, 1), 4: (0, 0)}
    cap = day_cap(stats, matches=1, complete=True)
    assert cap.need_moves == 1 and cap.holders == {1} and 4 not in cap.contenders


def test_captain_is_the_most_points_among_contenders_not_in_the_cap() -> None:
    # Капитан (TASK-432) — по сумме: 4 из 4 и +130 лучше, чем 2 хода по 40 в среднем.
    stats = {1: (130, 4), 2: (80, 2), 3: (10, 3), 4: (200, 1)}
    cap = day_cap(stats, matches=4, complete=True)
    assert cap.captains == {1} and cap.holders == {3}  # 4 с одним ходом не в споре


def test_the_cap_holder_is_never_captain() -> None:
    # Больше всех очков, но хуже всех в среднем: кепка, а капитан — следующий по сумме.
    stats = {1: (80, 4), 2: (50, 2), 3: (50, 2)}
    cap = day_cap(stats, matches=4, complete=True)
    assert cap.holders == {1} and cap.captains == {2, 3}


def test_captains_tie_and_no_captain_without_a_decided_race() -> None:
    assert day_cap({1: (40, 2), 2: (40, 2), 3: (0, 2)}, matches=2, complete=True).captains == {1, 2}
    assert day_cap({1: (20, 2), 2: (20, 2), 3: (20, 2)}, matches=2, complete=True).captains == frozenset()
    # Средние равны (кепки нет), а суммы разные — капитан есть.
    assert day_cap({1: (20, 2), 2: (40, 4), 3: (10, 1)}, matches=2, complete=True).captains == {2}
    assert day_cap({1: (0, 2), 2: (50, 2)}, matches=2, complete=True).captains == {2}  # вдвоём — тоже
    assert day_cap({1: (0, 2), 2: (50, 2), 3: (40, 2)}, matches=3, complete=False).captains == frozenset()


def test_goals_only_points_are_part_not_a_hit() -> None:
    # Саша (прод, 17.11): ход за хозяев 3:2 при итоге 1:2 — угаданы шайбы гостей, +10, козырь — +20. Не «угадал».
    from datetime import datetime, timezone

    from src.application.hockey_league_evening import HIT, MISS, PART, DayMatch, DayRow, Member, mark

    m = DayMatch(1, "Нефтехимик", "Динамо-Минск", datetime(2026, 11, 17, tzinfo=timezone.utc), "final", 1, 2)
    pick = {"points": 10, "doubled": True, "final": True}
    assert mark(pick, m) == PART
    assert mark({**pick, "points": 20}, m) == HIT and mark({**pick, "points": 0}, m) == MISS
    row = DayRow(member=Member(1, "Саша", "p", m.starts_at), picks={1: pick})
    assert (row.hits, row.moves, row.points) == (0, 1, 20)
