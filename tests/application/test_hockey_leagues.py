"""TASK-298: лиги друзей — создать, вступить по ссылке, таблица лиги, выйти, друзья на матче."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

import src.application.hockey_leagues as leagues_mod
from src.application.hockey_game import make_pick, score_finished_matches, standings
from src.application.hockey_leagues import (
    LeagueFull,
    TooManyLeagues,
    clean_name,
    create_league,
    friends_picks,
    join_by_code,
    league_preview,
    league_table,
    leave_league,
    normalize_code,
    player_leagues,
    rename_league,
)
from src.application.hockey_matches import set_manual_result
from src.ingestion.hockey_sources import MINSK_TZ

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=MINSK_TZ)
SASHA, KATYA, LESHA, DIMA, STRANGER = 9200001, 9200002, 9200003, 9200004, 9200005


async def _match(db_session, mid: str, starts_at: datetime) -> int:
    return (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
                VALUES ('hcdinamo', :mid, 'Динамо-Минск', 'Барыс', :starts_at) RETURNING id
                """),
            {"mid": mid, "starts_at": starts_at},
        )
    ).scalar_one()


async def _pick(db_session, match_id: int, player: int, name: str, **kw) -> None:
    await make_pick(db_session, player_key=player, display_name=name, match_id=match_id, now=NOW, **kw)


def test_clean_name_and_code() -> None:
    assert clean_name("  Пятничный   ОХМ ") == "Пятничный ОХМ"
    with pytest.raises(ValueError):
        clean_name("   ")
    with pytest.raises(ValueError):
        clean_name("х" * 29)
    assert normalize_code(" ab-cd 23 ") == "ABCD23"


@pytest.mark.asyncio
async def test_create_and_join_is_idempotent(db_session) -> None:
    league = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="Пятничный ОХМ")
    assert len(league.invite_code) == 8
    again = await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=league.invite_code.lower())
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=league.invite_code)
    assert again.id == league.id
    members = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM hockey_league_members WHERE league_id = :l"), {"l": league.id}
        )
    ).scalar_one()
    assert members == 2
    with pytest.raises(LookupError):
        await join_by_code(db_session, player_key=KATYA, display_name="Катя", code="NOPE2345")


async def _joined(db_session, league_id: int, player: int, at: datetime) -> None:
    await db_session.execute(
        text("UPDATE hockey_league_members SET joined_at = :at WHERE league_id = :l AND player_key = :p"),
        {"at": at, "l": league_id, "p": player},
    )


@pytest.mark.asyncio
async def test_league_table_counts_only_matches_after_joining(db_session) -> None:
    league = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="ОХМ")
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=league.invite_code)
    await _joined(db_session, league.id, SASHA, NOW - timedelta(days=1))
    await _joined(db_session, league.id, KATYA, NOW - timedelta(days=1))
    mid = await _match(db_session, "lg1", NOW + timedelta(hours=1))
    await _pick(db_session, mid, SASHA, "Саша", home_score=3, away_score=1)
    await _pick(db_session, mid, KATYA, "Катя", side="away")
    await _pick(db_session, mid, LESHA, "Лёша", home_score=3, away_score=1)
    await _pick(db_session, mid, STRANGER, "Чужой", side="home")
    await set_manual_result(
        db_session, mid, home_score=3, away_score=1, decided_in="regulation", now=NOW + timedelta(hours=4)
    )
    await score_finished_matches(db_session, now=NOW + timedelta(hours=4))
    # Лёша угадал точный счёт, но вступил после матча: в лиге он с нуля, без форы, и виден сразу.
    await join_by_code(db_session, player_key=LESHA, display_name="Лёша", code=league.invite_code)
    await _joined(db_session, league.id, LESHA, NOW + timedelta(hours=5))

    rows = await league_table(db_session, league_id=league.id, player_key=KATYA, now=NOW)
    assert [(r.display_name, r.points, r.rank) for r in rows] == [("Саша", 50, 1), ("Катя", 0, 2), ("Лёша", 0, 2)]
    assert STRANGER not in [r.player_key for r in rows]
    # В общей таблице очки Лёши за сезон на месте.
    global_lesha = next(s for s in await standings(db_session, now=NOW) if s.player_key == LESHA)
    assert global_lesha.points == 50
    with pytest.raises(PermissionError):
        await league_table(db_session, league_id=league.id, player_key=STRANGER, now=NOW)


