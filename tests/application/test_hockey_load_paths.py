"""Нагрузка «Кто кого»: счётчики сторон, кэш срезов, лиги игрока, короны, чистка уведомлений."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.hockey_game import make_pick, player_matches, score_finished_matches
from src.application.hockey_leagues import create_league, player_leagues, build_terms
from src.application.hockey_matches import set_manual_result
from src.application.hockey_notices import cleanup_old_notices
from src.application.hockey_slices import (
    club_scope,
    crown_totals,
    season_period,
    shown_keys,
    slice_row_of,
    slice_rows,
    slice_rows_cached,
)

A, B, C, D = 9300001, 9300002, 9300003, 9300004


async def _match(db, starts_at, *, home="Динамо-Минск", away="Барыс") -> int:
    return int(
        (
            await db.execute(
                text("""
                    INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at)
                    VALUES ('hcdinamo', 'khl', :mid, :h, :a, :t) RETURNING id
                    """),
                {"mid": uuid.uuid4().hex, "h": home, "a": away, "t": starts_at},
            )
        ).scalar_one()
    )


async def _play(db, match_id, who, side, *, now):
    await make_pick(db, player_key=who, display_name=f"И{who % 100}", match_id=match_id, side=side, now=now)


@pytest.mark.asyncio
async def test_player_matches_counts_sides_per_match(db_session) -> None:
    now = datetime.now(timezone.utc)
    m1 = await _match(db_session, now + timedelta(days=1))
    m2 = await _match(db_session, now + timedelta(days=2))
    m3 = await _match(db_session, now + timedelta(days=3))
    for who, side in ((A, "home"), (B, "home"), (C, "away")):
        await _play(db_session, m1, who, side, now=now)
    await _play(db_session, m2, A, "away", now=now)

    rows = await player_matches(db_session, A, since=now, limit=20)
    by_id = {r["id"]: r for r in rows}
    assert (by_id[m1]["home_picks"], by_id[m1]["away_picks"], by_id[m1]["pick_side"]) == (2, 1, "home")
    assert (by_id[m2]["home_picks"], by_id[m2]["away_picks"]) == (0, 1)
    assert (by_id[m3]["home_picks"], by_id[m3]["away_picks"], by_id[m3]["pick_side"]) == (0, 0, None)


@pytest.mark.asyncio
async def test_player_matches_empty_list(db_session) -> None:
    far = datetime.now(timezone.utc) + timedelta(days=3650)
    assert await player_matches(db_session, A, since=far, limit=20) == []


async def _scored_season_match(db, now):
    start = now - timedelta(days=2)
    match = await _match(db, start)
    for who, score in ((A, (3, 1)), (B, (2, 0)), (C, (1, 2))):
        await make_pick(
            db,
            player_key=who,
            display_name=f"И{who % 100}",
            match_id=match,
            home_score=score[0],
            away_score=score[1],
            now=start - timedelta(days=1),
        )
    await set_manual_result(db, match, home_score=3, away_score=1, decided_in="regulation", now=now)
    await score_finished_matches(db, now=now)
    return match


@pytest.mark.asyncio
async def test_cached_slice_equals_direct_and_row_lookup(db_session) -> None:
    now = datetime.now(timezone.utc)
    await _scored_season_match(db_session, now)
    scope, period = club_scope(None), season_period(now)
    direct = await slice_rows(db_session, scope=scope, period=period)
    cached = await slice_rows_cached(db_session, scope=scope, period=period)
    assert cached == direct and len(direct) == 3
    for row in direct:
        assert await slice_row_of(db_session, scope=scope, period=period, player_key=row.player_key) == row
    assert await slice_row_of(db_session, scope=scope, period=period, player_key=D) is None


@pytest.mark.asyncio
async def test_cache_is_dropped_when_points_are_scored(db_session) -> None:
    now = datetime.now(timezone.utc)
    scope, period = club_scope(None), season_period(now)
    assert await slice_rows_cached(db_session, scope=scope, period=period) == []  # закэшировали пустой срез
    await _scored_season_match(db_session, now)  # score_finished_matches сбрасывает кэш
    assert len(await slice_rows_cached(db_session, scope=scope, period=period)) == 3


@pytest.mark.asyncio
async def test_unknown_club_slice_is_not_cached(db_session) -> None:
    from src.application.hockey_cache import aggregates

    now = datetime.now(timezone.utc)
    await slice_rows_cached(db_session, scope=club_scope("Выдуманный-" + uuid.uuid4().hex), period=season_period(now))
    assert len(aggregates) == 0


@pytest.mark.asyncio
async def test_crown_totals_only_for_requested_players(db_session) -> None:
    now = datetime.now(timezone.utc)
    for who in (A, B):
        await db_session.execute(
            text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, 'x') ON CONFLICT DO NOTHING"),
            {"k": who},
        )
    for who, kind_club in ((A, "x1"), (A, "x2"), (B, "x3")):
        await db_session.execute(
            text("""
                INSERT INTO hockey_crowns (player_key, points, exact, kind, period_start, period_end, club)
                VALUES (:k, 10, 0, 'month', :s, :e, :c)
                """),
            {"k": who, "s": now - timedelta(days=60), "e": now - timedelta(days=30), "c": kind_club},
        )
    assert await crown_totals(db_session, player_keys=[A]) == {A: 2}
    assert await crown_totals(db_session, player_keys=[]) == {}
    everyone = await crown_totals(db_session)
    assert everyone[A] == 2 and everyone[B] == 1


def test_shown_keys_cover_top_me_and_neighbors() -> None:
    from src.application.hockey_slices import Row

    rows = [Row(i, 100 + i, f"n{i}", 100 - i, 0, 1, 1) for i in range(1, 11)]
    assert shown_keys(rows, None, limit=3) == {101, 102, 103}
    assert shown_keys(rows, 108, limit=3) == {101, 102, 103, 106, 107, 108, 109, 110}
    assert shown_keys(rows, 999, limit=2) == {101, 102}


async def _league_ending(db, owner, *, now, name, ends_in_days, member=None):
    terms = build_terms(scope="all", term="season", now=now)
    league = await create_league(db, owner_key=owner, owner_name="Овнер", name=name, terms=terms, now=now)
    await db.execute(
        text("UPDATE hockey_leagues SET starts_at = :s, ends_at = :e WHERE id = :id"),
        {"s": now - timedelta(days=200), "e": now + timedelta(days=ends_in_days), "id": league.id},
    )
    return league


@pytest.mark.asyncio
async def test_player_leagues_window_ids_and_no_rank(db_session) -> None:
    now = datetime.now(timezone.utc)
    live = await _league_ending(db_session, A, now=now, name="Идёт", ends_in_days=10)
    fresh = await _league_ending(db_session, A, now=now, name="Недавно", ends_in_days=-5)
    stale = await _league_ending(db_session, A, now=now, name="Давно", ends_in_days=-120)

    default = await player_leagues(db_session, player_key=A, now=now)
    assert {x.id for x in default} == {live.id, fresh.id}
    assert [x.active for x in sorted(default, key=lambda x: x.id)] == [True, False]
    assert all(x.my_rank == 1 for x in default)

    only_active = await player_leagues(db_session, player_key=A, now=now, ends_after=now)
    assert [x.id for x in only_active] == [live.id]

    explicit = await player_leagues(db_session, player_key=A, now=now, league_ids=[stale.id], ends_after=None)
    assert [x.id for x in explicit] == [stale.id]
    # без места таблица не считается
    bare = await player_leagues(db_session, player_key=A, now=now, league_ids=[live.id], with_rank=False)
    assert (bare[0].my_rank, bare[0].my_points, bare[0].members) == (None, None, 1)

    # starts_by: ещё не начавшаяся на момент at лига не попадает
    future = await _league_ending(db_session, A, now=now, name="Будущая", ends_in_days=40)
    await db_session.execute(
        text("UPDATE hockey_leagues SET starts_at = :s WHERE id = :id"), {"s": now + timedelta(days=5), "id": future.id}
    )
    at_now = await player_leagues(db_session, player_key=A, now=now, ends_after=now, starts_by=now)
    assert [x.id for x in at_now] == [live.id]


@pytest.mark.asyncio
async def test_player_leagues_limit_keeps_live_ones_in_join_order(db_session) -> None:
    now = datetime.now(timezone.utc)
    ended = [await _league_ending(db_session, A, now=now, name=f"К{i}", ends_in_days=-1 - i) for i in range(3)]
    live = await _league_ending(db_session, A, now=now, name="Живая", ends_in_days=5)
    got = await player_leagues(db_session, player_key=A, now=now, limit=2, with_rank=False)
    assert live.id in {x.id for x in got}  # идущая не вытеснена закончившимися
    assert [x.id for x in got] == sorted(x.id for x in got)  # порядок вступления сохранён
    assert len(got) == 2 and ended


@pytest.mark.asyncio
async def test_cleanup_old_notices_batches_and_keeps_queue(db_session) -> None:
    import src.application.hockey_notices as notices

    now = datetime.now(timezone.utc)
    match = await _match(db_session, now + timedelta(days=1))
    await db_session.execute(
        text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, 'x') ON CONFLICT DO NOTHING"),
        {"k": A},
    )
    old, recent = now - timedelta(days=90), now - timedelta(days=5)
    rows = [
        ("before", old, False),  # старая отправленная — уйдёт
        ("result", recent, False),  # свежая — останется
        ("nomove", None, True),  # упавшая, создана давно — уйдёт
        ("moved", None, False),  # в очереди — остаётся при любом возрасте
        ("lginvite", old, False),  # память серии приглашений — не чистится, иначе серия начнётся заново
        ("consent", old, False),  # «согласие уже спрашивали» — тоже память
    ]
    for kind, sent_at, failed in rows:
        created = old if kind != "result" else recent
        await db_session.execute(
            text("""
                INSERT INTO hockey_notices (player_key, match_id, kind, sent_at, failed, created_at)
                VALUES (:k, :m, :kind, :sent, :failed, :created)
                """),
            {
                "k": A,
                "m": match,
                "kind": kind,
                "sent": sent_at if kind not in ("before",) else old,
                "failed": failed,
                "created": created,
            },
        )

    class Factory:
        def __call__(self):
            return _Ctx(db_session)

    class _Ctx:
        def __init__(self, s):
            self.s = s

        async def __aenter__(self):
            return self.s

        async def __aexit__(self, *a):
            return False

    notices._last_cleanup = None
    deleted = await cleanup_old_notices(Factory(), now=now)
    assert deleted == 2
    left = set(
        (await db_session.execute(text("SELECT kind FROM hockey_notices WHERE player_key = :k"), {"k": A})).scalars()
    )
    assert left == {"result", "moved", "lginvite", "consent"}
    # второй вызов в пределах 6 часов ничего не делает
    assert await cleanup_old_notices(Factory(), now=now + timedelta(hours=1)) == 0
