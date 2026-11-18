"""«Вечер» лиги по живой базе (TASK-431): игровой день по Минску, матчи набора лиги, ходы после вступления."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.hockey_league_evening import default_day, league_evening, visible_days
from src.application.hockey_leagues import member_league

# Среда 18.11.2026, 21:00 по Минску.
NOW = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc)
ME, ANYA, SASHA, LATE = 880_431_101, 880_431_102, 880_431_103, 880_431_104


async def _match(db, home: str, away: str, starts_at: datetime, *, status: str = "final", score=(3, 1)) -> int:
    source, league = ("hcdinamo", "khl") if "Динамо-Минск" in (home, away) else ("hockeyby", "extraliga")
    final = status == "final"
    return int(
        (
            await db.execute(
                text("""INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at, status,
                                                    home_score, away_score, decided_in, result_source)
                        VALUES (:src, :lg, :mid, :h, :a, :t, :st, :hs, :as_, :din, :rs) RETURNING id"""),
                {
                    "src": source,
                    "lg": league,
                    "mid": uuid.uuid4().hex,
                    "h": home,
                    "a": away,
                    "t": starts_at,
                    "st": status,
                    "hs": score[0] if final else None,
                    "as_": score[1] if final else None,
                    "din": "regulation" if final else None,
                    "rs": "auto" if final else None,
                },
            )
        ).scalar_one()
    )


async def _pick(db, player: int, match_id: int, side: str, *, points: int | None = None, score=None) -> None:
    await db.execute(
        text("""INSERT INTO hockey_picks (player_key, match_id, side, points, home_score, away_score)
                VALUES (:p, :m, :s, :pts, :hs, :as_)"""),
        {
            "p": player,
            "m": match_id,
            "s": side,
            "pts": points,
            "hs": score[0] if score else None,
            "as_": score[1] if score else None,
        },
    )


async def _league(db, *, scope: str = "all", clubs: tuple[str, ...] = (), members=(ME, ANYA, SASHA)) -> int:
    names = {ME: "Макс", ANYA: "Аня", SASHA: "Саша", LATE: "Поздний"}
    for key in members:
        await db.execute(
            text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, :n) ON CONFLICT DO NOTHING"),
            {"k": key, "n": names[key]},
        )
    league_id = (
        await db.execute(
            text("""INSERT INTO hockey_leagues (name, invite_code, owner_key, scope, clubs, term_kind, starts_at, ends_at)
                    VALUES ('Бригада', :code, :o, :scope, :clubs, 'season', :s, :e) RETURNING id"""),
            {
                "code": uuid.uuid4().hex[:8].upper(),
                "o": ME,
                "scope": scope,
                "clubs": list(clubs),
                "s": NOW - timedelta(days=30),
                "e": NOW + timedelta(days=100),
            },
        )
    ).scalar_one()
    for key in members:
        await db.execute(
            text("INSERT INTO hockey_league_members (league_id, player_key, joined_at) VALUES (:l, :k, :j)"),
            {"l": league_id, "k": key, "j": NOW - timedelta(days=20)},
        )
    return int(league_id)


async def _evening(db, league_id: int, *, day: date | None = None, me: int = ME, now: datetime = NOW) -> dict:
    league = await member_league(db, league_id=league_id, player_key=me)
    return await league_evening(db, league=league, player_key=me, now=now, day=day)


def test_visible_days_stop_today_and_new_league_sees_its_first_day() -> None:
    d = [date(2026, 11, 16), date(2026, 11, 18), date(2026, 11, 20)]
    assert visible_days(d, date(2026, 11, 18)) == d[:2]
    assert default_day(d, date(2026, 11, 18)) == date(2026, 11, 18)
    assert default_day(d, date(2026, 11, 19)) == date(2026, 11, 18)  # сегодня матчей нет — последний день с матчами
    assert visible_days(d, date(2026, 11, 1)) == [date(2026, 11, 16)]  # прошедших нет — первый день впереди
    assert default_day([], date(2026, 11, 18)) is None


@pytest.mark.asyncio
async def test_evening_is_the_minsk_game_day_of_league_matches(db_session) -> None:
    db = db_session
    league_id = await _league(db, scope="extraliga")
    # 00:30 18.11 по Минску — это ещё 17.11 по UTC, а игровой день — 18-е.
    night = await _match(db, "Брест", "Витебск", datetime(2026, 11, 17, 21, 30, tzinfo=timezone.utc))
    a = await _match(db, "Юность-Минск", "Неман", NOW - timedelta(hours=3))
    b = await _match(db, "Гомель", "Шахтёр", NOW - timedelta(hours=1), score=(2, 3))
    await _match(db, "Динамо-Минск", "СКА", NOW - timedelta(hours=2))  # КХЛ: не в наборе лиги
    await _match(db, "Лида", "Металлург", NOW - timedelta(hours=2), status="cancelled")  # отменён: не в дне
    earlier = await _match(db, "Юность-Минск", "Лида", NOW - timedelta(days=2))
    await _pick(db, ME, a, "home", points=50, score=(3, 1))
    await _pick(db, ME, b, "home", points=0)
    await _pick(db, ANYA, a, "home", points=20)
    await _pick(db, ME, earlier, "home", points=20)

    ev = await _evening(db, league_id)
    assert ev["day"] == "2026-11-18"
    assert ev["prev"] == "2026-11-16" and ev["next"] is None
    assert [m["id"] for m in ev["matches"]] == [night, a, b]
    assert ev["complete"] is True
    me = ev["items"][0]
    assert me["is_me"] and me["display_name"] == "Макс"
    assert [x["state"] for x in me["marks"]] == ["none", "hit", "miss"]
    assert (me["hits"], me["moves"], me["points"]) == (1, 2, 50)
    sasha = next(r for r in ev["items"] if r["display_name"] == "Саша")
    assert [x["state"] for x in sasha["marks"]] == ["none", "none", "none"]
    assert "player_key" not in str(ev)

    back = await _evening(db, league_id, day=date(2026, 11, 16))
    assert back["day"] == "2026-11-16" and back["next"] == "2026-11-18" and back["prev"] is None
    # Не день лиги — вечер по умолчанию.
    assert (await _evening(db, league_id, day=date(2026, 11, 17)))["day"] == "2026-11-18"


@pytest.mark.asyncio
async def test_friends_score_and_points_open_only_after_start(db_session) -> None:
    db = db_session
    league_id = await _league(db, scope="clubs", clubs=("Юность-Минск",))
    later = await _match(db, "Юность-Минск", "Неман", NOW + timedelta(hours=1), status="scheduled")
    await _pick(db, ANYA, later, "away", score=(1, 2))
    await _pick(db, ME, later, "home", score=(4, 1))
    ev = await _evening(db, league_id)
    anya = next(r for r in ev["items"] if r["display_name"] == "Аня")
    assert anya["marks"] == [{"match_id": later, "state": "wait", "side": "away"}]
    mine = ev["items"][0]["marks"][0]
    assert (mine["home_score"], mine["away_score"]) == (4, 1)
    assert ev["complete"] is False

    started = await _evening(db, league_id, now=NOW + timedelta(hours=2))
    anya = next(r for r in started["items"] if r["display_name"] == "Аня")
    assert (anya["marks"][0]["home_score"], anya["marks"][0]["away_score"]) == (1, 2)


@pytest.mark.asyncio
async def test_moves_before_joining_do_not_count(db_session) -> None:
    db = db_session
    league_id = await _league(db, scope="all")
    m = await _match(db, "Юность-Минск", "Неман", NOW - timedelta(hours=3))
    await db.execute(text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, 'Поздний')"), {"k": LATE})
    await db.execute(
        text("INSERT INTO hockey_league_members (league_id, player_key, joined_at) VALUES (:l, :k, :j)"),
        {"l": league_id, "k": LATE, "j": NOW - timedelta(hours=1)},
    )
    await _pick(db, LATE, m, "home", points=50)
    ev = await _evening(db, league_id)
    late = next(r for r in ev["items"] if r["display_name"] == "Поздний")
    assert late["marks"][0]["state"] == "none" and late["points"] == 0


@pytest.mark.asyncio
async def test_day_cap_is_worn_until_the_next_played_day(db_session) -> None:
    from src.application.hockey_leagues import league_titles

    db = db_session
    league_id = await _league(db, scope="extraliga")
    d1 = NOW - timedelta(days=2)
    a = await _match(db, "Юность-Минск", "Неман", d1)
    b = await _match(db, "Гомель", "Шахтёр", d1 + timedelta(hours=1))
    for key, pts in ((ME, (50, 20)), (ANYA, (20, 20)), (SASHA, (0, 10))):
        await _pick(db, key, a, "home", points=pts[0])
        await _pick(db, key, b, "home", points=pts[1])
    # Сегодня: один матч сыгран, второй ещё нет — день не решён, кепку носит Саша со вчерашнего дня.
    c = await _match(db, "Юность-Минск", "Лида", NOW - timedelta(hours=3))
    later = await _match(db, "Брест", "Витебск", NOW + timedelta(hours=1), status="scheduled")
    await _pick(db, ME, c, "home", points=0)
    await _pick(db, ANYA, c, "home", points=50)

    old = await _evening(db, league_id, day=game_day_of(d1))
    sasha = next(r for r in old["items"] if r["display_name"] == "Саша")
    assert sasha["cap"] is True and old["cap"]["decided"] and old["cap"]["in_play"]
    assert [r["display_name"] for r in old["items"] if r["cap"]] == ["Саша"]

    today = await _evening(db, league_id)
    assert today["cap"]["decided"] is False and not any(r["cap"] for r in today["items"])
    assert (await league_titles(db, league_id=league_id, now=NOW))[SASHA]["id"] == "cap"

    # Второй матч сыгран: в споре двое (Саша не ходил) — кепка не разыгрывается и со Саши снята.
    await db.execute(
        text(
            "UPDATE hockey_matches SET status = 'final', home_score = 2, away_score = 1, decided_in = 'regulation', result_source = 'auto' WHERE id = :id"
        ),
        {"id": later},
    )
    await _pick(db, ME, later, "home", points=20)
    after = await _evening(db, league_id, now=NOW + timedelta(hours=4))
    assert after["cap"]["decided"] and not after["cap"]["in_play"]
    titles = await league_titles(db, league_id=league_id, now=NOW + timedelta(hours=4))
    assert all(t["id"] != "cap" for t in titles.values())


@pytest.mark.asyncio
async def test_scarf_of_the_day_is_a_move_against_your_own_team(db_session) -> None:
    db = db_session
    league_id = await _league(db, scope="extraliga")
    await db.execute(
        text("INSERT INTO hockey_player_prefs (player_key, fav_club) VALUES (:k, 'Юность-Минск')"), {"k": ANYA}
    )
    m = await _match(db, "Юность-Минск", "Неман", NOW - timedelta(hours=3))
    await _pick(db, ANYA, m, "away", points=0)
    await _pick(db, ME, m, "away", points=0)  # своей команды нет (ходил только сегодня за Неман — он и есть свой)
    ev = await _evening(db, league_id)
    anya = next(r for r in ev["items"] if r["display_name"] == "Аня")
    assert anya["scarf"] == {"club": "Юность-Минск", "picked": "Неман"}
    assert ev["items"][0]["scarf"] is None


def game_day_of(value: datetime) -> date:
    from src.application.hockey_league_evening import game_day

    return game_day(value)
