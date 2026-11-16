"""TASK-426 срез 1: фаза игрока считается из данных; границы 6/7/13/14 суток, блокировка, «не присылать»."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from kk_notify_helpers import KATYA, LESHA, SASHA, at, seed_pick, seed_player

from src.application.kk_notify_phase import Phase, days_since, load_one, load_player_facts, player_phase

NOW = at(12, day=20)


def phase(days_ago: int | None, *, blocked=False, opted_out=False, hour=12) -> Phase:
    last = None if days_ago is None else at(hour, day=20) - timedelta(days=days_ago)
    return player_phase(now=NOW, last_pick_at=last, blocked=blocked, opted_out=opted_out)


@pytest.mark.parametrize(
    ("days_ago", "expected"),
    [
        (0, Phase.ACTIVE),
        (6, Phase.ACTIVE),
        (7, Phase.COOLING),
        (13, Phase.COOLING),
        (14, Phase.LOST),
        (60, Phase.LOST),
    ],
)
def test_phase_boundaries(days_ago, expected) -> None:
    assert phase(days_ago) is expected


def test_no_picks_is_new() -> None:
    assert phase(None) is Phase.NEW


def test_off_beats_every_other_phase() -> None:
    for days in (None, 0, 8, 30):
        assert phase(days, blocked=True) is Phase.OFF
        assert phase(days, opted_out=True) is Phase.OFF


def test_boundary_counts_minsk_calendar_days_not_24h_blocks() -> None:
    """Ход в 23:50 шесть суток назад — всё ещё «6 дней», хотя прошло почти 6 суток 12 часов; 00:10 семь дней назад — уже 7."""
    assert phase(6, hour=23) is Phase.ACTIVE
    assert phase(7, hour=0) is Phase.COOLING
    # то же по UTC-границе: 22:30 UTC 12 ноября = 01:30 Минск 13 ноября, до «сегодня» (20-го) ровно семь календарных дней
    pick = datetime(2026, 11, 12, 22, 30, tzinfo=timezone.utc)
    assert days_since(pick, NOW) == 7
    assert player_phase(now=NOW, last_pick_at=pick, blocked=False, opted_out=False) is Phase.COOLING


def test_phase_across_month_end() -> None:
    now = at(10, day=3, month=12)
    last = at(10, day=26, month=11)
    assert player_phase(now=now, last_pick_at=last, blocked=False, opted_out=False) is Phase.COOLING  # ровно 7 дней
    assert player_phase(now=at(10, day=2, month=12), last_pick_at=last, blocked=False, opted_out=False) is Phase.ACTIVE


def test_naive_datetimes_are_read_as_utc() -> None:
    assert days_since(datetime(2026, 11, 12, 22, 30), NOW) == 7


@pytest.mark.asyncio
async def test_phases_come_from_database(db_session) -> None:
    reg = at(10, day=1)
    await seed_player(db_session, SASHA, registered=reg)
    await seed_pick(db_session, SASHA, NOW - timedelta(days=2))
    await seed_player(db_session, KATYA, registered=reg, blocked_at=at(1, day=18))
    await seed_pick(db_session, KATYA, NOW - timedelta(days=2))
    await seed_player(db_session, LESHA, registered=reg, remind=True)
    facts = {f.player_key: f for f in await load_player_facts(db_session, as_of=NOW)}
    assert facts[SASHA].phase(NOW) is Phase.ACTIVE
    assert facts[KATYA].phase(NOW) is Phase.OFF
    assert facts[LESHA].phase(NOW) is Phase.NEW
    # на 14 дней позже тот же ход — «отвалился»
    later = NOW + timedelta(days=12)
    assert (await load_one(db_session, SASHA, as_of=later)).phase(later) is Phase.LOST


@pytest.mark.asyncio
async def test_opt_out_in_database_switches_off(db_session) -> None:
    await seed_player(db_session, SASHA, registered=at(10, day=1), remind=False)
    await seed_pick(db_session, SASHA, NOW - timedelta(days=1))
    assert (await load_one(db_session, SASHA, as_of=NOW)).phase(NOW) is Phase.OFF


@pytest.mark.asyncio
async def test_as_of_ignores_later_picks_and_later_players(db_session) -> None:
    await seed_player(db_session, SASHA, registered=at(10, day=1))
    await seed_pick(db_session, SASHA, at(10, day=15))
    await seed_player(db_session, KATYA, registered=at(10, day=19))
    early = at(12, day=12)
    assert (await load_one(db_session, SASHA, as_of=early)).phase(early) is Phase.NEW  # хода ещё не было
    assert await load_one(db_session, KATYA, as_of=early) is None  # ещё не зарегистрирован
