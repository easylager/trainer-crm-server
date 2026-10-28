"""TASK-340: синхронизация Экстралиги с hockey.by — календарь, страница матча, таблица, изоляция от игры."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from src.application.extraliga import (
    CalendarEmpty,
    details_due,
    enabled_clubs,
    match_page_url,
    run_tick,
    STANDINGS_URL,
    sync_calendar,
    sync_details,
    sync_standings,
    upsert_calendar_match,
)
from src.ingestion.hockey_sources import MINSK_TZ
from src.ingestion.hockeyby_sources import STATUS_SCHEDULED, CalendarMatch

FIXTURES = Path(__file__).resolve().parents[2] / "data/fixtures/hockey"


def _page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _minsk(*args: int) -> datetime:
    return datetime(*args, tzinfo=MINSK_TZ)


class FakeSource:
    def __init__(self, pages: list[str], urls: dict[str, str] | None = None) -> None:
        self.pages = pages
        self.urls = urls or {}
        self.asked: list[str] = []

    async def calendar_page(self, page: int) -> str:
        self.asked.append(f"calendar:{page}")
        return self.pages[min(page, len(self.pages)) - 1]

    async def get(self, url: str) -> str:
        self.asked.append(url)
        return self.urls[url]


def _season() -> FakeSource:
    return FakeSource(
        [
            _page("hockeyby-calendar-p01.json"),
            _page("hockeyby-calendar-p12.json"),
            _page("hockeyby-calendar-p32-empty.json"),
        ]
    )


def _yunost_neman(match_id: str, starts_at: datetime) -> CalendarMatch:
    return CalendarMatch(
        match_id=match_id,
        starts_at=starts_at,
        home="Юность",
        away="Неман",
        home_club_id="10",
        away_club_id="14",
        arena="Чижовка-Арена",
        city=None,
        status=STATUS_SCHEDULED,
    )


async def _match(db_session, source_match_id: str):
    return (
        await db_session.execute(
            text(
                "SELECT id, league, status, home_team, away_team, starts_at, home_score, away_score, decided_in,"
                " result_source, tickets_url, details FROM hockey_matches"
                " WHERE source = 'hockeyby' AND source_match_id = :id"
            ),
            {"id": source_match_id},
        )
    ).one()


async def test_season_sync_stores_matches_and_old_results(db_session) -> None:
    now = _minsk(2026, 10, 28, 12, 0)
    source = _season()
    counts = await sync_calendar(db_session, source, now=now)
    assert counts["inserted"] == 24 and counts["pages"] == 3 and counts["failed"] == 0
    assert source.asked == ["calendar:1", "calendar:2", "calendar:3"]

    played = await _match(db_session, "441522")
    assert (played.league, played.home_team, played.away_team) == ("extraliga", "Шахтер", "Химик")
    # Сентябрьский матч: страница матча уже не нужна — итог из календаря.
    assert (played.status, played.home_score, played.away_score, played.result_source) == ("final", 5, 2, "auto")

    future = await _match(db_session, "442032")
    assert (future.status, future.home_team, future.away_team) == ("scheduled", "Металлург Жлобин", "Витебск")

    again = await sync_calendar(db_session, _season(), now=now)
    assert again["inserted"] == 0 and again["unchanged"] == 24


async def test_game_does_not_see_extraliga(db_session) -> None:
    await sync_calendar(db_session, _season(), now=_minsk(2026, 10, 28, 12, 0))
    total = (await db_session.execute(text("SELECT count(*) FROM hockey_matches WHERE source = 'hockeyby'"))).scalar()
    seen = (await db_session.execute(text("SELECT count(*) FROM kk_matches WHERE source = 'hockeyby'"))).scalar()
    assert total == 24 and seen == 0


async def test_postponed_match_moves_and_played_one_stays(db_session) -> None:
    now = _minsk(2026, 10, 28, 12, 0)
    m = _yunost_neman("441978", _minsk(2026, 10, 29, 19, 0))
    assert await upsert_calendar_match(db_session, m, now=now) == "inserted"
    assert await upsert_calendar_match(db_session, m, now=now) == "unchanged"
    later = replace(m, starts_at=_minsk(2026, 10, 30, 17, 0))
    assert await upsert_calendar_match(db_session, later, now=now) == "moved"
    row = await _match(db_session, "441978")
    assert row.starts_at == _minsk(2026, 10, 30, 17, 0)


async def test_match_page_sets_tickets_and_official_result(db_session) -> None:
    now = _minsk(2026, 10, 27, 22, 0)
    await upsert_calendar_match(db_session, _yunost_neman("441964", _minsk(2026, 10, 27, 19, 0)), now=now)
    await upsert_calendar_match(db_session, _yunost_neman("441978", _minsk(2026, 10, 29, 19, 0)), now=now)
    source = FakeSource(
        [],
        {
            match_page_url("441964"): _page("hockeyby-gamecenter-441964-ot.html"),
            match_page_url("441978"): _page("hockeyby-gamecenter-441978-future.html"),
        },
    )
    counts = await sync_details(db_session, source, now=now)
    assert counts == {"checked": 2, "final": 1, "failed": 0}

    done = await _match(db_session, "441964")
    assert (done.status, done.home_score, done.away_score, done.decided_in) == ("final", 3, 2, "ot")
    assert done.details["attendance"] == 622
    assert done.details["goals"][-1] == {
        "minute": "62:25",
        "side": "home",
        "scorer": "Арсений Ковгореня",
        "assists": [],
    }

    ahead = await _match(db_session, "441978")
    assert ahead.status == "scheduled"
    assert ahead.tickets_url.startswith("https://www.ticketpro.by/")
    assert ahead.details["home"]["forwards"][0]["name"] == "Дмитрий Хобян"

    # Через 10 минут ничего не перечитываем: у сыгранного протокол официальный, будущий — раз в сутки.
    assert await sync_details(db_session, source, now=now + timedelta(minutes=10)) == {
        "checked": 0,
        "final": 0,
        "failed": 0,
    }


def test_details_cadence() -> None:
    starts = _minsk(2026, 10, 29, 19, 0)
    assert details_due(starts, None, now=_minsk(2026, 10, 25, 12, 0))
    # За 4 дня до матча — раз в сутки.
    assert not details_due(starts, _minsk(2026, 10, 25, 1, 0), now=_minsk(2026, 10, 25, 12, 0))
    assert details_due(starts, _minsk(2026, 10, 24, 11, 0), now=_minsk(2026, 10, 25, 12, 0))
    # В день матча — каждые 15 минут.
    assert not details_due(starts, _minsk(2026, 10, 29, 20, 0), now=_minsk(2026, 10, 29, 20, 10))
    assert details_due(starts, _minsk(2026, 10, 29, 20, 0), now=_minsk(2026, 10, 29, 20, 16))


async def test_standings_by_team_id(db_session) -> None:
    source = FakeSource([], {STANDINGS_URL: _page("hockeyby-table-628.html")})
    assert await sync_standings(db_session, source, now=_minsk(2026, 10, 28, 6, 0)) == 14
    rows = dict(
        (
            await db_session.execute(
                text("SELECT team, place || '/' || points FROM hockey_standings WHERE league = 'extraliga'")
            )
        ).all()
    )
    assert rows["Юность"] == "13/9" and rows["Неман"] == "7/18" and rows["Металлург Жлобин"] == "2/25"


async def test_empty_calendar_is_an_error(db_session) -> None:
    with pytest.raises(CalendarEmpty):
        await sync_calendar(
            db_session, FakeSource([_page("hockeyby-calendar-p32-empty.json")]), now=_minsk(2026, 10, 28)
        )


async def test_tick_survives_a_broken_calendar(db_session) -> None:
    source = FakeSource(['{"status": "error", "errors": []}'], {STANDINGS_URL: _page("hockeyby-table-628.html")})
    out = await run_tick(db_session, source, now=_minsk(2026, 10, 28, 6, 0), calendar_due=True, standings_due=True)
    assert out["calendar_failed"] is True and out["standings"] == 14


def test_enabled_clubs_from_settings() -> None:
    assert enabled_clubs("") == frozenset()
    assert enabled_clubs(" Юность, Неман ,") == {"Юность", "Неман"}
    assert enabled_clubs("Юность,Шинник") == {"Юность"}


async def test_match_closed_by_calendar_still_gets_its_protocol(db_session) -> None:
    now = _minsk(2026, 10, 28, 12, 0)
    played = replace(
        _yunost_neman("441964", _minsk(2026, 10, 27, 19, 0)),
        status="played",
        home_score=3,
        away_score=2,
        decided_in="ot",
    )
    assert await upsert_calendar_match(db_session, played, now=now) == "inserted"
    assert (await _match(db_session, "441964")).status == "final"
    source = FakeSource([], {match_page_url("441964"): _page("hockeyby-gamecenter-441964-ot.html")})
    assert (await sync_details(db_session, source, now=now))["checked"] == 1
    row = await _match(db_session, "441964")
    assert row.details["official"] is True and len(row.details["goals"]) == 5
    # Официальный протокол есть — больше не ходим.
    assert (await sync_details(db_session, source, now=now + timedelta(hours=2)))["checked"] == 0
