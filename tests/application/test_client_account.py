"""TASK-367: имя человека не затирается ходом, «мой каток» — только видимый каток каталога."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from src.application.client_account import (
    get_home_arena_id,
    normalize_display_name,
    set_account_name,
    set_home_arena,
)
from src.application.hockey_game import make_pick, score_finished_matches, standings
from src.application.hockey_leagues import create_league, league_table
from src.application.hockey_matches import set_manual_result
from src.ingestion.hockey_sources import MINSK_TZ

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=MINSK_TZ)
ACCOUNT = 3670001
OTHER = 3670002
FAMILY = "👨‍👩‍👧"


def test_normalize_display_name_keeps_emoji_and_zwj() -> None:
    assert normalize_display_name("  Макс   К. ") == "Макс К."
    assert normalize_display_name("Максим 🌱") == "Максим 🌱"
    assert normalize_display_name(f"Макс {FAMILY}") == f"Макс {FAMILY}"
    assert normalize_display_name("Макс\u0007им") == "Максим"
    assert normalize_display_name("Макс\u200bК") == "МаксК"
    assert "\u200d" in normalize_display_name(FAMILY)


@pytest.mark.parametrize("raw", ["", "   ", "а" * 41, "\u0000\u200b"])
def test_normalize_display_name_rejects(raw: str) -> None:
    with pytest.raises(ValueError) as caught:
        normalize_display_name(raw)
    assert str(caught.value) == "Имя — от 1 до 40 знаков"


async def _match(db_session) -> int:
    return (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
                VALUES ('hcdinamo', :mid, 'Динамо-Минск', 'Барыс', :starts_at)
                RETURNING id
                """),
            {"mid": f"t367-{ACCOUNT}", "starts_at": NOW + timedelta(hours=2)},
        )
    ).scalar_one()


async def _src(db_session, player_key: int) -> str | None:
    return (
        await db_session.execute(
            text("SELECT first_src FROM hockey_players WHERE player_key = :p"),
            {"p": player_key},
        )
    ).scalar_one()


async def _name(db_session, player_key: int) -> tuple[str, bool]:
    row = (
        await db_session.execute(
            text("SELECT display_name, name_set_by_user FROM hockey_players WHERE player_key = :p"),
            {"p": player_key},
        )
    ).one()
    return str(row.display_name), bool(row.name_set_by_user)


@pytest.mark.asyncio
async def test_pick_updates_name_until_person_sets_it(db_session) -> None:
    mid = await _match(db_session)
    await make_pick(
        db_session, player_key=OTHER, display_name="Саша", match_id=mid, side="home", now=NOW
    )
    assert await _name(db_session, OTHER) == ("Саша", False)
    await make_pick(
        db_session, player_key=OTHER, display_name="Александр", match_id=mid, side="away", now=NOW
    )
    assert await _name(db_session, OTHER) == ("Александр", False)


NAMED = 3670003
LABELED = 3670004


@pytest.mark.asyncio
async def test_first_src_written_on_first_pick_after_name(db_session) -> None:
    mid = await _match(db_session)
    await set_account_name(db_session, NAMED, "Макс")
    await make_pick(
        db_session,
        player_key=NAMED,
        display_name="Максим К.",
        match_id=mid,
        side="home",
        src="promo1",
        now=NOW,
    )
    assert await _name(db_session, NAMED) == ("Макс", True)
    assert await _src(db_session, NAMED) == "promo1"


@pytest.mark.asyncio
async def test_first_src_not_replaced_by_later_pick(db_session) -> None:
    mid = await _match(db_session)
    await make_pick(
        db_session,
        player_key=LABELED,
        display_name="Саша",
        match_id=mid,
        side="home",
        src="promo1",
        now=NOW,
    )
    await make_pick(
        db_session,
        player_key=LABELED,
        display_name="Александр",
        match_id=mid,
        side="away",
        src="other2",
        now=NOW,
    )
    assert await _src(db_session, LABELED) == "promo1"
    assert (await _name(db_session, LABELED))[0] == "Александр"


@pytest.mark.asyncio
async def test_user_name_survives_telegram_pick_in_table_and_league(db_session) -> None:
    mid = await _match(db_session)
    await make_pick(
        db_session, player_key=ACCOUNT, display_name="Максим К.", match_id=mid, side="home", now=NOW
    )
    saved = await set_account_name(db_session, ACCOUNT, "  Макс   ")
    assert saved == "Макс"
    await make_pick(
        db_session, player_key=ACCOUNT, display_name="Максим К.", match_id=mid, side="away", now=NOW
    )
    assert await _name(db_session, ACCOUNT) == ("Макс", True)

    league = await create_league(
        db_session, owner_key=ACCOUNT, owner_name="Максим К.", name="Сезон", now=NOW
    )
    await set_manual_result(
        db_session, mid, home_score=3, away_score=1, decided_in="regulation", now=NOW + timedelta(hours=5)
    )
    await score_finished_matches(db_session, now=NOW + timedelta(hours=5))

    table = [row for row in await standings(db_session, now=NOW) if row.player_key == ACCOUNT]
    assert table and table[0].display_name == "Макс"
    league_rows = await league_table(db_session, league_id=league.id, player_key=ACCOUNT, now=NOW)
    mine = [row for row in league_rows if row.player_key == ACCOUNT]
    assert mine and mine[0].display_name == "Макс"


async def _city(db_session, *, active: bool) -> int:
    return (
        await db_session.execute(
            text("""
                INSERT INTO cities (name, country, is_active)
                VALUES (:name, 'BY', :active)
                RETURNING id
                """),
            {"name": f"TASK-367 {'открыт' if active else 'закрыт'}", "active": active},
        )
    ).scalar_one()


async def _arena(db_session, city_id: int, *, active: bool = True, confirmed: bool = True) -> int:
    return (
        await db_session.execute(
            text("""
                INSERT INTO arenas (city_id, name, is_active, is_confirmed)
                VALUES (:city_id, :name, :active, :confirmed)
                RETURNING id
                """),
            {
                "city_id": city_id,
                "name": f"Каток {city_id}-{active}-{confirmed}",
                "active": active,
                "confirmed": confirmed,
            },
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_home_arena_visible_only_and_clears_on_delete(db_session) -> None:
    city_id = await _city(db_session, active=True)
    visible = await _arena(db_session, city_id)
    hidden = await _arena(db_session, city_id, active=False)
    draft = await _arena(db_session, city_id)
    await db_session.execute(
        text("""
            INSERT INTO arena_profiles (arena_id, city_id, slug, status)
            VALUES (:arena_id, :city_id, :slug, 'draft')
            """),
        {"arena_id": draft, "city_id": city_id, "slug": f"t367-draft-{draft}"},
    )
    closed_city = await _city(db_session, active=False)
    closed = await _arena(db_session, closed_city)

    assert await set_home_arena(db_session, ACCOUNT, visible) == visible
    assert await get_home_arena_id(db_session, ACCOUNT) == visible

    for arena_id in (hidden, draft, closed, 2_147_483_647):
        with pytest.raises(ValueError) as caught:
            await set_home_arena(db_session, ACCOUNT, arena_id)
        assert str(caught.value) == "Каток не найден"
    assert await get_home_arena_id(db_session, ACCOUNT) == visible

    assert await set_home_arena(db_session, ACCOUNT, None) is None
    assert await get_home_arena_id(db_session, ACCOUNT) is None

    assert await set_home_arena(db_session, ACCOUNT, visible) == visible
    await db_session.execute(text("DELETE FROM arenas WHERE id = :id"), {"id": visible})
    assert await get_home_arena_id(db_session, ACCOUNT) is None
