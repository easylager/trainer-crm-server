"""TASK-296: итог матча Динамо-Минск — сверка двух источников, ручная проверка, ручной ввод."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from src.application.hockey_matches import (
    KIND_FINAL,
    KIND_REVIEW,
    KIND_WAIT,
    CalendarEmpty,
    LoopHealth,
    check_due_results,
    result_window_open,
    decide_result,
    match_url,
    run_tick,
    set_manual_result,
    sync_calendar,
    get_match,
    upsert_calendar_match,
    validate_result,
)
from src.ingestion.hockey_sources import (
    HCDINAMO_CALENDAR_URL,
    HOCKEY_BY_URL,
    MINSK_TZ,
    TickerResult,
    parse_hcdinamo_match,
    parse_hockey_by_ticker,
)

FIXTURES = Path(__file__).resolve().parents[2] / "data/fixtures/hockey"


def _page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _match(name: str, mid: str):
    return parse_hcdinamo_match(_page(f"hcdinamo-match-{name}.html"), source_match_id=mid)


def _ticker() -> list[TickerResult]:
    return parse_hockey_by_ticker(_page("hockey-by-ticker.html"))


def _khl(day: date, teams: tuple[str, str], points: tuple[int, int], extra: str | None = None) -> TickerResult:
    return TickerResult("1", "КХЛ", day, True, teams, points, extra)


def _minsk(*args: int) -> datetime:
    return datetime(*args, tzinfo=MINSK_TZ)


# --- чистое решение ---


def test_two_sources_agree_final_regulation() -> None:
    page = _match("final", "1218869")
    d = decide_result(page, _ticker(), starts_at=page.starts_at, now=_minsk(2026, 10, 18, 20, 0))
    assert (d.kind, d.home_score, d.away_score, d.decided_in) == (KIND_FINAL, 1, 4, "regulation")


def test_too_early_waits() -> None:
    page = _match("final", "1218869")
    d = decide_result(page, _ticker(), starts_at=page.starts_at, now=_minsk(2026, 10, 18, 18, 30))
    assert d.kind == KIND_WAIT


def test_overtime_confirmed_with_away_dinamo() -> None:
    page = _match("ot", "1218838")
    ticker = [_khl(date(2026, 9, 24), ("Динамо М", "Динамо Мн"), (4, 3), "ОТ")]
    d = decide_result(page, ticker, starts_at=page.starts_at, now=_minsk(2026, 9, 24, 22, 30))
    assert (d.kind, d.home_score, d.away_score, d.decided_in) == (KIND_FINAL, 4, 3, "ot")


def test_shootout_is_official_score_plus_one() -> None:
    page = _match("so", "1218851")
    ticker = [_khl(date(2026, 10, 5), ("Динамо Мн", "Торпедо"), (1, 2), "Б")]
    d = decide_result(page, ticker, starts_at=page.starts_at, now=_minsk(2026, 10, 5, 22, 30))
    assert (d.kind, d.home_score, d.away_score, d.decided_in) == (KIND_FINAL, 1, 2, "so")


def test_shootout_without_marker_goes_to_review() -> None:
    page = _match("so", "1218851")
    ticker = [_khl(date(2026, 10, 5), ("Динамо Мн", "Торпедо"), (1, 2), None)]
    d = decide_result(page, ticker, starts_at=page.starts_at, now=_minsk(2026, 10, 5, 22, 30))
    assert d.kind == KIND_REVIEW and "как решён" in d.reason


def test_sources_disagree_goes_to_review_at_once() -> None:
    page = _match("final", "1218869")
    ticker = [_khl(date(2026, 10, 18), ("Динамо Мн", "Ак Барс"), (2, 4))]
    d = decide_result(page, ticker, starts_at=page.starts_at, now=_minsk(2026, 10, 18, 19, 30))
    assert d.kind == KIND_REVIEW and "не совпал" in d.reason


def test_live_looking_score_without_confirmation_waits_then_reviews() -> None:
    page = _match("final", "1218869")
    assert decide_result(page, [], starts_at=page.starts_at, now=_minsk(2026, 10, 18, 20, 0)).kind == KIND_WAIT
    late = decide_result(page, [], starts_at=page.starts_at, now=_minsk(2026, 10, 18, 21, 0))
    assert late.kind == KIND_REVIEW and "hockey.by" in late.reason


def test_no_score_four_hours_after_start_reviews() -> None:
    page = _match("upcoming", "1218873")
    d = decide_result(page, _ticker(), starts_at=page.starts_at, now=_minsk(2026, 10, 22, 23, 45))
    assert d.kind == KIND_REVIEW and "нет итогового счёта" in d.reason


def test_tied_score_never_final() -> None:
    page = replace(_match("final", "1218869"), home_score=1, away_score=1, parts=((1, 1), (0, 0), (0, 0)))
    ticker = [_khl(date(2026, 10, 18), ("Динамо Мн", "Ак Барс"), (1, 1))]
    d = decide_result(page, ticker, starts_at=page.starts_at, now=_minsk(2026, 10, 18, 21, 30))
    assert d.kind == KIND_REVIEW


@pytest.mark.parametrize(
    ("home", "away", "decided", "ok"),
    [
        (3, 2, "regulation", True),
        (5, 1, "regulation", True),
        (2, 1, "so", True),
        (3, 1, "ot", False),
        (2, 2, "regulation", False),
        (-1, 2, "regulation", False),
        (2, 1, "x", False),
    ],
)
def test_validate_result(home: int, away: int, decided: str, ok: bool) -> None:
    if ok:
        validate_result(home, away, decided)
    else:
        with pytest.raises(ValueError):
            validate_result(home, away, decided)


# --- база ---


def _fake_fetch(pages: dict[str, str]):
    async def fetch(url: str) -> str:
        return pages[url]

    return fetch


async def _row(db_session, source_match_id: str) -> int:
    return (
        await db_session.execute(
            text("SELECT id FROM hockey_matches WHERE source = 'hcdinamo' AND source_match_id = :m"),
            {"m": source_match_id},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_upsert_inserts_moves_and_freezes_final(db_session) -> None:
    now = _minsk(2026, 10, 19, 12, 0)
    page = _match("upcoming", "1218873")
    assert await upsert_calendar_match(db_session, page, now=now) == "inserted"
    assert await upsert_calendar_match(db_session, page, now=now) == "unchanged"
    moved = replace(page, starts_at=page.starts_at + timedelta(hours=1))
    assert await upsert_calendar_match(db_session, moved, now=now) == "moved"
    not_ours = replace(page, home="СКА", away="ЦСКА", source_match_id="999")
    assert await upsert_calendar_match(db_session, not_ours, now=now) == "skipped"

    mid = await _row(db_session, "1218873")
    await set_manual_result(db_session, mid, home_score=2, away_score=3, decided_in="regulation", now=now)
    assert await upsert_calendar_match(db_session, page, now=now) == "unchanged"


@pytest.mark.asyncio
async def test_sync_calendar_reads_window(db_session) -> None:
    pages = {
        HCDINAMO_CALENDAR_URL: '<a href="/matches/1218869/">x</a><a href="/matches/1218873/">y</a><a href="/matches/1/">z</a>'
    }
    pages[match_url("1218869")] = _page("hcdinamo-match-final.html")
    pages[match_url("1218873")] = _page("hcdinamo-match-upcoming.html")
    pages[match_url("1")] = "<html>сломано</html>"
    counts = await sync_calendar(db_session, _fake_fetch(pages), now=_minsk(2026, 10, 19, 12, 0))
    assert counts["inserted"] == 2 and counts["failed"] == 1


@pytest.mark.asyncio
async def test_due_result_published_when_sources_agree(db_session) -> None:
    await upsert_calendar_match(db_session, _match("final", "1218869"), now=_minsk(2026, 10, 18, 12, 0))
    pages = {match_url("1218869"): _page("hcdinamo-match-final.html"), HOCKEY_BY_URL: _page("hockey-by-ticker.html")}
    alerts: list[str] = []

    async def alert(body: str) -> bool:
        alerts.append(body)
        return True

    out = await check_due_results(db_session, _fake_fetch(pages), now=_minsk(2026, 10, 18, 20, 0), alert=alert)
    assert [k for _, k in out] == [KIND_FINAL]
    row = await get_match(db_session, out[0][0])
    assert (row.status, row.home_score, row.away_score, row.decided_in, row.result_source) == (
        "final",
        1,
        4,
        "regulation",
        "auto",
    )
    assert alerts == []
    # Сыгранный матч больше не проверяется.
    assert await check_due_results(db_session, _fake_fetch(pages), now=_minsk(2026, 10, 18, 20, 10), alert=alert) == []


@pytest.mark.asyncio
async def test_disagreement_alerts_once_then_manual_closes(db_session) -> None:
    await upsert_calendar_match(db_session, _match("final", "1218869"), now=_minsk(2026, 10, 18, 12, 0))
    wrong = re.sub(
        r'(Динамо Мн</span>\s*<span class="hsc-team-points">)1<',
        r"\g<1>2<",
        _page("hockey-by-ticker.html"),
    )
    assert wrong != _page("hockey-by-ticker.html")
    pages = {match_url("1218869"): _page("hcdinamo-match-final.html"), HOCKEY_BY_URL: wrong}
    alerts: list[str] = []

    async def alert(body: str) -> bool:
        alerts.append(body)
        return True

    first = await check_due_results(db_session, _fake_fetch(pages), now=_minsk(2026, 10, 18, 20, 0), alert=alert)
    second = await check_due_results(db_session, _fake_fetch(pages), now=_minsk(2026, 10, 18, 20, 10), alert=alert)
    assert [k for _, k in first] == [KIND_REVIEW] and [k for _, k in second] == [KIND_REVIEW]
    assert len(alerts) == 1 and "Динамо-Минск — Ак Барс" in alerts[0]

    row = await set_manual_result(
        db_session, first[0][0], home_score=1, away_score=4, decided_in="regulation", now=_minsk(2026, 10, 18, 21, 0)
    )
    assert (row.status, row.result_source, row.review_reason) == ("final", "manual", None)
    assert await check_due_results(db_session, _fake_fetch(pages), now=_minsk(2026, 10, 18, 21, 10), alert=alert) == []


def _window_pages() -> dict[str, str]:
    pages = {
        HCDINAMO_CALENDAR_URL: '<a href="/matches/1218869/">x</a><a href="/matches/1218873/">y</a><a href="/matches/1/">z</a>'
    }
    pages[match_url("1218869")] = _page("hcdinamo-match-final.html")
    pages[match_url("1218873")] = _page("hcdinamo-match-upcoming.html")
    pages[match_url("1")] = "<html>сломано</html>"
    pages[HOCKEY_BY_URL] = _page("hockey-by-ticker.html")
    return pages


async def _silent(_body: str) -> bool:
    return True


@pytest.mark.asyncio
async def test_run_tick_calendar_due_inserts_window(db_session) -> None:
    pages = _window_pages()
    counts = await run_tick(
        db_session, _fake_fetch(pages), now=_minsk(2026, 10, 19, 12, 0), alert=_silent, calendar_due=True
    )
    assert counts["calendar"]["inserted"] == 2 and counts["calendar"]["failed"] == 1
    stored = (await db_session.execute(text("SELECT COUNT(*) FROM hockey_matches"))).scalar_one()
    assert stored == 2


@pytest.mark.asyncio
async def test_run_tick_without_calendar_due_leaves_calendar(db_session) -> None:
    pages = _window_pages()
    await run_tick(db_session, _fake_fetch(pages), now=_minsk(2026, 10, 19, 12, 0), alert=_silent, calendar_due=True)
    seen: list[str] = []

    async def fetch(url: str) -> str:
        seen.append(url)
        if url == HCDINAMO_CALENDAR_URL:
            raise AssertionError("календарь не должен запрашиваться")
        return pages[url]

    before = (await db_session.execute(text("SELECT COUNT(*) FROM hockey_matches"))).scalar_one()
    counts = await run_tick(db_session, fetch, now=_minsk(2026, 10, 19, 12, 10), alert=_silent, calendar_due=False)
    after = (await db_session.execute(text("SELECT COUNT(*) FROM hockey_matches"))).scalar_one()
    assert counts["calendar"] is None
    assert before == after == 2
    assert HCDINAMO_CALENDAR_URL not in seen


@pytest.mark.asyncio
async def test_run_tick_publishes_played_match(db_session) -> None:
    pages = {match_url("1218869"): _page("hcdinamo-match-final.html"), HOCKEY_BY_URL: _page("hockey-by-ticker.html")}
    await upsert_calendar_match(db_session, _match("final", "1218869"), now=_minsk(2026, 10, 18, 12, 0))
    counts = await run_tick(
        db_session, _fake_fetch(pages), now=_minsk(2026, 10, 18, 20, 0), alert=_silent, calendar_due=False
    )
    assert counts["final"] == 1 and counts["calendar"] is None
    row = (
        await db_session.execute(text("SELECT status, home_score, away_score, result_source FROM hockey_matches"))
    ).one()
    assert tuple(row) == ("final", 1, 4, "auto")


@pytest.mark.asyncio
async def test_manual_result_rejects_tie_and_unknown_match(db_session) -> None:
    with pytest.raises(LookupError):
        await set_manual_result(
            db_session, 987654, home_score=2, away_score=1, decided_in="regulation", now=_minsk(2026, 10, 18, 21, 0)
        )
    with pytest.raises(ValueError):
        await set_manual_result(
            db_session, 987654, home_score=2, away_score=2, decided_in="regulation", now=_minsk(2026, 10, 18, 21, 0)
        )


@pytest.mark.asyncio
async def test_run_tick_calendar_failure_still_checks_results(db_session) -> None:
    await upsert_calendar_match(db_session, _match("final", "1218869"), now=_minsk(2026, 10, 18, 12, 0))
    pages = {match_url("1218869"): _page("hcdinamo-match-final.html"), HOCKEY_BY_URL: _page("hockey-by-ticker.html")}

    async def fetch(url: str) -> str:
        if url == HCDINAMO_CALENDAR_URL:
            raise TimeoutError("hcdinamo.by не ответил")
        return pages[url]

    counts = await run_tick(db_session, fetch, now=_minsk(2026, 10, 18, 20, 0), alert=_silent, calendar_due=True)
    assert counts["calendar_failed"] is True and counts["calendar"] is None
    assert counts["final"] == 1


@pytest.mark.asyncio
async def test_long_past_match_from_calendar_window_is_not_inserted(db_session) -> None:
    # Живой прогон 2026-10-19: окно /matches/ отдаёт и матчи двухнедельной давности.
    page = _match("final", "1218869")
    assert await upsert_calendar_match(db_session, page, now=page.starts_at + timedelta(days=4)) == "skipped"


@pytest.mark.asyncio
async def test_stale_scheduled_match_goes_to_review_with_one_alert(db_session) -> None:
    page = _match("final", "1218869")
    await upsert_calendar_match(db_session, page, now=page.starts_at - timedelta(days=1))
    alerts: list[str] = []

    async def alert(body: str) -> bool:
        alerts.append(body)
        return True

    later = page.starts_at + timedelta(days=4)
    first = await check_due_results(db_session, _fake_fetch({}), now=later, alert=alert)
    second = await check_due_results(db_session, _fake_fetch({}), now=later + timedelta(minutes=10), alert=alert)
    assert [k for _, k in first] == [KIND_REVIEW] and second == []
    assert len(alerts) == 1 and "больше 3 дней" in alerts[0]


@pytest.mark.asyncio
async def test_empty_calendar_in_season_is_a_failure_and_off_season_is_quiet(db_session) -> None:
    pages = {HCDINAMO_CALENDAR_URL: "<html>новая вёрстка без ссылок</html>"}
    with pytest.raises(CalendarEmpty):
        await sync_calendar(db_session, _fake_fetch(pages), now=_minsk(2026, 10, 19, 12, 0))
    counts = await sync_calendar(db_session, _fake_fetch(pages), now=_minsk(2026, 7, 1, 12, 0))
    assert counts["inserted"] == 0
    tick = await run_tick(db_session, _fake_fetch(pages), now=_minsk(2026, 10, 19, 12, 0), alert=_silent, calendar_due=True)
    assert tick["calendar_failed"] is True and "вёрстка" in str(tick["calendar_error"])


@pytest.mark.asyncio
async def test_result_window_drives_the_fast_loop(db_session) -> None:
    await upsert_calendar_match(db_session, _match("final", "1218869"), now=_minsk(2026, 10, 18, 12, 0))
    start = (await get_match(db_session, await _row(db_session, "1218869"))).starts_at
    assert await result_window_open(db_session, now=start + timedelta(hours=1)) is False
    assert await result_window_open(db_session, now=start + timedelta(hours=2)) is True
    assert await result_window_open(db_session, now=start + timedelta(hours=3)) is True
    assert await result_window_open(db_session, now=start + timedelta(hours=4)) is False


def test_loop_health_alerts_once_after_three_failures_and_rearms() -> None:
    health = LoopHealth()
    assert health.failed("календарь матчей", "timeout") is None
    assert health.failed("календарь матчей", "timeout") is None
    text_ = health.failed("календарь матчей", "timeout")
    assert text_ and "3 раз подряд" in text_ and "/hockey" in text_
    assert health.failed("календарь матчей", "timeout") is None
    health.ok("календарь матчей")
    assert health.failed("календарь матчей", "timeout") is None