@pytest.mark.asyncio
async def test_player_leagues_show_my_place(db_session) -> None:
    a = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="ОХМ")
    b = await create_league(db_session, owner_key=KATYA, owner_name="Катя", name="Семья")
    await join_by_code(db_session, player_key=SASHA, display_name="Саша", code=b.invite_code)
    mine = await player_leagues(db_session, player_key=SASHA, now=NOW)
    assert [(x.name, x.is_owner, x.members, x.my_rank) for x in mine] == [("ОХМ", True, 1, 1), ("Семья", False, 2, 1)]
    assert {x.id for x in mine} == {a.id, b.id}


@pytest.mark.asyncio
async def test_owner_leaves_ownership_moves_last_leaves_deletes(db_session) -> None:
    league = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="ОХМ")
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=league.invite_code)
    assert await leave_league(db_session, league_id=league.id, player_key=SASHA) == "owner_moved"
    owner = (
        await db_session.execute(text("SELECT owner_key FROM hockey_leagues WHERE id = :l"), {"l": league.id})
    ).scalar_one()
    assert owner == KATYA
    with pytest.raises(PermissionError):
        await leave_league(db_session, league_id=league.id, player_key=SASHA)
    assert await leave_league(db_session, league_id=league.id, player_key=KATYA) == "deleted"
    assert await league_preview(db_session, league.invite_code) is None


@pytest.mark.asyncio
async def test_only_owner_renames(db_session) -> None:
    league = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="ОХМ")
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=league.invite_code)
    with pytest.raises(PermissionError):
        await rename_league(db_session, league_id=league.id, player_key=KATYA, name="Наша")
    renamed = await rename_league(db_session, league_id=league.id, player_key=SASHA, name=" Субботний  лёд ")
    assert renamed.name == "Субботний лёд"


@pytest.mark.asyncio
async def test_limits(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(leagues_mod, "MAX_MEMBERS", 2)
    monkeypatch.setattr(leagues_mod, "MAX_LEAGUES_PER_PLAYER", 2)
    league = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="ОХМ")
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=league.invite_code)
    with pytest.raises(LeagueFull):
        await join_by_code(db_session, player_key=LESHA, display_name="Лёша", code=league.invite_code)
    await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="Вторая")
    with pytest.raises(TooManyLeagues):
        await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="Третья")


@pytest.mark.asyncio
async def test_preview_has_no_keys(db_session) -> None:
    league = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="ОХМ")
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=league.invite_code)
    preview = await league_preview(db_session, league.invite_code)
    assert preview == {"name": "ОХМ", "invite_code": league.invite_code, "members": 2, "names": ["Саша", "Катя"]}


@pytest.mark.asyncio
async def test_friends_on_match_halves_without_me_strangers_or_scores(db_session) -> None:
    a = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="ОХМ")
    b = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="Семья")
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=a.invite_code)
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=b.invite_code)
    await join_by_code(db_session, player_key=DIMA, display_name="Дима", code=b.invite_code)
    mid = await _match(db_session, "fr1", NOW + timedelta(days=1))
    other = await _match(db_session, "fr2", NOW + timedelta(days=2))
    await _pick(db_session, mid, SASHA, "Саша", side="home")
    await _pick(db_session, mid, KATYA, "Катя", home_score=1, away_score=3)
    await _pick(db_session, mid, DIMA, "Дима", side="home")
    await _pick(db_session, mid, STRANGER, "Чужой", side="home")
    got = await friends_picks(db_session, player_key=SASHA, match_ids=[mid, other])
    # Катя в двух моих лигах — один раз; чужого нет; меня нет.
    assert got == {mid: {"home": ["Дима"], "away": ["Катя"]}, other: {"home": [], "away": []}}
