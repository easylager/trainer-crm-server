"""Ревью бэкенда «Кто кого» (09.11): утечки, 500-ки на краях, повторные события."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.deps import get_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.api.routes import webapp_client_hockey_share as share_routes
from src.application.hockey_game import make_pick, score_finished_matches
from src.application.hockey_leagues import create_league, join_by_code
from src.application.hockey_matches import set_manual_result
from src.application.hockey_races import close_due_races, ensure_month_race, mark_calendar_synced, race_result
from src.ingestion.hockey_sources import MINSK_TZ

ME = 880_310_001
FRIEND = 880_310_002
THIRD = 880_310_003
NAMES = {ME: "Саша", FRIEND: "Катя", THIRD: "Лёша"}


@contextmanager
def patch_client_principal(user_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)
    app.dependency_overrides[get_client_miniapp_principal] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_client_miniapp_principal, None)


@pytest.fixture(autouse=True)
def _client_env(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_prepare(*args, **kwargs):
        return "PM-1"

    monkeypatch.setattr(share_routes, "_prepare", fake_prepare)
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.test")
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "1")
    monkeypatch.delenv("CLIENT_MINI_APP_SHORT_NAME", raising=False)


NOV = datetime(2026, 11, 10, 12, 0, tzinfo=MINSK_TZ)
DEC = datetime(2026, 12, 1, 12, 0, tzinfo=MINSK_TZ)
JOINED = datetime(2026, 11, 1, tzinfo=MINSK_TZ)


async def _insert_match(db_session, *, starts_at: datetime) -> int:
    return int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at, status)
                    VALUES ('hcdinamo', :mid, 'Динамо-Минск', 'ХК Сочи', :starts_at, 'scheduled')
                    RETURNING id
                    """),
                {"mid": uuid.uuid4().hex, "starts_at": starts_at},
            )
        ).scalar_one()
    )


async def _league_with(db_session, owner: int, owner_name: str, name: str, *others: tuple[int, str]):
    league = await create_league(db_session, owner_key=owner, owner_name=owner_name, name=name)
    for key, display in others:
        await join_by_code(db_session, player_key=key, display_name=display, code=league.invite_code)
    await db_session.execute(
        text("UPDATE hockey_league_members SET joined_at = :at WHERE league_id = :l"),
        {"at": JOINED, "l": league.id},
    )
    return league


async def _play_november(db_session, scores: dict[int, tuple[int, int]]):
    """Один матч ноября, ходы игроков, итог 3:1, гонка закрыта. Возвращает гонку."""
    race = await ensure_month_race(db_session, now=NOV)
    starts = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    match_id = await _insert_match(db_session, starts_at=starts)
    for player, score in scores.items():
        await make_pick(
            db_session,
            player_key=player,
            display_name=NAMES.get(player, "Игрок"),
            match_id=match_id,
            home_score=score[0],
            away_score=score[1],
            now=starts - timedelta(hours=1),
        )
    await set_manual_result(db_session, match_id, home_score=3, away_score=1, decided_in="regulation", now=DEC)
    await score_finished_matches(db_session, now=DEC)
    await mark_calendar_synced(db_session, now=datetime(2026, 11, 25, tzinfo=MINSK_TZ))
    assert await close_due_races(db_session, now=DEC + timedelta(days=8))
    await db_session.commit()
    return race


@pytest.mark.asyncio
async def test_a_crown_wall_does_not_leak_player_key(app_use_test_db, db_session) -> None:
    """Стена корон отдаёт имена чемпионов, но не Telegram-id (player_key)."""
    league = await _league_with(db_session, ME, "Саша", "ОХМ", (FRIEND, "Катя"), (THIRD, "Лёша"))
    await _play_november(db_session, {ME: (3, 1), FRIEND: (2, 1), THIRD: (5, 0)})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            r = await client.get(f"/api/webapp/client/hockey/leagues/{league.id}")
    assert r.status_code == 200, r.text
    crowned = [m for m in r.json()["wall"] if m["state"] == "crowned"]
    assert crowned, "в ноябре должна быть корона"
    assert crowned[0]["winners"] == [{"display_name": "Саша"}]
    assert "player_key" not in r.text and str(ME) not in r.text


