"""TASK-359: список «Матчи и мои ходы» — фазы матча, окно на сезон, подгрузка, режимы «мои / все»."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from src.application.hockey_game import (
    HISTORY_PAGE,
    MATCH_LIVE_FOR,
    MATCH_STALE_AFTER,
    UPCOMING_LIMIT,
    awaiting_count,
    decode_cursor,
    encode_cursor,
    match_phase,
    match_stale,
    my_points,
    player_match_list,
)
from src.ingestion.hockey_sources import MINSK_TZ

NOW = datetime(2026, 11, 9, 20, 0, tzinfo=MINSK_TZ)
ME, OTHER = 9359001, 9359002


async def _match(
    db,
    starts_at: datetime,
    *,
    status: str = "scheduled",
    league: str = "khl",
    home: str = "Динамо-Минск",
    away: str = "Барыс",
    probe: bool = False,
) -> int:
    source = "hockeyby" if league == "extraliga" else "hcdinamo"
    final = status == "final"
    return int(
        (
            await db.execute(
                text("""
                    INSERT INTO hockey_matches (
                        source, league, source_match_id, home_team, away_team, starts_at, status,
                        home_score, away_score, decided_in, result_source, finalized_at, result_probe
                    ) VALUES (
                        :source, :league, :mid, :home, :away, :starts_at, :status,
                        :hs, :as_, :decided, :rsrc, :fin, CAST(:probe AS jsonb)
                    ) RETURNING id
                    """),
                {
                    "source": source,
                    "league": league,
                    "mid": uuid.uuid4().hex,
                    "home": home,
                    "away": away,
                    "starts_at": starts_at,
                    "status": status,
                    "hs": 3 if final else None,
                    "as_": 2 if final else None,
                    "decided": "regulation" if final else None,
                    "rsrc": "manual" if final else None,
                    "fin": starts_at + timedelta(hours=3) if final else None,
                    "probe": '{"home": 3, "away": 2, "decided_in": "regulation"}' if probe else None,
                },
            )
        ).scalar_one()
    )


async def _pick(db, match_id: int, who: int = ME, *, points: int | None = None, doubled: bool = False) -> None:
    await db.execute(
        text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, 'Игрок') ON CONFLICT DO NOTHING"),
        {"k": who},
    )
    await db.execute(
        text("""
            INSERT INTO hockey_picks (match_id, player_key, side, points, doubled, trump_week)
            VALUES (:m, :k, 'home', :p, :d, CASE WHEN :d THEN DATE '2026-11-02' END)
            """),
        {"m": match_id, "k": who, "p": points, "d": doubled},
    )


def _ids(page: dict) -> list[int]:
    return [r["id"] for r in page["rows"]]


def test_match_phase_follows_the_match_from_upcoming_to_done() -> None:
    start = NOW
    before = NOW - timedelta(minutes=1)
    assert match_phase("scheduled", start, before) == "upcoming"
    assert match_phase("scheduled", start, NOW + timedelta(minutes=1)) == "live"
    assert match_phase("scheduled", start, NOW + MATCH_LIVE_FOR - timedelta(seconds=1)) == "live"
    # Трёх часов хватает любой игре: дальше без итога — «ждём итог».
    assert match_phase("scheduled", start, NOW + MATCH_LIVE_FOR) == "waiting"
    # Запомненный итог (один опрос) и ручная проверка — «ждём итог» сразу, не дожидаясь трёх часов.
    assert match_phase("scheduled", start, NOW + timedelta(hours=2), has_probe=True) == "waiting"
    assert match_phase("review", start, NOW + timedelta(minutes=30)) == "waiting"
    assert match_phase("final", start, NOW + timedelta(hours=4)) == "done"
    assert match_phase("cancelled", start, before) == "cancelled"
    assert match_phase("cancelled", start, NOW + timedelta(hours=4)) == "cancelled"


def test_stale_only_for_waiting_after_three_days() -> None:
    late = NOW + MATCH_STALE_AFTER
    assert match_stale("waiting", NOW, late) is True
    assert match_stale("waiting", NOW, late - timedelta(seconds=1)) is False
    assert match_stale("done", NOW, late) is False
    assert match_stale("live", NOW, late) is False


def test_my_points_apply_the_trump_to_base_points() -> None:
    assert my_points(None, True) is None
    assert my_points(50, False) == 50
    assert my_points(50, True) == 100
    assert my_points(0, True) == 0


def test_cursor_round_trip_and_garbage() -> None:
    raw = encode_cursor(NOW, 77)
    when, ident = decode_cursor(raw)
    assert when == NOW and ident == 77
    assert "+" not in raw and " " not in raw  # живёт в адресной строке как есть
    for bad in ("", "no-sep", "not-a-number_1", f"{raw.split('_')[0]}_x", "999999999999999999999999_1"):
        with pytest.raises(ValueError):
            decode_cursor(bad)


@pytest.mark.asyncio
async def test_history_does_not_displace_the_future_and_pages_through_the_season(db_session) -> None:
    played = [await _match(db_session, NOW - timedelta(hours=5 + i), status="final") for i in range(30)]
    ahead = [await _match(db_session, NOW + timedelta(hours=2 + i)) for i in range(10)]

    first = await player_match_list(db_session, ME, now=NOW)
    ids = _ids(first)
    # Будущее целиком, а сыгранные — только последняя страница, самые свежие.
    assert set(ahead) <= set(ids)
    assert set(ids) - set(ahead) == set(played[:HISTORY_PAGE])
    assert first["has_more"] is True and first["next_before"]
    assert ids == sorted(ids, key=lambda i: next(r for r in first["rows"] if r["id"] == i)["starts_at"])

    seen = list(played[:HISTORY_PAGE])
    cursor = first["next_before"]
    for _ in range(5):
        page = await player_match_list(db_session, ME, now=NOW, before=cursor)
        assert set(_ids(page)).isdisjoint(ahead)  # страница «раньше» — только прошедшие
        seen += sorted(_ids(page), key=lambda i: played.index(i))
        cursor = page["next_before"]
        if not page["has_more"]:
            break
    assert cursor is None
    assert sorted(seen) == sorted(played)  # весь сезон, без дублей и пропусков


@pytest.mark.asyncio
async def test_upcoming_is_capped_but_nearest_first(db_session) -> None:
    ahead = [await _match(db_session, NOW + timedelta(hours=1 + i)) for i in range(UPCOMING_LIMIT + 5)]
    page = await player_match_list(db_session, ME, now=NOW)
    assert _ids(page) == ahead[:UPCOMING_LIMIT]


@pytest.mark.asyncio
async def test_started_without_result_is_never_pushed_out_by_a_long_history(db_session) -> None:
    for i in range(25):
        await _match(db_session, NOW - timedelta(hours=30 + i), status="final")
    live = await _match(db_session, NOW - timedelta(hours=1))
    waiting = await _match(db_session, NOW - timedelta(hours=4), league="extraliga", probe=True)
    reviewed = await _match(db_session, NOW - timedelta(hours=5), status="review")
    page = await player_match_list(db_session, ME, now=NOW)
    by_id = {r["id"]: r for r in page["rows"]}
    assert {live, waiting, reviewed} <= set(by_id)
    assert by_id[waiting]["has_probe"] is True and by_id[live]["has_probe"] is False


@pytest.mark.asyncio
async def test_mine_keeps_my_moves_and_every_future_match_but_hides_the_rest(db_session) -> None:
    mine_done = await _match(db_session, NOW - timedelta(hours=30), status="final")
    other_done = await _match(db_session, NOW - timedelta(hours=31), status="final")
    mine_live = await _match(db_session, NOW - timedelta(hours=1))
    other_live = await _match(db_session, NOW - timedelta(hours=2))
    future = await _match(db_session, NOW + timedelta(hours=5))
    for match_id in (mine_done, mine_live):
        await _pick(db_session, match_id)
    await _pick(db_session, other_done, OTHER)

    mine = set(_ids(await player_match_list(db_session, ME, now=NOW, mode="mine")))
    assert mine == {mine_done, mine_live, future}
    everyone = set(_ids(await player_match_list(db_session, ME, now=NOW, mode="all")))
    assert everyone == {mine_done, other_done, mine_live, other_live, future}


@pytest.mark.asyncio
async def test_league_filter_applies_to_every_part(db_session) -> None:
    khl = [
        await _match(db_session, NOW - timedelta(hours=30), status="final"),
        await _match(db_session, NOW - timedelta(hours=1)),
        await _match(db_session, NOW + timedelta(hours=5)),
    ]
    xl = [
        await _match(db_session, NOW - timedelta(hours=31), status="final", league="extraliga"),
        await _match(db_session, NOW - timedelta(hours=2), league="extraliga"),
        await _match(db_session, NOW + timedelta(hours=6), league="extraliga"),
    ]
    assert set(_ids(await player_match_list(db_session, ME, now=NOW, league="extraliga"))) == set(xl)
    assert set(_ids(await player_match_list(db_session, ME, now=NOW, league="khl"))) == set(khl)
    assert set(_ids(await player_match_list(db_session, ME, now=NOW))) == set(khl + xl)


@pytest.mark.asyncio
async def test_cancelled_match_stays_only_where_i_made_a_move(db_session) -> None:
    mine_ahead = await _match(db_session, NOW + timedelta(days=1), status="cancelled")
    mine_past = await _match(db_session, NOW - timedelta(days=1), status="cancelled")
    nobody = await _match(db_session, NOW + timedelta(days=2), status="cancelled")
    await _pick(db_session, mine_ahead)
    await _pick(db_session, mine_past)
    ids = set(_ids(await player_match_list(db_session, ME, now=NOW)))
    assert ids == {mine_ahead, mine_past} and nobody not in ids


@pytest.mark.asyncio
async def test_old_match_without_result_is_listed_only_with_my_move(db_session) -> None:
    mine_stuck = await _match(db_session, NOW - timedelta(days=5), league="extraliga")
    other_stuck = await _match(db_session, NOW - timedelta(days=6), league="extraliga")
    await _pick(db_session, mine_stuck)
    page = await player_match_list(db_session, ME, now=NOW)
    assert _ids(page) == [mine_stuck] and other_stuck not in _ids(page)
    row = page["rows"][0]
    assert match_phase(row["status"], row["starts_at"], NOW, has_probe=row["has_probe"]) == "waiting"
    assert match_stale("waiting", row["starts_at"], NOW) is True


@pytest.mark.asyncio
async def test_awaiting_counts_my_started_matches_without_result_only(db_session) -> None:
    live = await _match(db_session, NOW - timedelta(hours=1))
    review = await _match(db_session, NOW - timedelta(hours=6), status="review")
    done = await _match(db_session, NOW - timedelta(hours=9), status="final")
    ahead = await _match(db_session, NOW + timedelta(hours=3))
    stuck = await _match(db_session, NOW - timedelta(days=4))
    foreign = await _match(db_session, NOW - timedelta(hours=2))
    for match_id in (live, review, done, ahead, stuck):
        await _pick(db_session, match_id)
    await _pick(db_session, foreign, OTHER)
    assert await awaiting_count(db_session, ME, now=NOW) == 2
    assert await awaiting_count(db_session, OTHER, now=NOW) == 1
