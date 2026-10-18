"""TASK-297: ход, закрытие на старте, очки по итогу, общая таблица."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.hockey_game import (
    PicksClosed,
    make_pick,
    normalize_pick,
    player_matches,
    player_standing,
    score_finished_matches,
    season_start,
    standings,
)
from src.application.hockey_matches import set_manual_result
from src.ingestion.hockey_sources import MINSK_TZ

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=MINSK_TZ)
SASHA, KATYA, LESHA, IGOR = 9100001, 9100002, 9100003, 9100004


async def _match(db_session, mid: str, starts_at: datetime, home: str = "Динамо-Минск", away: str = "Барыс") -> int:
    return (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
                VALUES ('hcdinamo', :mid, :home, :away, :starts_at) RETURNING id
                """),
            {"mid": mid, "home": home, "away": away, "starts_at": starts_at},
        )
    ).scalar_one()


async def _pick(db_session, match_id: int, player: int, name: str = "Саша", **kw):
    return await make_pick(db_session, player_key=player, display_name=name, match_id=match_id, now=NOW, **kw)


async def _final(db_session, match_id: int, home: int, away: int, decided: str = "regulation", at: datetime = NOW):
    await set_manual_result(db_session, match_id, home_score=home, away_score=away, decided_in=decided, now=at)


async def _points(db_session, match_id: int, player: int):
    return (
        await db_session.execute(
            text("SELECT points FROM hockey_picks WHERE match_id = :m AND player_key = :p"),
            {"m": match_id, "p": player},
        )
    ).scalar_one()


# --- чистые правила ---


@pytest.mark.parametrize(
    ("side", "home", "away", "expected"),
    [
        ("home", None, None, ("home", None, None)),
        (None, 1, 4, ("away", 1, 4)),
        ("away", 2, 3, ("away", 2, 3)),
    ],
)
def test_normalize_pick_ok(side, home, away, expected) -> None:
    assert normalize_pick(side, home, away) == expected


@pytest.mark.parametrize(
    ("side", "home", "away"),
    [
        (None, None, None),
        ("draw", None, None),
        (None, 2, 2),
        ("home", 1, 4),
        (None, 3, None),
        (None, -1, 2),
        (None, 21, 0),
    ],
)
def test_normalize_pick_rejects(side, home, away) -> None:
    with pytest.raises(ValueError):
        normalize_pick(side, home, away)


def test_season_starts_first_of_august_minsk() -> None:
    assert season_start(datetime(2026, 10, 20, tzinfo=timezone.utc)) == datetime(2026, 8, 1, tzinfo=MINSK_TZ)
    assert season_start(datetime(2027, 3, 1, tzinfo=timezone.utc)) == datetime(2026, 8, 1, tzinfo=MINSK_TZ)


# --- ход и срок ---