@pytest.mark.asyncio
async def test_b_crown_share_without_league_crowns_is_404_not_500(app_use_test_db, db_session) -> None:
    """У лиги нет корон за месяц (никто не ходил) — 404 вместо падения на assert."""
    await _league_with(db_session, ME, "Саша", "Тихая", (FRIEND, "Катя"))
    race = await _play_november(db_session, {})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            r = await client.post("/api/webapp/client/hockey/share", json={"card": "crown", "race_id": race.id})
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_b_race_result_picks_league_with_crown(app_use_test_db, db_session) -> None:
    """«Лучшая лига» итогов месяца — та, где за месяц выдали корону, а не просто где сейчас выше место."""
    played = await _league_with(db_session, ME, "Саша", "Играли", (FRIEND, "Катя"), (THIRD, "Лёша"))
    await _league_with(db_session, ME, "Саша", "Тихая", (880_310_099, "Тихий"))
    race = await _play_november(db_session, {FRIEND: (3, 1), THIRD: (2, 1), ME: (2, 0)})

    res = await race_result(db_session, player_key=ME, race=race)
    assert res["league"]["id"] == played.id


@pytest.mark.asyncio
async def test_c_extend_owner_over_quota_is_409_and_leaves_no_orphan(app_use_test_db, db_session) -> None:
    """Владелец в 20 лигах: «Продлить» — понятный 409, а не лига без владельца и не 500."""
    from src.application.hockey_leagues import MAX_LEAGUES_PER_PLAYER

    league = await _league_with(db_session, ME, "Саша", "Старая", (FRIEND, "Катя"))
    # Старая лига закончилась и квоту не держит; остальные 20 — держат.
    await db_session.execute(
        text("UPDATE hockey_leagues SET ends_at = :at WHERE id = :l"),
        {"at": datetime.now(timezone.utc) - timedelta(days=1), "l": league.id},
    )
    for i in range(MAX_LEAGUES_PER_PLAYER):
        await create_league(db_session, owner_key=ME, owner_name="Саша", name=f"Л{i}")
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            r = await client.post(f"/api/webapp/client/hockey/leagues/{league.id}/extend", json={})
    assert r.status_code == 409, r.text
    orphans = (
        await db_session.execute(text("SELECT COUNT(*) FROM hockey_leagues WHERE extended_from = :l"), {"l": league.id})
    ).scalar_one()
    assert orphans == 0


@pytest.mark.asyncio
async def test_c_extend_again_after_owner_left_extension_is_not_500(app_use_test_db, db_session) -> None:
    """Продление есть, а владелец из него вышел: повтор «Продлить» отвечает понятной ошибкой, не 500."""
    league = await _league_with(db_session, ME, "Саша", "Старая", (FRIEND, "Катя"))
    await db_session.execute(
        text("UPDATE hockey_leagues SET ends_at = :at WHERE id = :l"),
        {"at": datetime.now(timezone.utc) - timedelta(days=1), "l": league.id},
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            first = await client.post(f"/api/webapp/client/hockey/leagues/{league.id}/extend", json={})
            assert first.status_code == 200, first.text
            left = await client.delete(f"/api/webapp/client/hockey/leagues/{first.json()['id']}/membership")
            assert left.status_code == 200, left.text
            again = await client.post(f"/api/webapp/client/hockey/leagues/{league.id}/extend", json={})
    assert again.status_code == 409, again.text


@pytest.mark.parametrize("raw", ["0001-01", "1999-12", "9999-12", "2101-01"])
def test_d_parse_period_rejects_absurd_years(raw: str) -> None:
    from src.application.hockey_slices import parse_period

    with pytest.raises(ValueError):
        parse_period(raw, NOV)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"term": "month", "month": "0001-01"},
        {"term": "month", "month": "9999-12"},
        {"term": "dates", "starts_at": datetime(1, 1, 1).date(), "ends_at": datetime(2026, 12, 1).date()},
        {"term": "dates", "starts_at": datetime(2026, 11, 20).date(), "ends_at": datetime(9999, 12, 31).date()},
        {"term": "playoff", "starts_at": datetime(1, 1, 1).date(), "ends_at": datetime(2027, 4, 1).date()},
    ],
)
def test_d_build_terms_rejects_absurd_years_with_invalid_terms(kwargs: dict) -> None:
    from src.application.hockey_leagues import InvalidTerms, build_terms

    with pytest.raises(InvalidTerms):
        build_terms(scope="dinamo", now=NOV, **kwargs)


