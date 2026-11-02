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
    assert counts == {"checked": 2, "final": 1, "failed": 0, "live": 0}

    done = await _match(db_session, "441964")
    assert (done.status, done.home_score, done.away_score, done.decided_in) == ("final", 3, 2, "ot")
    assert done.details["attendance"] == 622
    assert done.details["goals"][-1] == {
        "minute": "62:25",
        "side": "home",
        "scorer": "Арсений Ковгореня",
        "assists": [],
        "streak": 3,
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
        "live": 0,
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


async def test_old_results_get_protocols_a_few_per_tick(db_session, monkeypatch) -> None:
    import src.application.extraliga as extraliga

    monkeypatch.setattr(extraliga, "BACKFILL_PER_TICK", 1)
    now = _minsk(2026, 11, 20, 12, 0)
    for mid, day in (("441960", 24), ("441964", 27)):
        played = replace(
            _yunost_neman(mid, _minsk(2026, 10, day, 19, 0)),
            status="played",
            home_score=1,
            away_score=4,
            decided_in="regulation",
        )
        await upsert_calendar_match(db_session, played, now=now)
    source = FakeSource(
        [],
        {
            match_page_url("441960"): _page("hockeyby-gamecenter-441960-final.html"),
            match_page_url("441964"): _page("hockeyby-gamecenter-441964-ot.html"),
        },
    )
    # По одному за тик, свежий первым.
    assert (await sync_details(db_session, source, now=now))["checked"] == 1
    assert source.asked == [match_page_url("441964")]
    assert (await sync_details(db_session, source, now=now + timedelta(minutes=10)))["checked"] == 1
    assert (await sync_details(db_session, source, now=now + timedelta(minutes=20)))["checked"] == 0
    streaks = [g["streak"] for g in (await _match(db_session, "441964")).details["goals"]]
    assert streaks == [None, None, None, 3, 3]


async def test_broken_match_page_is_not_hammered(db_session) -> None:
    now = _minsk(2026, 10, 25, 12, 0)
    await upsert_calendar_match(db_session, _yunost_neman("441978", _minsk(2026, 10, 29, 19, 0)), now=now)
    source = FakeSource([], {match_page_url("441978"): "<html>сайт на обслуживании</html>"})
    assert (await sync_details(db_session, source, now=now))["failed"] == 1
    assert (await sync_details(db_session, source, now=now + timedelta(minutes=10)))["failed"] == 0


async def test_preview_before_the_return_match(db_session) -> None:
    from src.application.extraliga_preview import match_preview

    now = _minsk(2026, 10, 28, 12, 0)
    await sync_calendar(db_session, _season(), now=now)
    first = replace(
        _yunost_neman("441964", _minsk(2026, 10, 27, 19, 0)),
        status="played",
        home_score=3,
        away_score=2,
        decided_in="ot",
    )
    await upsert_calendar_match(db_session, first, now=now)
    await upsert_calendar_match(db_session, _yunost_neman("441978", _minsk(2026, 10, 29, 19, 0)), now=now)
    source = FakeSource(
        [],
        {
            STANDINGS_URL: _page("hockeyby-table-628.html"),
            match_page_url("441964"): _page("hockeyby-gamecenter-441964-ot.html"),
            match_page_url("441978"): _page("hockeyby-gamecenter-441978-future.html"),
        },
    )
    await sync_standings(db_session, source, now=now)
    await sync_details(db_session, source, now=now)
    mid = (await _match(db_session, "441978")).id

    p = await match_preview(db_session, mid)
    yu, ne = p["home"], p["away"]
    assert (yu["place"], yu["points"], ne["place"], ne["points"]) == (13, 9, 7, 18)
    # В фикстурах из сыгранных у этой пары только вчерашний матч — он и есть свежий в форме.
    assert yu["form"][-1] == "Во" and ne["form"][-1] == "По"
    assert [f["name"] for f in yu["leaders"]["forwards"]] == ["Дмитрий Хобян", "Кирилл Бобровских"]
    assert ne["leaders"]["goalie"]["save_pct"] == 92.2
    assert yu["streaks"] == [{"player": "Арсений Ковгореня", "matches": 3}]
    last = p["last_meeting"]
    assert (last["home_score"], last["away_score"], last["decided_in"], last["same_arena"]) == (3, 2, "ot", True)
    assert last["winning_goal"] == {"scorer": "Арсений Ковгореня", "minute": 63}
    assert last["loser"] == "Неман"


def test_form_marks_and_winning_goal() -> None:
    from src.application.extraliga_preview import _Played, form_mark, winning_goal

    so = _Played("Шахтер", "Гомель", 3, 2, "so", _minsk(2026, 10, 1, 19, 0), None, {"goals": []})
    assert (form_mark(so, "Шахтер"), form_mark(so, "Гомель")) == ("Вб", "Пб")
    assert winning_goal(so) is None
    goals = [{"side": s, "scorer": n, "minute": "10:00"} for s, n in (("away", "А"), ("home", "Б"), ("home", "В"))]
    reg = _Played("Юность", "Лида", 2, 1, "regulation", _minsk(2026, 10, 1, 19, 0), None, {"goals": goals})
    assert form_mark(reg, "Лида") == "П" and winning_goal(reg)["scorer"] == "В"


async def _with_pick(db_session, source_match_id: str) -> int:
    from src.application.hockey_game import make_pick

    row = await _match(db_session, source_match_id)
    await make_pick(
        db_session,
        player_key=881_334_001,
        display_name="Саша",
        match_id=row.id,
        side="home",
        now=row.starts_at - timedelta(hours=2),
    )
    return row.id


async def test_result_needs_two_stable_polls_when_there_are_picks(db_session) -> None:
    """TASK-334 M1: у Экстралиги один источник — итог публикуется после двух одинаковых опросов."""
    now = _minsk(2026, 10, 27, 22, 0)
    await upsert_calendar_match(db_session, _yunost_neman("441964", _minsk(2026, 10, 27, 19, 0)), now=now)
    await _with_pick(db_session, "441964")
    source = FakeSource([], {match_page_url("441964"): _page("hockeyby-gamecenter-441964-ot.html")})
    await sync_details(db_session, source, now=now)
    assert (await _match(db_session, "441964")).status == "scheduled"  # первый опрос: запомнили
    # Слишком скоро (меньше 15 минут) — ещё не публикуем
    await db_session.execute(text("UPDATE hockey_matches SET details_checked_at = NULL"))
    await sync_details(db_session, source, now=now + timedelta(minutes=5))
    assert (await _match(db_session, "441964")).status == "scheduled"
    await db_session.execute(text("UPDATE hockey_matches SET details_checked_at = NULL"))
    await sync_details(db_session, source, now=now + timedelta(minutes=16))
    done = await _match(db_session, "441964")
    assert (done.status, done.home_score, done.away_score, done.decided_in) == ("final", 3, 2, "ot")


async def test_changed_score_between_polls_goes_to_review(db_session) -> None:
    from src.application.extraliga import confirm_result

    now = _minsk(2026, 10, 27, 22, 0)
    await upsert_calendar_match(db_session, _yunost_neman("441964", _minsk(2026, 10, 27, 19, 0)), now=now)
    mid = await _with_pick(db_session, "441964")
    assert not await confirm_result(db_session, mid, home=3, away=2, decided_in="ot", now=now)
    assert not await confirm_result(db_session, mid, home=2, away=3, decided_in="ot", now=now + timedelta(minutes=20))
    row = await _match(db_session, "441964")
    assert row.status == "review"


async def test_missing_or_odd_ending_goes_to_review(db_session) -> None:
    from src.application.extraliga import confirm_result

    now = _minsk(2026, 10, 27, 22, 0)
    await upsert_calendar_match(db_session, _yunost_neman("441964", _minsk(2026, 10, 27, 19, 0)), now=now)
    mid = await _with_pick(db_session, "441964")
    assert not await confirm_result(db_session, mid, home=4, away=2, decided_in="ot", now=now)  # разница 2 в ОТ
    assert (await _match(db_session, "441964")).status == "review"
    assert not await confirm_result(db_session, mid, home=3, away=2, decided_in=None, now=now)


async def test_moved_match_voids_late_picks_and_keeps_early_ones(db_session) -> None:
    now = _minsk(2026, 10, 28, 12, 0)
    m = _yunost_neman("441978", _minsk(2026, 10, 29, 19, 0))
    await upsert_calendar_match(db_session, m, now=now)
    mid = await _with_pick(db_session, "441978")
    await db_session.execute(
        text("UPDATE hockey_picks SET picked_at = :t WHERE match_id = :m"), {"t": _minsk(2026, 10, 29, 18, 0), "m": mid}
    )
    # Перенесли на 17:00 того же дня: ход в 18:00 оказался после нового срока — аннулируется.
    await upsert_calendar_match(db_session, replace(m, starts_at=_minsk(2026, 10, 29, 17, 0)), now=now)
    assert (
        await db_session.execute(text("SELECT count(*) FROM hockey_picks WHERE match_id = :m"), {"m": mid})
    ).scalar_one() == 0


# ── живой счёт (TASK-334 S6) ─────────────────────────────────────────


def _live_page(score: tuple[int, int] | None = None) -> str:
    page = _page("hockeyby-gamecenter-441964-ot.html").replace(
        'game-header-info-current">Официальные данные<', 'game-header-info-current">3-й период<'
    )
    if score:
        import re

        page = re.sub(
            r'(game-header-info-score">\s*<span[^>]*>\s*)\d+(\s*</span>\s*:\s*<span[^>]*>\s*)\d+',
            rf"\g<1>{score[0]}\g<2>{score[1]}",
            page,
        )
    return page


@pytest.mark.asyncio
async def test_live_score_is_polled_every_15_minutes_and_never_touches_the_result(db_session) -> None:
    start = _minsk(2026, 10, 27, 19, 0)
    await upsert_calendar_match(db_session, _yunost_neman("441964", start), now=start - timedelta(days=1))
    url = match_page_url("441964")
    now = start + timedelta(minutes=50)
    counts = await sync_details(db_session, FakeSource([], {url: _live_page((1, 0))}), now=now)
    assert counts["live"] == 1
    row = await _match(db_session, "441964")
    assert (row.status, row.home_score) == ("scheduled", None)
    live = (
        await db_session.execute(
            text("SELECT live_home_score, live_away_score FROM hockey_matches WHERE source_match_id = '441964'")
        )
    ).one()
    assert tuple(live) == (1, 0)

    # Раньше чем через 15 минут страницу не читаем; позже — счёт обновляется.
    quiet = FakeSource([], {url: _live_page((2, 0))})
    assert (await sync_details(db_session, quiet, now=now + timedelta(minutes=5)))["checked"] == 0
    assert quiet.asked == []
    assert (await sync_details(db_session, quiet, now=now + timedelta(minutes=16)))["live"] == 1
    live = (
        await db_session.execute(text("SELECT live_home_score FROM hockey_matches WHERE source_match_id = '441964'"))
    ).scalar_one()
    assert live == 2


@pytest.mark.asyncio
async def test_live_poll_failure_keeps_score_and_result(db_session) -> None:
    start = _minsk(2026, 10, 27, 19, 0)
    await upsert_calendar_match(db_session, _yunost_neman("441964", start), now=start - timedelta(days=1))
    url = match_page_url("441964")
    now = start + timedelta(minutes=50)
    await sync_details(db_session, FakeSource([], {url: _live_page((1, 0))}), now=now)

    class Broken(FakeSource):
        async def get(self, url: str) -> str:
            raise OSError("hockey.by is down")

    counts = await sync_details(db_session, Broken([]), now=now + timedelta(minutes=20))
    assert counts["failed"] == 1 and counts["live"] == 0
    row = (
        await db_session.execute(
            text("SELECT status, live_home_score FROM hockey_matches WHERE source_match_id = '441964'")
        )
    ).one()
    assert tuple(row) == ("scheduled", 1)


@pytest.mark.asyncio
async def test_live_poll_stops_with_the_final(db_session) -> None:
    start = _minsk(2026, 10, 27, 19, 0)
    await upsert_calendar_match(db_session, _yunost_neman("441964", start), now=start - timedelta(days=1))
    url = match_page_url("441964")
    now = start + timedelta(minutes=50)
    await sync_details(db_session, FakeSource([], {url: _live_page((1, 0))}), now=now)
    official = FakeSource([], {url: _page("hockeyby-gamecenter-441964-ot.html")})
    counts = await sync_details(db_session, official, now=now + timedelta(hours=2))
    assert counts["final"] == 1 and counts["live"] == 0
    # Итог стоит; поздний «неофициальный» ответ счёт уже не пишет.
    later = FakeSource([], {url: _live_page((9, 9))})
    await sync_details(db_session, later, now=now + timedelta(hours=4))
    row = (
        await db_session.execute(
            text("SELECT status, home_score, live_home_score FROM hockey_matches WHERE source_match_id = '441964'")
        )
    ).one()
    assert tuple(row) == ("final", 3, 1)


def test_site_form_pills_have_readable_labels_and_titles() -> None:
    from src.application.site_matches_page import _form_marks, _where_card

    html = _form_marks(["В", "П", "Во", "По", "Вб", "Пб"])
    assert [x.split(">")[1].split("<")[0] for x in html.split("</i>")[:-1]] == ["В", "П", "В·ОТ", "П·ОТ", "В·ОТ", "П·ОТ"]
    assert 'title="Победа в овертайме"' in html and 'title="Поражение по буллитам"' in html
    assert html.count("data-win") == 3
    card = _where_card({"arena": {"address": "ул. А, 1", "latitude": 53.9, "longitude": 27.5}, "arena_name": "Арена", "city": "Минск"})
    assert "Яндекс Карты" in card and "Google" not in card
