"""TASK-364: запасной источник матчей Динамо — sportmail.ru, когда hcdinamo.by / hockey.by молчат."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from src.application import hockey_matches as hm
from src.application.hockey_matches import (
    KIND_FINAL,
    KIND_REVIEW,
    KIND_WAIT,
    LoopHealth,
    check_due_results,
    get_match,
    run_tick,
    sync_calendar_fallback,
    upsert_calendar_match,
)
from src.ingestion.hockey_sources import (
    HCDINAMO_CALENDAR_URL,
    HOCKEY_BY_URL,
    MINSK_TZ,
    TickerResult,
    parse_hcdinamo_match,
)
from src.ingestion.sportmail_sources import (
    SPORTMAIL_DINAMO_MATCHES_URL,
    parse_sportmail_match,
    parse_sportmail_team_matches,
    sportmail_match_url,
)

FIXTURES = Path(__file__).resolve().parents[2] / "data/fixtures/hockey"
SOCHI = "8129336"  # 08.11.2026 17:00 ХК Сочи — Динамо-Минск 3:2, овертайм


def _fx(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _minsk(*args: int) -> datetime:
    return datetime(*args, tzinfo=MINSK_TZ)


async def _silent(_: str) -> bool:
    return True


def _hcd(source_match_id: str, starts_at: datetime, home: str, away: str):
    base = parse_hcdinamo_match(_fx("hcdinamo-match-upcoming.html"), source_match_id=source_match_id)
    return replace(base, source_match_id=source_match_id, starts_at=starts_at, home=home, away=away)


async def _down(url: str) -> str:
    raise TimeoutError(f"{url} не ответил")


def _fetch_with(pages: dict[str, str]):
    """Всё, чего нет в ``pages``, — таймаут: так выглядит недоступный сайт."""

    async def fetch(url: str) -> str:
        if url not in pages:
            raise TimeoutError(f"{url} не ответил")
        return pages[url]

    return fetch


# --- разбор ---


def test_team_table_gives_score_and_how_it_was_decided() -> None:
    rows = {m.source_match_id: m for m in parse_sportmail_team_matches(_fx("sportmail-team-matches.html"))}
    assert len(rows) == 6
    ot = rows[SOCHI]
    assert (ot.home, ot.away, ot.home_score, ot.away_score, ot.decided_in) == ("ХК Сочи", "Динамо-Минск", 3, 2, "ot")
    assert ot.starts_at == _minsk(2026, 11, 8, 17, 0)
    shootout = rows["8129089"]
    assert (shootout.home_score, shootout.away_score, shootout.decided_in) == (3, 4, "so")
    regular = rows["8129116"]
    assert (regular.home, regular.decided_in) == ("Лада", "regulation")


def test_unplayed_rows_have_no_score_and_names_match_ours() -> None:
    rows = {m.source_match_id: m for m in parse_sportmail_team_matches(_fx("sportmail-team-matches.html"))}
    ska = rows["8129355"]
    assert ska.played is False and ska.home_score is None and ska.decided_in is None
    assert (ska.home, ska.away) == ("СКА", "Динамо-Минск")
    # «Динамо М» у sportmail — Москва, а не Минск.
    assert (rows["8129109"].home, rows["8129109"].away) == ("Динамо Москва", "Динамо-Минск")


def test_match_page_states() -> None:
    played = parse_sportmail_match(_fx("sportmail-match-played.html"))
    assert (played.home, played.away, played.home_score, played.away_score) == ("ХК Сочи", "Динамо-Минск", 3, 2)
    assert played.is_played and not played.is_online
    scheduled = parse_sportmail_match(_fx("sportmail-match-scheduled.html"))
    assert scheduled.home_score is None and not scheduled.is_played


def test_page_without_state_is_a_loud_failure() -> None:
    with pytest.raises(ValueError, match="сменилась вёрстка"):
        parse_sportmail_team_matches("<html>другая страница</html>")


# --- календарь ---


@pytest.mark.asyncio
async def test_calendar_fallback_inserts_upcoming_and_is_idempotent(db_session) -> None:
    now = _minsk(2026, 11, 9, 12, 0)
    fetch = _fetch_with({SPORTMAIL_DINAMO_MATCHES_URL: _fx("sportmail-team-matches.html")})
    first = await sync_calendar_fallback(db_session, fetch, now=now)
    assert (first["inserted"], first["moved"]) == (2, 0)  # 10.11 Авангард и 13.11 СКА; сыгранные не заводим
    again = await sync_calendar_fallback(db_session, fetch, now=now)
    assert (again["inserted"], again["unchanged"]) == (0, 2)
    ids = (
        (
            await db_session.execute(
                text("SELECT source_match_id FROM hockey_matches WHERE source = 'hcdinamo' ORDER BY starts_at")
            )
        )
        .scalars()
        .all()
    )
    assert ids == ["sm8129342", "sm8129355"]


@pytest.mark.asyncio
async def test_calendar_fallback_keeps_the_primary_horizon(db_session) -> None:
    fetch = _fetch_with({SPORTMAIL_DINAMO_MATCHES_URL: _fx("sportmail-team-matches.html")})
    # 7 октября 10.11 — через 34 дня (в горизонте), 13.11 — через 37 (за ним).
    counts = await sync_calendar_fallback(db_session, fetch, now=_minsk(2026, 10, 7, 12, 0))
    assert counts["inserted"] == 1


@pytest.mark.asyncio
async def test_calendar_fallback_trusts_the_primary_time_on_the_same_day(db_session) -> None:
    now = _minsk(2026, 11, 9, 12, 0)
    await upsert_calendar_match(
        db_session, _hcd("1218891", _minsk(2026, 11, 13, 19, 25), "СКА", "Динамо-Минск"), now=now
    )
    fetch = _fetch_with({SPORTMAIL_DINAMO_MATCHES_URL: _fx("sportmail-team-matches.html")})
    counts = await sync_calendar_fallback(db_session, fetch, now=now)
    assert counts["inserted"] == 1  # только Авангард
    starts = (
        await db_session.execute(text("SELECT starts_at FROM hockey_matches WHERE source_match_id = '1218891'"))
    ).scalar_one()
    assert starts.astimezone(MINSK_TZ).hour == 19 and starts.astimezone(MINSK_TZ).minute == 25


@pytest.mark.asyncio
async def test_calendar_fallback_moves_a_rescheduled_match_instead_of_duplicating(db_session) -> None:
    now = _minsk(2026, 11, 9, 12, 0)
    # У нас СКА стоял на 12.11, sportmail.ru ставит на 13.11: это один матч.
    await upsert_calendar_match(
        db_session, _hcd("1218891", _minsk(2026, 11, 12, 19, 30), "СКА", "Динамо-Минск"), now=now
    )
    fetch = _fetch_with({SPORTMAIL_DINAMO_MATCHES_URL: _fx("sportmail-team-matches.html")})
    counts = await sync_calendar_fallback(db_session, fetch, now=now)
    assert (counts["moved"], counts["inserted"]) == (1, 1)
    rows = (
        await db_session.execute(
            text("SELECT source_match_id, starts_at FROM hockey_matches WHERE source = 'hcdinamo' ORDER BY starts_at")
        )
    ).all()
    assert [r.source_match_id for r in rows] == ["sm8129342", "1218891"]
    assert rows[1].starts_at.astimezone(MINSK_TZ).day == 13


@pytest.mark.asyncio
async def test_calendar_fallback_skips_a_club_we_do_not_know(db_session) -> None:
    now = _minsk(2026, 11, 9, 12, 0)
    html = _fx("sportmail-team-matches.html").replace("Авангард", "Неизвестный клуб")
    counts = await sync_calendar_fallback(db_session, _fetch_with({SPORTMAIL_DINAMO_MATCHES_URL: html}), now=now)
    assert (counts["inserted"], counts["skipped"]) == (1, 1)


@pytest.mark.asyncio
async def test_primary_returning_adopts_the_fallback_row(db_session) -> None:
    now = _minsk(2026, 11, 9, 12, 0)
    await sync_calendar_fallback(
        db_session, _fetch_with({SPORTMAIL_DINAMO_MATCHES_URL: _fx("sportmail-team-matches.html")}), now=now
    )
    page = _hcd("1218891", _minsk(2026, 11, 13, 19, 30), "СКА", "Динамо-Минск")
    assert await upsert_calendar_match(db_session, page, now=now) == "unchanged"
    ids = (
        (
            await db_session.execute(
                text(
                    "SELECT source_match_id FROM hockey_matches WHERE (starts_at AT TIME ZONE 'Europe/Minsk')::date = '2026-11-13'"
                )
            )
        )
        .scalars()
        .all()
    )
    assert ids == ["1218891"]  # ни дубля, ни «sm…»


@pytest.mark.asyncio
async def test_run_tick_uses_the_fallback_when_the_primary_calendar_is_down(db_session) -> None:
    fetch = _fetch_with({SPORTMAIL_DINAMO_MATCHES_URL: _fx("sportmail-team-matches.html")})
    counts = await run_tick(db_session, fetch, now=_minsk(2026, 11, 9, 12, 0), alert=_silent, calendar_due=True)
    assert counts["calendar_failed"] is True  # основной не отвечает: алерт админам по-прежнему нужен
    assert counts["calendar_via"] == "sportmail.ru" and counts["calendar"]["inserted"] == 2


@pytest.mark.asyncio
async def test_run_tick_without_any_calendar_source_reports_failure(db_session) -> None:
    counts = await run_tick(db_session, _down, now=_minsk(2026, 11, 9, 12, 0), alert=_silent, calendar_due=True)
    assert counts["calendar_failed"] is True and counts["calendar"] is None and counts["calendar_via"] is None


def test_alert_tells_when_a_fallback_is_running() -> None:
    health = LoopHealth()
    texts = [health.failed("календарь матчей", "таймаут", note="Работаем на sportmail.ru") for _ in range(3)]
    assert texts[:2] == [None, None]
    assert "Работаем на sportmail.ru" in texts[2] and "не обновляются" not in texts[2]


# --- итоги ---


async def _sochi_row(db_session) -> int:
    await upsert_calendar_match(
        db_session,
        _hcd("1218887", _minsk(2026, 11, 8, 17, 0), "ХК Сочи", "Динамо-Минск"),
        now=_minsk(2026, 11, 8, 12, 0),
    )
    return (
        await db_session.execute(text("SELECT id FROM hockey_matches WHERE source_match_id = '1218887'"))
    ).scalar_one()


@pytest.mark.asyncio
async def test_result_from_sportmail_when_both_primary_sources_are_down(db_session) -> None:
    mid = await _sochi_row(db_session)
    fetch = _fetch_with(
        {
            SPORTMAIL_DINAMO_MATCHES_URL: _fx("sportmail-team-matches.html"),
            sportmail_match_url(SOCHI): _fx("sportmail-match-played.html"),
        }
    )
    out = await check_due_results(db_session, fetch, now=_minsk(2026, 11, 8, 20, 0), alert=_silent)
    assert out == [(mid, KIND_FINAL)]
    row = await get_match(db_session, mid)
    assert (row.status, row.home_score, row.away_score, row.decided_in) == ("final", 3, 2, "ot")


@pytest.mark.asyncio
async def test_sportmail_alone_waits_when_its_match_page_does_not_say_played(db_session) -> None:
    mid = await _sochi_row(db_session)
    fetch = _fetch_with(
        {
            SPORTMAIL_DINAMO_MATCHES_URL: _fx("sportmail-team-matches.html"),
            sportmail_match_url(SOCHI): _fx("sportmail-match-scheduled.html"),
        }
    )
    out = await check_due_results(db_session, fetch, now=_minsk(2026, 11, 8, 20, 0), alert=_silent)
    assert out == [(mid, KIND_WAIT)]
    assert (await get_match(db_session, mid)).status == "scheduled"


@pytest.mark.asyncio
async def test_all_sources_down_changes_nothing_and_reviews_after_the_deadline(db_session) -> None:
    mid = await _sochi_row(db_session)
    early = await check_due_results(db_session, _down, now=_minsk(2026, 11, 8, 20, 0), alert=_silent)
    assert early == [(mid, KIND_WAIT)]
    late = await check_due_results(db_session, _down, now=_minsk(2026, 11, 8, 21, 0), alert=_silent)
    assert late == [(mid, KIND_REVIEW)]


def _sochi_confirm(points: tuple[int, int], extra: str | None = "ОТ") -> TickerResult:
    return TickerResult("1", "КХЛ", date(2026, 11, 8), True, ("Сочи", "Динамо Мн"), points, extra)


async def _decide_with_sportmail(db_session, *, page, ticker):
    mid = await _sochi_row(db_session)
    row = await get_match(db_session, mid)
    plain = hm.decide_result(page, ticker, starts_at=row.starts_at, now=_minsk(2026, 11, 8, 20, 0))
    fetch = _fetch_with({SPORTMAIL_DINAMO_MATCHES_URL: _fx("sportmail-team-matches.html")})
    cache = hm._SportmailCache(fetch)  # noqa: SLF001
    return await hm._sportmail_decision(  # noqa: SLF001
        row, plain, page, ticker, cache, fetch, now=_minsk(2026, 11, 8, 20, 0)
    )


@pytest.mark.asyncio
async def test_sportmail_stands_in_for_the_hcdinamo_page_when_hockey_by_confirms(db_session) -> None:
    d = await _decide_with_sportmail(db_session, page=None, ticker=[_sochi_confirm((3, 2))])
    assert (d.kind, d.home_score, d.away_score, d.decided_in) == (KIND_FINAL, 3, 2, "ot")


@pytest.mark.asyncio
async def test_sportmail_disagreeing_with_hockey_by_goes_to_review(db_session) -> None:
    d = await _decide_with_sportmail(db_session, page=None, ticker=[_sochi_confirm((4, 2), extra=None)])
    assert d.kind == KIND_REVIEW and "sportmail.ru" in (d.reason or "")


@pytest.mark.asyncio
async def test_sportmail_does_not_overrule_two_working_primary_sources(db_session) -> None:
    page = replace(
        parse_hcdinamo_match(_fx("hcdinamo-match-final.html"), source_match_id="x"),
        home="ХК Сочи",
        away="Динамо-Минск",
    )
    # Основные расходятся между собой — решение остаётся за ними, sportmail.ru его не меняет.
    d = await _decide_with_sportmail(db_session, page=page, ticker=[_sochi_confirm((3, 2))])
    plain = hm.decide_result(
        page, [_sochi_confirm((3, 2))], starts_at=_minsk(2026, 11, 8, 17, 0), now=_minsk(2026, 11, 8, 20, 0)
    )
    assert d == plain


@pytest.mark.asyncio
async def test_live_score_comes_from_sportmail_when_the_ticker_has_no_match(db_session, monkeypatch) -> None:
    mid = await _sochi_row(db_session)
    row = await get_match(db_session, mid)
    live = (
        _fx("sportmail-match-played.html")
        .replace('"is_played": true', '"is_played": false')
        .replace('"is_online": false', '"is_online": true')
    )
    # Табло идёт: таблица команды ещё без итога.
    table = _fx("sportmail-team-matches.html").replace('"text": "3:2"', '"text": "&minus;&nbsp;:&nbsp;&minus;"')
    fetch = _fetch_with({SPORTMAIL_DINAMO_MATCHES_URL: table, sportmail_match_url(SOCHI): live})
    seen: list[tuple[int, int, int]] = []

    async def fake_set_live_score(session, *, match_id, home, away, now):
        seen.append((match_id, home, away))

    monkeypatch.setattr("src.application.hockey_game.set_live_score", fake_set_live_score)
    await hm._sportmail_live(
        db_session, row, hm._SportmailCache(fetch), fetch, now=_minsk(2026, 11, 8, 18, 30)
    )  # noqa: SLF001
    assert seen == [(mid, 3, 2)]


def _live_page() -> str:
    return (
        _fx("sportmail-match-played.html")
        .replace('"is_played": true', '"is_played": false')
        .replace('"is_online": false', '"is_online": true')
    )


@pytest.mark.asyncio
async def test_live_score_is_taken_from_the_page_even_when_the_table_already_shows_a_score(
    db_session, monkeypatch
) -> None:
    # 10.11.2026: в таблице sportmail.ru у идущего матча уже стоит счёт; по нему матч считался сыгранным
    # и живой счёт у нас замирал.
    mid = await _sochi_row(db_session)
    row = await get_match(db_session, mid)
    fetch = _fetch_with(
        {SPORTMAIL_DINAMO_MATCHES_URL: _fx("sportmail-team-matches.html"), sportmail_match_url(SOCHI): _live_page()}
    )
    seen: list[tuple[int, int, int]] = []

    async def fake_set_live_score(session, *, match_id, home, away, now):
        seen.append((match_id, home, away))

    monkeypatch.setattr("src.application.hockey_game.set_live_score", fake_set_live_score)
    await hm._sportmail_live(
        db_session, row, hm._SportmailCache(fetch), fetch, now=_minsk(2026, 11, 8, 18, 30)
    )  # noqa: SLF001
    assert seen == [(mid, 3, 2)]


@pytest.mark.asyncio
async def test_live_tie_in_the_table_is_not_sent_to_review_and_a_live_score_is_not_a_result(db_session) -> None:
    mid = await _sochi_row(db_session)
    row = await get_match(db_session, mid)
    for score in ("0:0", "1:0"):
        table = _fx("sportmail-team-matches.html").replace('"text": "3:2"', f'"text": "{score}"')
        fetch = _fetch_with({SPORTMAIL_DINAMO_MATCHES_URL: table, sportmail_match_url(SOCHI): _live_page()})
        now = _minsk(2026, 11, 8, 19, 5)  # 2 ч 05 после старта: окно итога открыто, но страница матча «идёт»
        plain = hm.decide_result(None, [], starts_at=row.starts_at, now=now)
        d = await hm._sportmail_decision(  # noqa: SLF001
            row, plain, None, [], hm._SportmailCache(fetch), fetch, now=now
        )
        assert d.kind != KIND_FINAL and d == plain, score
        assert "ничьих" not in (d.reason or "")
