"""TASK-298: лиги друзей — создать, вступить по ссылке, таблица лиги, выйти, друзья на матче."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import src.application.hockey_leagues as leagues_mod
from src.application.hockey_game import make_pick, score_finished_matches, standings
from src.application.hockey_leagues import (
    MAX_CLUBS,
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
    term_options,
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
    # При равных очках и точных выше тот, кто сыграл меньше ходов: у Лёши ходов в лиге нет.
    assert [(r.display_name, r.points, r.rank) for r in rows] == [("Саша", 50, 1), ("Лёша", 0, 2), ("Катя", 0, 3)]
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


def test_term_options_windows_are_minsk_midnights_and_only_season_crowns_monthly() -> None:
    """Окна сроков для экрана «Новая лига»: границы — минская полночь, корона каждый месяц — только у сезона."""
    november = datetime(2026, 11, 3, 12, 0, tzinfo=MINSK_TZ)
    opts = term_options(now=november)
    assert opts["max_clubs"] == MAX_CLUBS
    by_term = {i["term"]: i for i in opts["items"]}
    assert [i["term"] for i in opts["items"]] == ["season", "month", "weeks4", "playoff"]
    assert [i["term"] for i in opts["items"] if i["monthly_crowns"]] == ["season"]
    # Календарь игры минский: ноябрь и 4 недели начинаются в минскую полночь.
    def utc(y, m, d):
        return datetime(y, m, d, tzinfo=MINSK_TZ).astimezone(timezone.utc).isoformat()

    assert by_term["month"]["starts_at"] == utc(2026, 11, 1)
    assert by_term["month"]["ends_at"] == utc(2026, 12, 1)
    assert by_term["weeks4"]["starts_at"] == utc(2026, 11, 3)
    assert by_term["weeks4"]["ends_at"] == utc(2026, 12, 1)
    # Плей-офф сезона — 1 марта по 1 июня по Минску года окончания сезона.
    assert by_term["playoff"]["starts_at"] == utc(2027, 3, 1)
    assert by_term["playoff"]["ends_at"] == utc(2027, 6, 1)
    assert opts["season_ends_at"] == utc(2027, 8, 1)


def test_term_options_drops_playoff_after_its_end() -> None:
    """Срок, который уже нельзя создать (плей-офф кончился), из списка пропадает — ещё живой он в списке."""
    alive_edge = datetime(2027, 5, 31, 23, 59, tzinfo=MINSK_TZ)
    assert "playoff" in [i["term"] for i in term_options(now=alive_edge)["items"]]
    gone_edge = datetime(2027, 6, 1, 0, 1, tzinfo=MINSK_TZ)
    assert [i["term"] for i in term_options(now=gone_edge)["items"]] == ["season", "month", "weeks4"]