@pytest.mark.asyncio
async def test_pick_is_replaced_not_duplicated(db_session) -> None:
    mid = await _match(db_session, "p1", NOW + timedelta(days=1))
    first = await _pick(db_session, mid, SASHA, side="home")
    second = await _pick(db_session, mid, SASHA, home_score=2, away_score=3)
    assert (first.side, second.side, second.home_score, second.away_score) == ("home", "away", 2, 3)
    count = (
        await db_session.execute(text("SELECT COUNT(*) FROM hockey_picks WHERE match_id = :m"), {"m": mid})
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_pick_closed_at_start_on_server(db_session) -> None:
    mid = await _match(db_session, "p2", NOW)
    with pytest.raises(PicksClosed):
        await _pick(db_session, mid, SASHA, side="home")
    with pytest.raises(LookupError):
        await _pick(db_session, 987654321, SASHA, side="home")


@pytest.mark.asyncio
async def test_postponed_match_reopens_by_new_start(db_session) -> None:
    mid = await _match(db_session, "p3", NOW - timedelta(minutes=5))
    with pytest.raises(PicksClosed):
        await _pick(db_session, mid, SASHA, side="home")
    await db_session.execute(
        text("UPDATE hockey_matches SET starts_at = :s WHERE id = :m"), {"s": NOW + timedelta(days=2), "m": mid}
    )
    assert (await _pick(db_session, mid, SASHA, side="home")).side == "home"


@pytest.mark.asyncio
async def test_finished_match_closed_even_if_time_looks_open(db_session) -> None:
    mid = await _match(db_session, "p4", NOW + timedelta(hours=1))
    await _final(db_session, mid, 3, 2)
    with pytest.raises(PicksClosed):
        await _pick(db_session, mid, SASHA, side="home")


# --- очки ---


@pytest.mark.asyncio
async def test_points_exact_winner_miss_and_idempotent(db_session) -> None:
    mid = await _match(db_session, "s1", NOW + timedelta(hours=2))
    await _pick(db_session, mid, SASHA, "Саша", home_score=1, away_score=4)
    await _pick(db_session, mid, KATYA, "Катя", side="away")
    await _pick(db_session, mid, LESHA, "Лёша", home_score=2, away_score=3)
    await _pick(db_session, mid, IGOR, "Игорь", side="home")
    await _final(db_session, mid, 1, 4, at=NOW + timedelta(hours=5))

    assert await score_finished_matches(db_session, now=NOW + timedelta(hours=5)) == 4
    assert [await _points(db_session, mid, p) for p in (SASHA, KATYA, LESHA, IGOR)] == [5, 1, 1, 0]
    # Повторный прогон ничего не трогает.
    assert await score_finished_matches(db_session, now=NOW + timedelta(hours=6)) == 0
    assert await _points(db_session, mid, SASHA) == 5


@pytest.mark.asyncio
async def test_corrected_result_rescores_without_double_points(db_session) -> None:
    mid = await _match(db_session, "s2", NOW + timedelta(hours=2))
    await _pick(db_session, mid, SASHA, home_score=1, away_score=4)
    await _pick(db_session, mid, KATYA, home_score=2, away_score=4)
    await _final(db_session, mid, 1, 4, at=NOW + timedelta(hours=5))
    await score_finished_matches(db_session, now=NOW + timedelta(hours=5))
    # Админ исправил итог позже подсчёта.
    await _final(db_session, mid, 2, 4, at=NOW + timedelta(hours=7))
    assert await score_finished_matches(db_session, now=NOW + timedelta(hours=7)) == 2
    assert (await _points(db_session, mid, SASHA), await _points(db_session, mid, KATYA)) == (1, 5)


@pytest.mark.asyncio
async def test_shootout_official_score_counts_as_exact(db_session) -> None:
    mid = await _match(db_session, "s3", NOW + timedelta(hours=2), home="Динамо-Минск", away="Торпедо")
    await _pick(db_session, mid, SASHA, home_score=1, away_score=2)
    await _final(db_session, mid, 1, 2, decided="so", at=NOW + timedelta(hours=5))
    await score_finished_matches(db_session, now=NOW + timedelta(hours=5))
    assert await _points(db_session, mid, SASHA) == 5


@pytest.mark.asyncio
async def test_cancelled_match_loses_points(db_session) -> None:
    mid = await _match(db_session, "s4", NOW + timedelta(hours=2))
    await _pick(db_session, mid, SASHA, side="home")
    await _final(db_session, mid, 3, 1, at=NOW + timedelta(hours=5))
    await score_finished_matches(db_session, now=NOW + timedelta(hours=5))
    await db_session.execute(text("UPDATE hockey_matches SET status = 'cancelled' WHERE id = :m"), {"m": mid})
    await score_finished_matches(db_session, now=NOW + timedelta(hours=6))
    assert await _points(db_session, mid, SASHA) is None


# --- таблица ---


@pytest.mark.asyncio
async def test_standings_rank_by_points_then_exact_and_season(db_session) -> None:
    a = await _match(db_session, "t1", NOW + timedelta(hours=1))
    b = await _match(db_session, "t2", NOW + timedelta(hours=3))
    old = await _match(db_session, "t0", datetime(2026, 3, 1, 19, 0, tzinfo=MINSK_TZ))
    # Ход на прошлый сезон — прямой записью, через make_pick он уже закрыт.
    await db_session.execute(
        text("INSERT INTO hockey_players (player_key, display_name) VALUES (:p, 'Игорь') ON CONFLICT DO NOTHING"),
        {"p": IGOR},
    )
    await db_session.execute(
        text(
            "INSERT INTO hockey_picks (match_id, player_key, side, home_score, away_score) VALUES (:m, :p, 'home', 4, 1)"
        ),
        {"m": old, "p": IGOR},
    )
    await _pick(db_session, a, SASHA, "Саша", home_score=3, away_score=1)  # 5
    await _pick(db_session, a, KATYA, "Катя", side="home")  # 1
    await _pick(db_session, b, KATYA, "Катя", side="home")  # 1
    await _pick(db_session, b, SASHA, "Саша", side="away")  # 0
    await _pick(db_session, b, LESHA, "Лёша", side="home")  # 1
    await _final(db_session, a, 3, 1, at=NOW + timedelta(hours=4))
    await _final(db_session, b, 2, 1, at=NOW + timedelta(hours=6))
    await _final(db_session, old, 4, 1, at=NOW + timedelta(hours=6))
    await score_finished_matches(db_session, now=NOW + timedelta(hours=6))

    table = await standings(db_session, now=NOW)
    ours = [s for s in table if s.player_key in (SASHA, KATYA, LESHA, IGOR)]
    assert [(s.display_name, s.points, s.exact, s.played) for s in ours] == [
        ("Саша", 5, 1, 2),
        ("Катя", 2, 0, 2),
        ("Лёша", 1, 0, 1),
    ]
    assert ours[0].rank < ours[1].rank < ours[2].rank
    me = await player_standing(db_session, KATYA, now=NOW)
    assert me is not None and (me.points, me.rank) == (2, ours[1].rank)
    assert await player_standing(db_session, IGOR, now=NOW) is None


@pytest.mark.asyncio
async def test_player_matches_show_my_pick_and_sides(db_session) -> None:
    mid = await _match(db_session, "f1", NOW + timedelta(days=1))
    await _pick(db_session, mid, SASHA, side="home")
    await _pick(db_session, mid, KATYA, side="away")
    await _pick(db_session, mid, LESHA, home_score=1, away_score=3)
    rows = [r for r in await player_matches(db_session, LESHA, since=NOW) if r["id"] == mid]
    assert len(rows) == 1
    r = rows[0]
    assert (r["pick_side"], r["pick_home_score"], r["pick_away_score"]) == ("away", 1, 3)
    assert (r["home_picks"], r["away_picks"]) == (1, 2)