@pytest.mark.asyncio
async def test_e_stakes_for_played_match_promise_nothing(app_use_test_db, db_session) -> None:
    """«Если угадаешь» для сыгранного матча не добавляет очки победителя второй раз."""
    from src.application.hockey_slices import stakes

    await _league_with(db_session, ME, "Саша", "Трое", (FRIEND, "Катя"), (THIRD, "Лёша"))
    starts = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    match_id = await _insert_match(db_session, starts_at=starts)
    # Друзья сходили на матч, Саша нет: матч сыгран, и обещать Саше «если угадаешь» уже нечего.
    for player in (FRIEND, THIRD):
        await make_pick(
            db_session,
            player_key=player,
            display_name=NAMES[player],
            match_id=match_id,
            home_score=5,
            away_score=0,
            now=starts - timedelta(hours=1),
        )
    await set_manual_result(db_session, match_id, home_score=3, away_score=1, decided_in="regulation", now=DEC)
    await score_finished_matches(db_session, now=DEC)

    after = await stakes(db_session, player_key=ME, match_id=match_id, now=DEC)
    assert after is not None and after["items"] == []


@pytest.mark.asyncio
async def test_e_join_by_code_vanished_league_is_lookup_error(app_use_test_db, db_session, monkeypatch) -> None:
    """Лигу удалили между поиском по коду и блокировкой строки: LookupError (404), не NoResultFound."""
    from src.application import hockey_leagues

    league = await _league_with(db_session, ME, "Саша", "Исчезнет")
    ghost = hockey_leagues.League(**{**league.__dict__, "id": -1})

    async def fake_by_code(session, code):
        return ghost

    monkeypatch.setattr(hockey_leagues, "league_by_code", fake_by_code)
    with pytest.raises(LookupError):
        await hockey_leagues.join_by_code(db_session, player_key=FRIEND, display_name="Катя", code="X")


@pytest.mark.asyncio
async def test_e_join_league_reports_whether_player_was_added(app_use_test_db, db_session) -> None:
    """Событие joined пишется по факту вступления: повторный «Вступить» нового участника не создаёт."""
    from src.application.hockey_leagues import join_league

    league = await _league_with(db_session, ME, "Саша", "Двор")
    first, added = await join_league(db_session, player_key=FRIEND, display_name="Катя", code=league.invite_code)
    again, added_again = await join_league(db_session, player_key=FRIEND, display_name="Катя", code=league.invite_code)
    assert first.id == again.id == league.id
    assert (added, added_again) == (True, False)


def test_e_phase_closes_with_the_pick_window() -> None:
    """Последние 60 секунд ход уже не принимается, и фаза не должна говорить «open»."""
    from src.application.hockey_event import _phase

    start = datetime(2026, 11, 20, 19, 0, tzinfo=timezone.utc)
    assert _phase("scheduled", start, now=start - timedelta(minutes=5), picked=False) == "open"
    assert _phase("scheduled", start, now=start - timedelta(seconds=30), picked=False) == "live"
    assert _phase("scheduled", start, now=start - timedelta(seconds=30), picked=True) == "live"
