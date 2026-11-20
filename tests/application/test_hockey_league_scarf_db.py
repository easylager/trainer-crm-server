"""«В чужом шарфе» по живой базе: «своя» команда — «болею за» или клуб, за который чаще ходил (не всегда Динамо)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.hockey_leagues import league_titles

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
YOUTH_FAN, DINAMO_FAN, NO_TEAM, HABIT_FAN = 880_431_001, 880_431_002, 880_431_003, 880_431_004


async def _match(db, home: str, away: str, starts_at: datetime, *, status: str = "scheduled") -> int:
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
                    "hs": 3 if final else None,
                    "as_": 1 if final else None,
                    "din": "regulation" if final else None,
                    "rs": "auto" if final else None,
                },
            )
        ).scalar_one()
    )


async def _pick(db, player: int, match_id: int, side: str, *, points: int | None = None) -> None:
    await db.execute(
        text("INSERT INTO hockey_picks (player_key, match_id, side, points) VALUES (:p, :m, :s, :pts)"),
        {"p": player, "m": match_id, "s": side, "pts": points},
    )


@pytest.mark.asyncio
async def test_scarf_uses_each_players_own_team(db_session) -> None:
    db = db_session
    for key in (YOUTH_FAN, DINAMO_FAN, NO_TEAM, HABIT_FAN):
        await db.execute(text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, 'И')"), {"k": key})
    await db.execute(
        text(
            "INSERT INTO hockey_player_prefs (player_key, fav_club) VALUES (:y, 'Юность-Минск'), (:d, 'Динамо-Минск')"
        ),
        {"y": YOUTH_FAN, "d": DINAMO_FAN},
    )
    league_id = (
        await db.execute(
            text("""INSERT INTO hockey_leagues (name, invite_code, owner_key, scope, term_kind, starts_at, ends_at)
                    VALUES ('Л', 'KK431SCF', :o, 'all', 'month', :s, :e) RETURNING id"""),
            {"o": YOUTH_FAN, "s": NOW - timedelta(days=17), "e": NOW + timedelta(days=12)},
        )
    ).scalar_one()
    for key in (YOUTH_FAN, DINAMO_FAN, NO_TEAM, HABIT_FAN):
        await db.execute(
            text("INSERT INTO hockey_league_members (league_id, player_key, joined_at) VALUES (:l, :k, :j)"),
            {"l": league_id, "k": key, "j": NOW - timedelta(days=17)},
        )

    # Ближайший матч дня — без Динамо: раньше ход за хозяев здесь считался ходом «против Динамо».
    youth = await _match(db, "Юность-Минск", "Шахтёр", NOW + timedelta(hours=6))
    await _pick(db, YOUTH_FAN, youth, "away")  # против своей Юности — шарф
    await _pick(db, DINAMO_FAN, youth, "home")  # болеет за Динамо, матч не про его команду — без шарфа
    await _pick(db, NO_TEAM, youth, "away")  # своей команды нет — без шарфа

    # «Своя» без настройки: за Динамо ходил в прошлом, теперь пошёл против.
    past = await _match(db, "Динамо-Минск", "Барыс", NOW - timedelta(days=5), status="final")
    await _pick(db, HABIT_FAN, past, "home", points=20)
    dinamo_away = await _match(db, "Барыс", "Динамо-Минск", NOW + timedelta(days=1))
    await _pick(db, HABIT_FAN, dinamo_away, "home")
    await db.flush()

    titles = await league_titles(db, league_id=league_id, now=NOW)

    assert {k: v["id"] for k, v in titles.items()} == {YOUTH_FAN: "scarf", HABIT_FAN: "scarf"}


@pytest.mark.asyncio
async def test_titles_count_only_picks_after_joining_like_the_table(db_session) -> None:
    """Звания — из тех же ходов, что очки таблицы: до вступления лига их не видела, «Ванги» за них нет."""
    from src.application.hockey_game import POINTS_EXACT

    db = db_session
    late, early = 880_431_011, 880_431_012
    for key in (late, early):
        await db.execute(text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, 'И')"), {"k": key})
    league_id = (
        await db.execute(
            text("""INSERT INTO hockey_leagues (name, invite_code, owner_key, scope, term_kind, starts_at, ends_at)
                    VALUES ('Л', 'KK431JND', :o, 'all', 'month', :s, :e) RETURNING id"""),
            {"o": early, "s": NOW - timedelta(days=17), "e": NOW + timedelta(days=12)},
        )
    ).scalar_one()
    await db.execute(
        text("""INSERT INTO hockey_league_members (league_id, player_key, joined_at)
                VALUES (:l, :e, :start), (:l, :late, :joined)"""),
        {"l": league_id, "e": early, "late": late, "start": NOW - timedelta(days=17), "joined": NOW - timedelta(days=2)},
    )
    for days in (10, 8):  # оба точных счёта — до вступления late
        m = await _match(db, "Динамо-Минск", "Барыс", NOW - timedelta(days=days), status="final")
        await _pick(db, late, m, "home", points=POINTS_EXACT)
    await db.flush()

    assert await league_titles(db, league_id=league_id, now=NOW) == {}
