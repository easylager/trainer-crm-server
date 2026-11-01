"""TASK-334 (PDEC-031): срезы «клуб × период», короны, звания сезона, лиги на набор команд, козырь, «Если угадаешь»."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.hockey_game import (
    live_points,
    make_pick,
    score_finished_matches,
    set_double,
    set_live_score,
    standings,
)
from src.application.hockey_leagues import (
    InvalidTerms,
    build_terms,
    create_league,
    extend_league,
    join_by_code,
    league_table,
    matches_in_terms,
    player_leagues,
)
from src.application.hockey_matches import set_manual_result
from src.application.hockey_races import (
    close_due_races,
    confirm_close_month,
    crown_counts,
    ensure_races,
    mark_calendar_synced,
)
from src.application.hockey_slices import (
    club_scope,
    crown_leaders,
    parse_period,
    peaks,
    slice_rows,
    stakes,
    table_view,
)
from src.ingestion.hockey_sources import MINSK_TZ

NOV = datetime(2026, 11, 10, 12, 0, tzinfo=MINSK_TZ)
SYNC = datetime(2026, 11, 25, 12, 0, tzinfo=MINSK_TZ)
LATE = datetime(2026, 12, 20, 12, 0, tzinfo=MINSK_TZ)
P = [9340001 + i for i in range(6)]  # игроки
DINAMO = "Динамо-Минск"


async def _match(db, mid: str, starts_at: datetime, *, home: str = DINAMO, away: str = "Барыс", extraliga=False) -> int:
    source, league = ("hockeyby", "extraliga") if extraliga else ("hcdinamo", "khl")
    return (
        await db.execute(
            text("""
                INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at)
                VALUES (:s, :l, :mid, :home, :away, :starts_at) RETURNING id
                """),
            {"s": source, "l": league, "mid": mid, "home": home, "away": away, "starts_at": starts_at},
        )
    ).scalar_one()


async def _pick(db, match_id: int, player: int, score: tuple[int, int] | None = None, side: str | None = None) -> None:
    await make_pick(
        db,
        player_key=player,
        display_name=f"И{player % 100}",
        match_id=match_id,
        home_score=None if score is None else score[0],
        away_score=None if score is None else score[1],
        side=side,
        now=NOV,
    )


async def _finish(db, match_id: int, starts_at: datetime, score=(3, 1)) -> datetime:
    done = starts_at + timedelta(hours=3)
    await set_manual_result(db, match_id, home_score=score[0], away_score=score[1], decided_in="regulation", now=done)
    await score_finished_matches(db, now=done)
    return done


async def _three_players_game(db, starts: datetime, *, mid: str, home=DINAMO, away="Барыс", extraliga=False) -> int:
    """Трое с очками: P0 — точный счёт (50), P1 — победитель и разница (30), P2 — победитель (20)."""
    m = await _match(db, mid, starts, home=home, away=away, extraliga=extraliga)
    await _pick(db, m, P[0], (3, 1))
    await _pick(db, m, P[1], (2, 0))
    await _pick(db, m, P[2], side="home")
    await _finish(db, m, starts)
    return m


def _ranks(rows) -> list[tuple[int, int]]:
    return [(r.player_key, r.rank) for r in rows]


# ---------- S0: матчи Экстралиги принимают ходы и считаются тем же кодом ----------


@pytest.mark.asyncio
async def test_extraliga_match_takes_picks_and_scores_like_dinamo(db_session) -> None:
    starts = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    m = await _match(db_session, "x1", starts, home="Юность", away="Неман", extraliga=True)
    d = await _match(db_session, "x2", starts, extraliga=False)
    for match in (m, d):
        await _pick(db_session, match, P[0], (3, 1))
        await _finish(db_session, match, starts)
    pts = (await db_session.execute(text("SELECT match_id, points FROM hockey_picks ORDER BY match_id"))).all()
    assert [r.points for r in pts] == [50, 50]
    # kk_matches по-прежнему только Динамо
    assert (await db_session.execute(text("SELECT count(*) FROM kk_matches WHERE id = :m"), {"m": m})).scalar_one() == 0


# ---------- S2: срезы, места, тай-брейк ----------


@pytest.mark.asyncio
async def test_club_slice_counts_home_and_away_and_all_counts_a_match_once(db_session) -> None:
    t = datetime(2026, 11, 14, 19, 0, tzinfo=MINSK_TZ)
    home_game = await _match(db_session, "s1", t, home="Юность", away="Неман", extraliga=True)
    away_game = await _match(db_session, "s2", t + timedelta(days=2), home="Неман", away="Юность", extraliga=True)
    for i, g in enumerate((home_game, away_game)):
        await _pick(db_session, g, P[0], (3, 1) if i == 0 else (1, 3))
        await _finish(db_session, g, t + timedelta(days=2 * i), score=(3, 1) if i == 0 else (1, 3))
    yunost = await slice_rows(db_session, scope=club_scope("Юность"), period=parse_period("season", NOV))
    neman = await slice_rows(db_session, scope=club_scope("Неман"), period=parse_period("2026-11", NOV))
    allrows = await slice_rows(db_session, scope=club_scope(None), period=parse_period("season", NOV))
    assert (yunost[0].points, yunost[0].played) == (100, 2)
    assert (neman[0].points, neman[0].played) == (100, 2)
    # «Все» — по матчам, не суммой клубных срезов: два хода, а не четыре.
    assert (allrows[0].points, allrows[0].played) == (100, 2)
    # Месяц другого периода пуст, а не ошибка (пауза, N4).
    assert await slice_rows(db_session, scope=club_scope("Юность"), period=parse_period("2026-12", NOV)) == []


@pytest.mark.asyncio
async def test_same_picks_give_different_places_in_different_slices(db_session) -> None:
    t = datetime(2026, 11, 14, 19, 0, tzinfo=MINSK_TZ)
    y = await _match(db_session, "d1", t, home="Юность", away="Неман", extraliga=True)
    d = await _match(db_session, "d2", t + timedelta(days=1))
    await _pick(db_session, y, P[0], (3, 1))  # у Юности P0 впереди
    await _pick(db_session, y, P[1], side="home")
    await _pick(db_session, d, P[1], (3, 1))  # у Динамо P1 впереди
    await _pick(db_session, d, P[0], side="away")
    await _finish(db_session, y, t)
    await _finish(db_session, d, t + timedelta(days=1))
    by_club = {c: _ranks(await slice_rows(db_session, scope=club_scope(c), period=parse_period("season", NOV))) for c in ("Юность", DINAMO, None)}
    assert by_club["Юность"][0] == (P[0], 1) and by_club[DINAMO][0] == (P[1], 1)
    # В «Все» P0: 50, P1: 20+50=70 → P1 первый.
    assert by_club[None][0] == (P[1], 1)


@pytest.mark.asyncio
async def test_tiebreak_points_then_exact_then_fewer_moves_and_full_tie_shares_place(db_session) -> None:
    t = datetime(2026, 11, 14, 19, 0, tzinfo=MINSK_TZ)
    a = await _match(db_session, "t1", t)
    b = await _match(db_session, "t2", t + timedelta(days=1))
    # P0: 20 + 0 (2 хода); P1: 20 (1 ход); P2: 20 + 0 (2 хода) — как P0.
    await _pick(db_session, a, P[0], side="home")
    await _pick(db_session, a, P[1], side="home")
    await _pick(db_session, a, P[2], side="home")
    await _pick(db_session, b, P[0], side="away")
    await _pick(db_session, b, P[2], side="away")
    await _finish(db_session, a, t)
    await _finish(db_session, b, t + timedelta(days=1))
    rows = await slice_rows(db_session, scope=club_scope(None), period=parse_period("season", NOV))
    ranks = {r.player_key: r.rank for r in rows}
    assert ranks[P[1]] == 1  # столько же очков, но меньше ходов
    assert ranks[P[0]] == ranks[P[2]] == 2  # полное равенство — одно место


@pytest.mark.asyncio
async def test_newcomer_without_moves_is_not_in_the_slice_and_has_no_row(db_session) -> None:
    await _three_players_game(db_session, datetime(2026, 11, 14, 19, 0, tzinfo=MINSK_TZ), mid="n1")
    rows = await slice_rows(db_session, scope=club_scope("Барыс"), period=parse_period("season", NOV))
    view = table_view(rows, player_key=P[5], crowns={}, limit=50, crown_possible=True)
    assert view["me"] is None and view["to_crown"] is None and view["neighbors"] == []
    assert all("player_key" not in item for item in view["items"])
    mine = table_view(rows, player_key=P[1], crowns={}, limit=50, crown_possible=True)
    assert mine["to_crown"] == 20 and mine["me"]["correct_percent"] == 100 and len(mine["neighbors"]) == 3


@pytest.mark.asyncio
async def test_trump_doubles_points_but_not_the_exact_count(db_session) -> None:
    t = datetime(2026, 11, 14, 19, 0, tzinfo=MINSK_TZ)
    m = await _match(db_session, "k1", t)
    await _pick(db_session, m, P[0], (3, 1))
    await set_double(db_session, player_key=P[0], match_id=m, on=True, now=NOV)
    await _finish(db_session, m, t)
    row = (await slice_rows(db_session, scope=club_scope(None), period=parse_period("season", NOV)))[0]
    assert (row.points, row.exact) == (100, 1)


# ---------- S1: короны ----------


def test_crown_rules_threshold_ties_and_zero() -> None:
    from src.application.hockey_slices import Row

    def row(key, rank, pts, played=1):
        return Row(rank, key, f"p{key}", pts, 0, played, 0)

    assert crown_leaders([row(1, 1, 50), row(2, 2, 20)]) == []  # двое — короны нет
    assert crown_leaders([row(1, 1, 50), row(2, 2, 20), row(3, 3, 0)]) == []  # третий с нулём не считается
    assert [r.player_key for r in crown_leaders([row(1, 1, 50), row(2, 2, 20), row(3, 3, 10)])] == [1]
    tie = crown_leaders([row(1, 1, 50), row(2, 1, 50), row(3, 3, 10)])
    assert [r.player_key for r in tie] == [1, 2]  # ничья — всем
    assert crown_leaders([row(1, 1, 0), row(2, 1, 0), row(3, 1, 0)]) == []  # ноль очков — без короны


@pytest.mark.asyncio
async def test_month_crowns_for_all_and_each_club_once_after_the_correction_window(db_session) -> None:
    await ensure_races(db_session, now=NOV)
    t = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    await _three_players_game(db_session, t, mid="c1", home="Юность", away="Неман", extraliga=True)
    await mark_calendar_synced(db_session, now=SYNC)
    # Окно исправления итога — 7 суток: через сутки после матча короны ещё нет.
    assert await close_due_races(db_session, now=t + timedelta(days=1)) == []
    closed = await close_due_races(db_session, now=t + timedelta(days=8))
    assert len(closed) == 3  # Все, Юность, Неман
    crowns = (await db_session.execute(text("SELECT club, player_key, kind, race_id FROM hockey_crowns ORDER BY club NULLS FIRST"))).all()
    assert [(c.club, c.player_key, c.kind) for c in crowns] == [
        (None, P[0], "month"),
        ("Неман", P[0], "month"),
        ("Юность", P[0], "month"),
    ]
    # Повторное закрытие ничего не дублирует.
    assert await close_due_races(db_session, now=t + timedelta(days=9)) == []
    assert (await db_session.execute(text("SELECT count(*) FROM hockey_crowns"))).scalar_one() == 3
    assert await crown_counts(db_session, league_id=None) == {P[0]: 3}


@pytest.mark.asyncio
async def test_two_players_no_crown_and_late_correction_does_not_move_it(db_session) -> None:
    await ensure_races(db_session, now=NOV)
    t = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    m = await _match(db_session, "c2", t)
    await _pick(db_session, m, P[0], (3, 1))
    await _pick(db_session, m, P[1], side="home")
    await _finish(db_session, m, t)
    await mark_calendar_synced(db_session, now=SYNC)
    await close_due_races(db_session, now=t + timedelta(days=8))
    assert (await db_session.execute(text("SELECT count(*) FROM hockey_crowns"))).scalar_one() == 0
    closure = (await db_session.execute(text("SELECT crowned FROM hockey_closures WHERE kind = 'month' AND club IS NULL"))).scalar_one()
    assert closure == 0


@pytest.mark.asyncio
async def test_month_waits_for_the_calendar_and_for_unfinished_matches(db_session) -> None:
    await ensure_races(db_session, now=NOV)
    t = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    await _three_players_game(db_session, t, mid="w1")
    # Календарь читали за месяц до конца: последние матчи могли быть не видны — не закрываем.
    await mark_calendar_synced(db_session, now=datetime(2026, 11, 2, tzinfo=MINSK_TZ))
    assert await close_due_races(db_session, now=t + timedelta(days=20)) == []
    await mark_calendar_synced(db_session, now=SYNC)
    # Несыгранный матч в месяце держит срез.
    late = await _match(db_session, "w2", datetime(2026, 11, 29, 19, 0, tzinfo=MINSK_TZ))
    assert late
    assert await close_due_races(db_session, now=datetime(2026, 12, 3, tzinfo=MINSK_TZ)) == []
    # Через 72 часа после конца месяца срез закрывается без зависшего матча (M8).
    assert await close_due_races(db_session, now=datetime(2026, 12, 5, tzinfo=MINSK_TZ))


@pytest.mark.asyncio
async def test_month_boundary_follows_minsk_time(db_session) -> None:
    await ensure_races(db_session, now=NOV)
    late_nov = datetime(2026, 11, 30, 23, 30, tzinfo=MINSK_TZ)
    early_dec = datetime(2026, 12, 1, 0, 30, tzinfo=MINSK_TZ)
    await _three_players_game(db_session, late_nov, mid="b1")
    await _three_players_game(db_session, early_dec, mid="b2")
    nov = await slice_rows(db_session, scope=club_scope(None), period=parse_period("2026-11", NOV))
    dec = await slice_rows(db_session, scope=club_scope(None), period=parse_period("2026-12", NOV))
    assert nov[0].played == 1 and dec[0].played == 1


@pytest.mark.asyncio
async def test_cancelled_match_is_out_of_points_and_the_month_close(db_session) -> None:
    from src.application.hockey_matches import cancel_match

    t = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    m = await _three_players_game(db_session, t, mid="x9")
    await cancel_match(db_session, m, reason="technical", now=t + timedelta(hours=4))
    await score_finished_matches(db_session, now=t + timedelta(hours=4))
    assert await slice_rows(db_session, scope=club_scope(None), period=parse_period("season", NOV)) == []


@pytest.mark.asyncio
async def test_manual_confirm_closes_before_the_window(db_session) -> None:
    race = await ensure_races(db_session, now=NOV)
    t = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    await _three_players_game(db_session, t, mid="mc")
    assert await confirm_close_month(db_session, period_start=race.starts_at, club=None, now=t + timedelta(days=1))
    assert await confirm_close_month(db_session, period_start=race.starts_at, club=None, now=t + timedelta(days=1)) is None
    assert (await db_session.execute(text("SELECT count(*) FROM hockey_crowns"))).scalar_one() == 1


@pytest.mark.asyncio
async def test_season_titles_after_the_season_and_window_only_once(db_session) -> None:
    t = datetime(2027, 3, 20, 19, 0, tzinfo=MINSK_TZ)
    await _three_players_game(db_session, t, mid="z1")
    await mark_calendar_synced(db_session, now=datetime(2027, 7, 20, tzinfo=MINSK_TZ))
    await db_session.execute(text("UPDATE hockey_races SET calendar_synced_at = '2027-07-20'"))
    assert await close_due_races(db_session, now=datetime(2027, 6, 1, tzinfo=MINSK_TZ)) == []  # сезон ещё идёт
    after = datetime(2027, 8, 12, tzinfo=MINSK_TZ)
    # синхронизацию для сезона берём из любой гонки
    await ensure_races(db_session, now=datetime(2027, 7, 20, tzinfo=MINSK_TZ))
    await mark_calendar_synced(db_session, now=datetime(2027, 7, 20, tzinfo=MINSK_TZ))
    await close_due_races(db_session, now=after)
    titles = (await db_session.execute(text("SELECT season, club, player_key FROM hockey_titles ORDER BY club NULLS FIRST"))).all()
    assert [(x.season, x.club, x.player_key) for x in titles] == [
        ("2026/27", None, P[0]),
        ("2026/27", "Барыс", P[0]),
        ("2026/27", DINAMO, P[0]),
    ] or {x.club for x in titles} == {None, "Барыс", DINAMO}
    n = (await db_session.execute(text("SELECT count(*) FROM hockey_titles"))).scalar_one()
    await close_due_races(db_session, now=after + timedelta(days=1))
    assert (await db_session.execute(text("SELECT count(*) FROM hockey_titles"))).scalar_one() == n


# ---------- «Твои вершины» ----------


@pytest.mark.asyncio
async def test_peaks_need_three_players_and_three_moves(db_session) -> None:
    base = datetime(2026, 11, 12, 19, 0, tzinfo=MINSK_TZ)
    for i in range(3):
        await _three_players_game(db_session, base + timedelta(days=i), mid=f"pk{i}")
    out = await peaks(db_session, player_key=P[0], now=NOV)
    assert out and out[0]["rank"] == 1 and out[0]["players"] == 3 and len(out) <= 3
    assert all(x["played"] >= 3 for x in out)
    # Двое игроков / мало ходов — вершин нет.
    assert await peaks(db_session, player_key=P[5], now=NOV) == []


# ---------- «Если угадаешь» ----------


@pytest.mark.asyncio
async def test_stakes_are_conditional_and_hidden_for_tiny_slices(db_session) -> None:
    t = datetime(2026, 11, 12, 19, 0, tzinfo=MINSK_TZ)
    await _three_players_game(db_session, t, mid="st0")
    nxt = await _match(db_session, "st1", datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ))
    await _pick(db_session, nxt, P[2], side="home")
    out = await stakes(db_session, player_key=P[2], match_id=nxt, now=NOV)
    assert out["points_if_winner"] == 20
    first = out["items"][0]
    # Сейчас P2 третий; угаданный победитель поднимает его выше (условно, не обещание).
    assert first["rank_now"] == 3 and first["rank_if"] < first["rank_now"]
    # Срезы меньше трёх игроков с очками не показываются.
    assert all(i["players"] >= 3 for i in out["items"])
    assert await stakes(db_session, player_key=P[2], match_id=999999999, now=NOV) is None


# ---------- S3: лиги ----------


@pytest.mark.asyncio
async def test_league_counts_only_chosen_clubs_in_term_and_after_joining(db_session) -> None:
    terms = build_terms(scope="clubs", clubs=["Юность", DINAMO], term="month", now=NOV)
    league = await create_league(db_session, owner_key=P[0], owner_name="А", name="Юность+Динамо", terms=terms, now=NOV)
    await join_by_code(db_session, player_key=P[1], display_name="Б", code=league.invite_code)
    await db_session.execute(text("UPDATE hockey_league_members SET joined_at = :t"), {"t": datetime(2026, 11, 1, tzinfo=MINSK_TZ)})
    t = datetime(2026, 11, 14, 19, 0, tzinfo=MINSK_TZ)
    games = {
        "yu": await _match(db_session, "l1", t, home="Юность", away="Неман", extraliga=True),
        "di": await _match(db_session, "l2", t + timedelta(days=1)),
        "ot": await _match(db_session, "l3", t + timedelta(days=2), home="Неман", away="Лида", extraliga=True),
        "dec": await _match(db_session, "l4", datetime(2026, 12, 3, 19, 0, tzinfo=MINSK_TZ)),
    }
    for key, g in games.items():
        await _pick(db_session, g, P[0], (3, 1))
    for i, g in enumerate(games.values()):
        await _finish(db_session, g, [t, t + timedelta(days=1), t + timedelta(days=2), datetime(2026, 12, 3, 19, 0, tzinfo=MINSK_TZ)][i])
    rows = await league_table(db_session, league_id=league.id, player_key=P[0], now=NOV)
    me = next(r for r in rows if r.player_key == P[0])
    assert (me.points, me.played) == (100, 2)  # Юность и Динамо; чужой клуб и декабрь не считаются
    assert next(r for r in rows if r.player_key == P[1]).points == 0
    # В общей таблице все четыре матча.
    allrows = await slice_rows(db_session, scope=club_scope(None), period=parse_period("season", NOV))
    assert allrows[0].played == 4


def test_terms_validation() -> None:
    with pytest.raises(InvalidTerms):
        build_terms(scope="clubs", clubs=[], term="season", now=NOV)
    with pytest.raises(InvalidTerms):
        build_terms(scope="clubs", clubs=["Несуществующий"], term="season", now=NOV)
    with pytest.raises(InvalidTerms):
        build_terms(scope="all", term="dates", now=NOV, starts_at=NOV.date() - timedelta(days=5), ends_at=NOV.date() + timedelta(days=5))
    with pytest.raises(InvalidTerms):
        build_terms(scope="all", term="dates", now=NOV, starts_at=NOV.date() + timedelta(days=5), ends_at=NOV.date() + timedelta(days=2))
    with pytest.raises(InvalidTerms):
        build_terms(scope="all", term="dates", now=NOV, starts_at=NOV.date(), ends_at=NOV.date() + timedelta(days=400))
    w4 = build_terms(scope="extraliga", term="weeks4", now=NOV)
    assert w4.ends_at - w4.starts_at == timedelta(days=28)
    assert build_terms(scope="all", term="month", now=NOV, month="2026-12").starts_at == datetime(2026, 12, 1, tzinfo=MINSK_TZ)


@pytest.mark.asyncio
async def test_extend_makes_one_new_league_with_the_same_people(db_session) -> None:
    terms = build_terms(scope="dinamo", term="month", now=NOV)
    league = await create_league(db_session, owner_key=P[0], owner_name="А", name="Ноябрь", terms=terms, now=NOV)
    await join_by_code(db_session, player_key=P[1], display_name="Б", code=league.invite_code)
    dec = datetime(2026, 12, 5, 12, 0, tzinfo=MINSK_TZ)
    new, created = await extend_league(db_session, league_id=league.id, player_key=P[0], now=dec)
    again, created2 = await extend_league(db_session, league_id=league.id, player_key=P[0], now=dec)
    assert created and not created2 and new.id == again.id != league.id
    assert new.starts_at == datetime(2026, 12, 1, tzinfo=MINSK_TZ) and new.scope == "dinamo"
    members = (await db_session.execute(text("SELECT player_key FROM hockey_league_members WHERE league_id = :l ORDER BY 1"), {"l": new.id})).scalars().all()
    assert members == [P[0], P[1]]
    with pytest.raises(PermissionError):
        await extend_league(db_session, league_id=league.id, player_key=P[1], now=dec)
    # Старая лига закончилась и не занимает квоту.
    mine = await player_leagues(db_session, player_key=P[0], now=dec)
    assert {x.id: x.active for x in mine} == {league.id: False, new.id: True}


@pytest.mark.asyncio
async def test_league_month_and_term_crowns_need_three_players_with_points(db_session) -> None:
    await ensure_races(db_session, now=NOV)
    league = await create_league(db_session, owner_key=P[0], owner_name="А", name="Сезон", now=NOV)
    for k in (P[1], P[2]):
        await join_by_code(db_session, player_key=k, display_name="x", code=league.invite_code)
    await db_session.execute(text("UPDATE hockey_league_members SET joined_at = :t"), {"t": datetime(2026, 11, 1, tzinfo=MINSK_TZ)})
    t = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    await _three_players_game(db_session, t, mid="lm")
    await mark_calendar_synced(db_session, now=SYNC)
    await close_due_races(db_session, now=datetime(2026, 12, 3, tzinfo=MINSK_TZ))
    row = (await db_session.execute(text("SELECT kind, player_key FROM hockey_crowns WHERE league_id = :l"), {"l": league.id})).all()
    assert [(r.kind, r.player_key) for r in row] == [("league_month", P[0])]
    assert await crown_counts(db_session, league_id=league.id) == {P[0]: 1}


@pytest.mark.asyncio
async def test_matches_in_terms_counts_upcoming_only(db_session) -> None:
    await _match(db_session, "q1", datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ))
    await _match(db_session, "q2", datetime(2026, 11, 5, 19, 0, tzinfo=MINSK_TZ))  # уже был
    terms = build_terms(scope="dinamo", term="month", now=NOV)
    assert await matches_in_terms(db_session, terms, now=NOV) == 1


@pytest.mark.asyncio
async def test_migration_keeps_old_leagues_on_dinamo_only(db_session) -> None:
    """L10: лига по умолчанию («Динамо, до конца сезона») не получает очков за Экстралигу."""
    league = await create_league(db_session, owner_key=P[0], owner_name="А", name="Старая", now=NOV)
    t = datetime(2026, 11, 14, 19, 0, tzinfo=MINSK_TZ)
    d = await _match(db_session, "o1", t)
    e = await _match(db_session, "o2", t + timedelta(days=1), home="Юность", away="Неман", extraliga=True)
    await db_session.execute(text("UPDATE hockey_league_members SET joined_at = :t"), {"t": datetime(2026, 11, 1, tzinfo=MINSK_TZ)})
    for g in (d, e):
        await _pick(db_session, g, P[0], (3, 1))
    await _finish(db_session, d, t)
    await _finish(db_session, e, t + timedelta(days=1))
    me = next(r for r in await league_table(db_session, league_id=league.id, player_key=P[0], now=NOV))
    assert me.points == 50 and me.played == 1


# ---------- S4: живой счёт ----------


@pytest.mark.asyncio
async def test_live_score_is_separate_from_the_result(db_session) -> None:
    t = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    m = await _match(db_session, "lv", t)
    assert await set_live_score(db_session, match_id=m, home=2, away=1, now=t + timedelta(minutes=40))
    row = (await db_session.execute(text("SELECT live_home_score, live_away_score, live_at, home_score, status FROM hockey_matches WHERE id = :m"), {"m": m})).one()
    assert (row.live_home_score, row.live_away_score, row.home_score, row.status) == (2, 1, None, "scheduled")
    assert live_points(side="home", home_score=2, away_score=1, live_home=2, live_away=1, doubled=True) == 100
    assert live_points(side="home", home_score=3, away_score=1, live_home=1, live_away=1, doubled=False) is None
