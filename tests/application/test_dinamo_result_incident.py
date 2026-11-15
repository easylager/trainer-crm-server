"""Инцидент 15.11.2026: идущий матч Динамо принят за сыгранный на 1 ч 50 мин после старта.

Правило: итог Динамо — только при независимом «матч завершён» (hockey.by ``completed`` или страница матча
sportmail.ru ``is_played``) и только со второго такого же опроса не раньше ``DINAMO_STABLE_AFTER``.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from src.application import hockey_matches as hm
from src.application.hockey_matches import (
    DINAMO_STABLE_AFTER,
    KIND_FINAL,
    KIND_REVIEW,
    KIND_WAIT,
    RESULT_CHECK_AFTER,
    REVIEW_AFTER,
    check_due_results,
    decide_result,
    get_match,
    set_manual_result,
    upsert_calendar_match,
)
from src.ingestion.hockey_sources import (
    HOCKEY_BY_URL,
    MINSK_TZ,
    HcdinamoMatch,
    TickerResult,
    parse_hcdinamo_match,
)
from src.ingestion.sportmail_sources import SPORTMAIL_DINAMO_MATCHES_URL, sportmail_match_url

FIXTURES = Path(__file__).resolve().parents[2] / "data/fixtures/hockey"
SOCHI = "8129336"  # 08.11.2026 17:00 ХК Сочи — Динамо-Минск
START = datetime(2026, 11, 8, 17, 0, tzinfo=MINSK_TZ)


def _fx(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _at(minutes: int) -> datetime:
    return START + timedelta(minutes=minutes)


async def _silent(_: str) -> bool:
    return True


# Таблица sportmail.ru: счёт 3:2 без пометки (у идущего матча она так и выглядит); страница матча — идёт / завершён.
TABLE_PLAIN = _fx("sportmail-team-matches.html").replace('"subtext": "(ОТ)"', '"subtext": ""')
PAGE_ONLINE = _fx("sportmail-match-played.html").replace('"is_played": true', '"is_played": false').replace(
    '"is_online": false', '"is_online": true'
)
PAGE_PLAYED = _fx("sportmail-match-played.html")


def _hcd_third_period() -> HcdinamoMatch:
    """Страница hcdinamo.by в третьем периоде: три части, счёт без ничьей — ``looks_final`` истинно."""
    base = parse_hcdinamo_match(_fx("hcdinamo-match-final.html"), source_match_id="1218887")
    page = replace(
        base, home="ХК Сочи", away="Динамо-Минск", home_score=3, away_score=2, parts=((1, 1), (1, 0), (1, 1))
    )
    assert page.looks_final
    return page


def _ticker(*, completed: bool) -> list[TickerResult]:
    return [TickerResult("1", "КХЛ", date(2026, 11, 8), completed, ("Сочи", "Динамо Мн"), (3, 2), None)]


class World:
    """Что сейчас показывают источники; ``fetch`` и разбор hcdinamo.by/hockey.by подменяются в ``install``."""

    def __init__(self) -> None:
        self.hcd: HcdinamoMatch | None = None
        self.ticker: list[TickerResult] = []
        self.table = TABLE_PLAIN
        self.sm_page: str | None = PAGE_ONLINE

    def install(self, monkeypatch):
        monkeypatch.setattr(hm, "parse_hcdinamo_match", lambda _html, source_match_id: self._hcd())
        monkeypatch.setattr(hm, "parse_hockey_by_ticker", lambda _html: self.ticker)

        async def fetch(url: str) -> str:
            if url == SPORTMAIL_DINAMO_MATCHES_URL:
                return self.table
            if url == sportmail_match_url(SOCHI):
                if self.sm_page is None:
                    raise TimeoutError(url)
                return self.sm_page
            if url == HOCKEY_BY_URL or "hcdinamo" in url:
                return ""
            raise TimeoutError(url)

        return fetch

    def _hcd(self) -> HcdinamoMatch:
        if self.hcd is None:
            raise TimeoutError("hcdinamo.by")
        return self.hcd


async def _sochi_row(db_session) -> int:
    base = parse_hcdinamo_match(_fx("hcdinamo-match-upcoming.html"), source_match_id="1218887")
    page = replace(base, starts_at=START, home="ХК Сочи", away="Динамо-Минск")
    await upsert_calendar_match(db_session, page, now=START - timedelta(hours=5))
    return (
        await db_session.execute(text("SELECT id FROM hockey_matches WHERE source_match_id = '1218887'"))
    ).scalar_one()


async def _poll(db_session, fetch, minutes: int) -> list[tuple[int, str]]:
    return await check_due_results(db_session, fetch, now=_at(minutes), alert=_silent)


# --- инцидент: идущий матч никогда не итог ---


@pytest.mark.asyncio
async def test_running_match_is_never_final_at_any_poll(db_session, monkeypatch) -> None:
    """hcdinamo.by (3 части, looks_final) + таблица sportmail со счётом + тикер без completed + страница online."""
    mid = await _sochi_row(db_session)
    world = World()
    world.hcd, world.ticker = _hcd_third_period(), _ticker(completed=False)
    fetch = world.install(monkeypatch)

    # 1 ч 50 / 2 ч 00 — не опрашиваем (порог 2 ч 15 мин): матч даже не выбирается.
    for minutes in (110, 120, 134):
        assert await _poll(db_session, fetch, minutes) == []
    # Дальше весь период до REVIEW_AFTER: ни одного итога, матч остаётся не финальным.
    for minutes in (135, 140, 150, 160, 170, 180, 200, 209):
        out = await _poll(db_session, fetch, minutes)
        assert [k for _, k in out] == [KIND_WAIT], minutes
        assert (await get_match(db_session, mid)).status == "scheduled"
    # Никто так и не подтвердил конец — после REVIEW_AFTER зовём человека, а не публикуем.
    out = await _poll(db_session, fetch, int(REVIEW_AFTER.total_seconds() // 60) + 1)
    assert [k for _, k in out] == [KIND_REVIEW]
    assert (await get_match(db_session, mid)).status == "review"


@pytest.mark.asyncio
async def test_running_match_with_sportmail_page_down_is_not_final(db_session, monkeypatch) -> None:
    mid = await _sochi_row(db_session)
    world = World()
    world.hcd, world.ticker, world.sm_page = _hcd_third_period(), _ticker(completed=False), None
    fetch = world.install(monkeypatch)
    for minutes in (135, 150, 170, 190):
        assert [k for _, k in await _poll(db_session, fetch, minutes)] == [KIND_WAIT]
    assert (await get_match(db_session, mid)).status == "scheduled"


def test_hcdinamo_alone_and_live_scores_agreeing_are_not_a_confirmation() -> None:
    """Чистое решение: looks_final без completed — ожидание на любом сроке до REVIEW_AFTER."""
    page = _hcd_third_period()
    for minutes in (110, 120, 140, 200):
        assert decide_result(page, _ticker(completed=False), starts_at=START, now=_at(minutes)).kind == KIND_WAIT
        assert decide_result(page, [], starts_at=START, now=_at(minutes)).kind == KIND_WAIT


@pytest.mark.asyncio
async def test_sportmail_table_score_without_page_confirmation_is_not_final(db_session) -> None:
    mid = await _sochi_row(db_session)
    row = await get_match(db_session, mid)
    page = _hcd_third_period()
    world = World()
    for sm_page in (PAGE_ONLINE, None):
        world.sm_page = sm_page
        fetch = _FetchOnly(world)
        cache = hm._SportmailCache(fetch)  # noqa: SLF001
        plain = decide_result(page, _ticker(completed=False), starts_at=START, now=_at(140))
        d = await hm._sportmail_decision(  # noqa: SLF001
            row, plain, page, _ticker(completed=False), cache, fetch, now=_at(140)
        )
        assert d.kind == KIND_WAIT


class _FetchOnly:
    """Только sportmail.ru (для прямых вызовов ``_sportmail_decision``)."""

    def __init__(self, world: World) -> None:
        self.world = world

    async def __call__(self, url: str) -> str:
        if url == SPORTMAIL_DINAMO_MATCHES_URL:
            return self.world.table
        if url == sportmail_match_url(SOCHI) and self.world.sm_page is not None:
            return self.world.sm_page
        raise TimeoutError(url)


# --- завершённый матч: два согласных опроса ---


@pytest.mark.asyncio
@pytest.mark.parametrize("proof", ["ticker", "sportmail_page"])
async def test_finished_match_is_final_only_after_second_agreeing_poll(db_session, monkeypatch, proof) -> None:
    mid = await _sochi_row(db_session)
    world = World()
    world.hcd = _hcd_third_period()
    if proof == "ticker":
        world.ticker = _ticker(completed=True)
    else:
        world.ticker, world.sm_page = _ticker(completed=False), PAGE_PLAYED
    fetch = world.install(monkeypatch)

    assert [k for _, k in await _poll(db_session, fetch, 140)] == [KIND_WAIT]  # первое чтение
    assert [k for _, k in await _poll(db_session, fetch, 145)] == [KIND_WAIT]  # меньше 10 минут
    assert [k for _, k in await _poll(db_session, fetch, 149)] == [KIND_WAIT]
    assert (await get_match(db_session, mid)).status == "scheduled"
    assert [k for _, k in await _poll(db_session, fetch, 150)] == [KIND_FINAL]  # ровно 10 минут
    row = await get_match(db_session, mid)
    assert (row.status, row.home_score, row.away_score, row.decided_in, row.result_source) == (
        "final",
        3,
        2,
        "regulation",
        "auto",
    )


@pytest.mark.asyncio
async def test_sportmail_page_alone_finishes_after_two_polls_when_both_primaries_are_down(
    db_session, monkeypatch
) -> None:
    mid = await _sochi_row(db_session)
    world = World()
    world.sm_page = PAGE_PLAYED
    fetch = world.install(monkeypatch)
    assert [k for _, k in await _poll(db_session, fetch, 140)] == [KIND_WAIT]
    assert [k for _, k in await _poll(db_session, fetch, 150)] == [KIND_FINAL]
    assert (await get_match(db_session, mid)).status == "final"


@pytest.mark.asyncio
async def test_polls_that_disagree_go_to_review_with_a_reason(db_session, monkeypatch) -> None:
    mid = await _sochi_row(db_session)
    world = World()
    world.hcd, world.ticker = _hcd_third_period(), _ticker(completed=True)
    fetch = world.install(monkeypatch)
    assert [k for _, k in await _poll(db_session, fetch, 140)] == [KIND_WAIT]

    # К следующему опросу «завершённый» матч показывает другой счёт (3:2 → 4:2), страница и тикер согласны между собой.
    world.hcd = replace(world.hcd, home_score=4, parts=((2, 1), (1, 0), (1, 1)))
    world.ticker = [replace(world.ticker[0], points=(4, 2))]
    out = await _poll(db_session, fetch, 152)
    assert [k for _, k in out] == [KIND_REVIEW]
    row = await get_match(db_session, mid)
    assert row.status == "review" and "менялся между опросами" in row.review_reason
    assert "3:2" in row.review_reason and "4:2" in row.review_reason
    # Липкая проверка: три тика с одним счётом, прошло больше 10 минут — финала нет, статус review.
    for minutes in (156, 164, 172, 190):
        assert [k for _, k in await _poll(db_session, fetch, minutes)] == [KIND_REVIEW]
        row = await get_match(db_session, mid)
        assert row.status == "review" and row.home_score is None
    probe = (await db_session.execute(text("SELECT result_probe FROM hockey_matches WHERE id = :i"), {"i": mid})).scalar_one()
    assert probe["conflict"] is True and probe["home"] == 4
    # Человек закрывает как обычно.
    closed = await set_manual_result(db_session, mid, home_score=3, away_score=2, decided_in="regulation", now=_at(200))
    assert (closed.status, closed.result_source, closed.home_score) == ("final", "manual", 3)


@pytest.mark.asyncio
async def test_plain_review_without_result_still_publishes_after_confirmation(db_session, monkeypatch) -> None:
    """Обычный review «нет итога к 3ч30» не липкий: пара опросов после него публикует итог."""
    mid = await _sochi_row(db_session)
    world = World()
    world.hcd, world.ticker = _hcd_third_period(), _ticker(completed=False)
    fetch = world.install(monkeypatch)
    assert [k for _, k in await _poll(db_session, fetch, 215)] == [KIND_REVIEW]
    world.ticker = _ticker(completed=True)
    assert [k for _, k in await _poll(db_session, fetch, 220)] == [KIND_WAIT]
    assert [k for _, k in await _poll(db_session, fetch, 231)] == [KIND_FINAL]
    assert (await get_match(db_session, mid)).status == "final"


@pytest.mark.asyncio
async def test_a_poll_without_proof_resets_the_pair(db_session, monkeypatch) -> None:
    """Пары идут подряд: между двумя согласными опросами «не завершён» обнуляет первый."""
    mid = await _sochi_row(db_session)
    world = World()
    world.hcd = _hcd_third_period()
    world.ticker = _ticker(completed=True)
    fetch = world.install(monkeypatch)
    assert [k for _, k in await _poll(db_session, fetch, 140)] == [KIND_WAIT]
    world.ticker = _ticker(completed=False)
    assert [k for _, k in await _poll(db_session, fetch, 144)] == [KIND_WAIT]
    world.ticker = _ticker(completed=True)
    assert [k for _, k in await _poll(db_session, fetch, 152)] == [KIND_WAIT]  # с первого опроса 12 минут, но пара порвана
    assert (await get_match(db_session, mid)).status == "scheduled"
    assert [k for _, k in await _poll(db_session, fetch, 162)] == [KIND_FINAL]


@pytest.mark.asyncio
async def test_manual_result_is_stronger_than_the_pending_check(db_session, monkeypatch) -> None:
    mid = await _sochi_row(db_session)
    world = World()
    world.hcd, world.ticker = _hcd_third_period(), _ticker(completed=True)
    fetch = world.install(monkeypatch)
    assert [k for _, k in await _poll(db_session, fetch, 140)] == [KIND_WAIT]
    row = await set_manual_result(
        db_session, mid, home_score=2, away_score=1, decided_in="regulation", now=_at(141)
    )
    assert (row.status, row.result_source, row.home_score) == ("final", "manual", 2)
    assert await _poll(db_session, fetch, 152) == []


# --- пороги ---


def test_check_threshold_is_two_hours_fifteen() -> None:
    assert RESULT_CHECK_AFTER == timedelta(hours=2, minutes=15)
    assert REVIEW_AFTER >= RESULT_CHECK_AFTER + timedelta(minutes=45) + DINAMO_STABLE_AFTER  # овертайм+буллиты+пара
    page, ticker = _hcd_third_period(), _ticker(completed=True)
    just_before = START + RESULT_CHECK_AFTER - timedelta(seconds=1)
    assert decide_result(page, ticker, starts_at=START, now=just_before).kind == KIND_WAIT
    assert decide_result(page, ticker, starts_at=START, now=START + RESULT_CHECK_AFTER).kind == KIND_FINAL


@pytest.mark.asyncio
async def test_result_is_not_polled_before_the_threshold(db_session, monkeypatch) -> None:
    """До порога страницу итога hcdinamo.by не читаем и решения не принимаем.

    Живой счёт (неофициальный, очков не даёт) по-прежнему обновляется из тикера/страницы sportmail.ru — это
    отдельный путь (``set_live_score``), на итог он не влияет."""
    mid = await _sochi_row(db_session)
    world = World()
    world.hcd, world.ticker = _hcd_third_period(), _ticker(completed=True)
    seen: list[str] = []
    real = world.install(monkeypatch)

    async def fetch(url: str) -> str:
        seen.append(url)
        return await real(url)

    just_before = START + RESULT_CHECK_AFTER - timedelta(seconds=1)
    assert await check_due_results(db_session, fetch, now=just_before, alert=_silent) == []
    assert not any(u.startswith("https://hcdinamo.by/matches/") for u in seen)
    assert (await db_session.execute(text("SELECT result_probe FROM hockey_matches WHERE id = :i"), {"i": mid})).scalar_one() is None
    assert [k for _, k in await check_due_results(db_session, fetch, now=START + RESULT_CHECK_AFTER, alert=_silent)] == [
        KIND_WAIT
    ]
    assert any(u.startswith("https://hcdinamo.by/matches/") for u in seen)


# --- лог пути решения ---


@pytest.mark.asyncio
async def test_decision_path_is_logged_with_every_source(db_session, monkeypatch, caplog) -> None:
    mid = await _sochi_row(db_session)
    world = World()
    world.hcd, world.ticker = _hcd_third_period(), _ticker(completed=False)
    fetch = world.install(monkeypatch)
    with caplog.at_level(logging.INFO, logger=hm.logger.name):
        await _poll(db_session, fetch, 140)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("hockey result:")]
    assert len(lines) == 1
    line = lines[0]
    assert f"match={mid}" in line and "kind=wait" in line
    assert "hcdinamo=3:2 looks_final=True" in line and "hockey.by=3:2 completed=False" in line
    assert "sportmail.table=(3, 2, 'regulation')" in line and "(3, 2, False, True)" in line
