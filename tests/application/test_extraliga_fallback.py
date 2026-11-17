"""TASK-364: запасной источник Экстралиги — flashscore.com, когда hockey.by не отвечает."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from src.application import extraliga as xl
from src.application.extraliga import (
    CLUBS,
    Breaker,
    hockeyby_down,
    match_page_url,
    run_tick,
    sync_details,
    sync_fallback,
    upsert_calendar_match,
)
from src.application.hockey_matches import LoopHealth
from src.ingestion.flashscore_sources import (
    CLUB_IDS,
    FLASHSCORE_EXTRALIGA_URL,
    parse_flashscore_league,
)
from src.ingestion.hockey_sources import MINSK_TZ
from src.ingestion.hockeyby_sources import STATUS_SCHEDULED, CalendarMatch

FIXTURES = Path(__file__).resolve().parents[2] / "data/fixtures/hockey"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=MINSK_TZ)


def _fx(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _minsk(*args: int) -> datetime:
    return datetime(*args, tzinfo=MINSK_TZ)


def _flashscore(page: str | None = None):
    asked: list[str] = []

    async def fetch(url: str) -> str:
        asked.append(url)
        assert url == FLASHSCORE_EXTRALIGA_URL
        return page if page is not None else _fx("flashscore-extraliga.html")

    fetch.asked = asked  # type: ignore[attr-defined]
    return fetch


def _cal(match_id: str, starts_at: datetime, home_id: str, away_id: str) -> CalendarMatch:
    return CalendarMatch(
        match_id=match_id,
        starts_at=starts_at,
        home=CLUBS[home_id].name,
        away=CLUBS[away_id].name,
        home_club_id=home_id,
        away_club_id=away_id,
        arena="Арена",
        city=None,
        status=STATUS_SCHEDULED,
    )


async def _row(db_session, where: str, **params):
    return (
        await db_session.execute(
            text(
                "SELECT id, source, league, source_match_id, status, home_team, away_team, home_club_id, away_club_id,"
                " starts_at, arena, city, home_score, away_score, decided_in, live_home_score, live_away_score"
                f" FROM hockey_matches WHERE {where}"
            ),
            params,
        )
    ).one()


async def _ids(db_session) -> list[str]:
    return list(
        (
            await db_session.execute(
                text("SELECT source_match_id FROM hockey_matches WHERE source = 'hockeyby' ORDER BY starts_at, id")
            )
        ).scalars()
    )


def _live(page: str, match_id: str, home: int, away: int) -> str:
    """Идущий матч flashscore вживую не видели: делаем его из ближайшего, меняя стадию на 2 и дописывая счёт."""
    head = f"AA÷{match_id}¬"
    start = page.index(head)
    end = page.index("~", start)
    record = page[start:end].replace("¬AB÷1¬CR÷1¬AC÷1¬", "¬AB÷2¬CR÷2¬AC÷12¬") + f"¬AG÷{home}¬AH÷{away}"
    return page[:start] + record + page[end:]


# ── разбор ────────────────────────────────────────────────────────────


def test_feed_gives_results_with_how_they_were_decided_and_fixtures() -> None:
    rows = {m.source_match_id: m for m in parse_flashscore_league(_fx("flashscore-extraliga.html"))}
    assert len(rows) == 7
    reg = rows["K2wO09kU"]
    assert (reg.home, reg.away, reg.home_club_id, reg.away_club_id) == ("Baranavichy", "Brest", "21", "11")
    assert (reg.status, reg.home_score, reg.away_score, reg.decided_in) == ("final", 6, 3, "regulation")
    assert reg.starts_at == _minsk(2026, 11, 9, 19, 0)
    ot = rows["6ugo4NvP"]
    assert (ot.home_club_id, ot.away_club_id, ot.home_score, ot.away_score, ot.decided_in) == ("14", "12", 2, 3, "ot")
    so = rows["6cO06DLh"]  # 1:1 и победа по буллитам: шайба победителю уже добавлена, как на hockey.by
    assert (so.home_score, so.away_score, so.decided_in) == (2, 1, "so")
    soon = rows["lxKmHUZA"]
    assert (soon.status, soon.home_score, soon.decided_in) == ("scheduled", None, None)
    assert soon.starts_at == _minsk(2026, 11, 10, 19, 0)


def test_every_flashscore_club_is_one_of_ours() -> None:
    assert set(CLUB_IDS.values()) == set(CLUBS)  # все 14 клубов, без лишних


def test_unknown_club_has_no_id_and_unknown_ending_has_no_decided_in() -> None:
    page = _fx("flashscore-extraliga.html").replace("AE÷Gomel¬", "AE÷Dinamo Minsk¬", 1).replace("AC÷10¬", "AC÷99¬")
    rows = {m.source_match_id: m for m in parse_flashscore_league(page)}
    assert any(m.home == "Dinamo Minsk" and m.home_club_id is None for m in rows.values())
    assert rows["6ugo4NvP"].status == "final" and rows["6ugo4NvP"].decided_in is None


def test_live_match_has_a_score_and_no_ending() -> None:
    page = _live(_fx("flashscore-extraliga.html"), "lxKmHUZA", 1, 0)
    m = {m.source_match_id: m for m in parse_flashscore_league(page)}["lxKmHUZA"]
    assert (m.status, m.home_score, m.away_score, m.decided_in) == ("live", 1, 0, None)


def test_changed_format_is_a_loud_failure() -> None:
    with pytest.raises(ValueError, match="сменилась вёрстка"):
        parse_flashscore_league("<html>другая страница</html>")
    broken = _fx("flashscore-extraliga.html").replace("¬AD÷1794240000¬", "¬", 1)
    with pytest.raises(ValueError, match="нет полей AD"):
        parse_flashscore_league(broken)
    with pytest.raises(ValueError, match="не число"):
        parse_flashscore_league(_fx("flashscore-extraliga.html").replace("AG÷6¬", "AG÷шесть¬", 1))


# ── календарь ─────────────────────────────────────────────────────────


async def test_fallback_inserts_upcoming_within_horizon_and_is_idempotent(db_session) -> None:
    # Арена хозяев берётся из их прошлого домашнего матча на hockey.by.
    await upsert_calendar_match(db_session, _cal("440001", _minsk(2026, 10, 1, 19, 0), "1", "15"), now=NOW)
    first = await sync_fallback(db_session, _flashscore(), now=NOW)
    # 10.11 ×2 и 20.11; 17.12 — за горизонтом (35 дней), сыгранные не заводим.
    assert (first["inserted"], first["moved"], first["skipped"]) == (3, 0, 0)
    again = await sync_fallback(db_session, _flashscore(), now=NOW)
    assert (again["inserted"], again["unchanged"]) == (0, 3)
    gomel = await _row(db_session, "source_match_id = 'fslxKmHUZA'")
    assert (gomel.source, gomel.league, gomel.home_team, gomel.away_team) == (
        "hockeyby",
        "extraliga",
        "Гомель",
        "Витебск",
    )
    assert (gomel.home_club_id, gomel.away_club_id, gomel.city, gomel.arena) == ("1", "22", "Гомель", "Арена")
    assert gomel.starts_at == _minsk(2026, 11, 10, 19, 0) and gomel.status == "scheduled"
    molodechno = await _row(db_session, "source_match_id = 'fszFDXKCzn'")
    assert (molodechno.home_team, molodechno.away_team, molodechno.arena) == ("Динамо-Молодечно", "Юность", None)


async def test_fallback_trusts_the_primary_time_on_the_same_day(db_session) -> None:
    await upsert_calendar_match(db_session, _cal("442100", _minsk(2026, 11, 10, 18, 30), "1", "22"), now=NOW)
    counts = await sync_fallback(db_session, _flashscore(), now=NOW)
    assert counts["inserted"] == 2 and counts["unchanged"] == 1
    row = await _row(db_session, "source_match_id = '442100'")
    assert row.starts_at == _minsk(2026, 11, 10, 18, 30)


async def test_fallback_moves_a_rescheduled_match_instead_of_duplicating(db_session) -> None:
    # У нас Брест — Шахтер стоял на 18.11, flashscore ставит на 20.11: это один матч.
    await upsert_calendar_match(db_session, _cal("442200", _minsk(2026, 11, 18, 19, 0), "11", "12"), now=NOW)
    counts = await sync_fallback(db_session, _flashscore(), now=NOW)
    assert (counts["moved"], counts["inserted"]) == (1, 2)
    row = await _row(db_session, "source_match_id = '442200'")
    assert row.starts_at == _minsk(2026, 11, 20, 19, 0)
    assert "fsW20LzGW0" not in await _ids(db_session)


async def test_fallback_move_tells_the_game(db_session, monkeypatch) -> None:
    await upsert_calendar_match(db_session, _cal("442200", _minsk(2026, 11, 18, 19, 0), "11", "12"), now=NOW)
    seen: list[int] = []

    async def fake_moved(session, *, match_id, starts_at):
        seen.append(match_id)
        return {"voided": [], "released": []}

    monkeypatch.setattr("src.application.hockey_game.on_match_moved", fake_moved)
    await sync_fallback(db_session, _flashscore(), now=NOW)
    row = await _row(db_session, "source_match_id = '442200'")
    assert seen == [row.id]


async def test_fallback_skips_a_club_we_do_not_know(db_session) -> None:
    page = _fx("flashscore-extraliga.html").replace("AF÷Vitebsk¬", "AF÷Dinamo Minsk¬")
    counts = await sync_fallback(db_session, _flashscore(page), now=NOW)
    assert counts["inserted"] == 2 and counts["skipped"] >= 1
    assert "fslxKmHUZA" not in await _ids(db_session)


async def test_fallback_never_touches_dinamo_rows(db_session) -> None:
    """«Кто кого» Динамо (``kk_matches`` = source 'hcdinamo') от запасного Экстралиги не зависит."""
    count = "SELECT count(*) FROM hockey_matches WHERE source = 'hcdinamo'"
    before = (await db_session.execute(text(count))).scalar_one()
    kk_before = (await db_session.execute(text("SELECT count(*) FROM kk_matches"))).scalar_one()
    page = _live(_fx("flashscore-extraliga.html"), "lxKmHUZA", 1, 0)
    await sync_fallback(db_session, _flashscore(page), now=_minsk(2026, 11, 9, 22, 0))
    await sync_fallback(db_session, _flashscore(), now=NOW)
    assert (await db_session.execute(text(count))).scalar_one() == before
    assert (await db_session.execute(text("SELECT count(*) FROM kk_matches"))).scalar_one() == kk_before
    wrong = "SELECT count(*) FROM hockey_matches WHERE source_match_id LIKE 'fs%' AND (source <> 'hockeyby' OR league <> 'extraliga')"
    assert (await db_session.execute(text(wrong))).scalar_one() == 0


async def test_empty_feed_in_season_is_an_error(db_session) -> None:
    # Ленты на месте, матчей в них нет: в ноябре это поломка, а не межсезонье.
    empty = "<script>cjs.initialFeeds['results'] = {\n data: `SA÷4¬~ZA÷BELARUS: Extraleague¬~`,\n};</script>"
    with pytest.raises(xl.CalendarEmpty):
        await sync_fallback(db_session, _flashscore(empty), now=NOW)


# ── усыновление ───────────────────────────────────────────────────────


async def test_primary_returning_adopts_the_fallback_row(db_session) -> None:
    await sync_fallback(db_session, _flashscore(), now=NOW)
    fallback = await _row(db_session, "source_match_id = 'fslxKmHUZA'")
    # hockey.by вернулся: тот же матч в 19:05 — строка та же, id hockey.by, время основного.
    outcome = await upsert_calendar_match(db_session, _cal("442300", _minsk(2026, 11, 10, 19, 5), "1", "22"), now=NOW)
    assert outcome == "moved"
    row = await _row(db_session, "source_match_id = '442300'")
    assert row.id == fallback.id and row.starts_at == _minsk(2026, 11, 10, 19, 5)
    assert "fslxKmHUZA" not in await _ids(db_session)
    # Другой день — не тот матч: не усыновляем.
    await upsert_calendar_match(db_session, _cal("442301", _minsk(2026, 11, 21, 19, 0), "11", "12"), now=NOW)
    assert "fsW20LzGW0" in await _ids(db_session)


async def test_details_never_ask_hockey_by_about_fallback_rows(db_session) -> None:
    await sync_fallback(db_session, _flashscore(), now=NOW)

    class Nothing:
        asked: list[str] = []

        async def calendar_page(self, page: int) -> str:
            raise AssertionError

        async def get(self, url: str) -> str:
            self.asked.append(url)
            raise AssertionError(url)

    source = Nothing()
    counts = await sync_details(db_session, source, now=NOW)
    assert source.asked == [] and counts["checked"] == 0


# ── итоги ─────────────────────────────────────────────────────────────


async def _with_pick(db_session, match_id: int, starts_at: datetime) -> None:
    from src.application.hockey_game import make_pick

    await make_pick(
        db_session,
        player_key=881_363_001,
        display_name="Саша",
        match_id=match_id,
        side="home",
        now=starts_at - timedelta(hours=2),
    )


async def _played_row(db_session, *, pick: bool = True) -> int:
    starts = _minsk(2026, 11, 9, 19, 0)
    await upsert_calendar_match(db_session, _cal("442400", starts, "21", "11"), now=starts - timedelta(days=1))
    row = await _row(db_session, "source_match_id = '442400'")
    if pick:
        await _with_pick(db_session, row.id, starts)
    return row.id


async def test_result_needs_two_equal_polls_5_minutes_apart(db_session) -> None:
    mid = await _played_row(db_session)
    now = _minsk(2026, 11, 9, 22, 0)
    first = await sync_fallback(db_session, _flashscore(), now=now)
    assert first["pending"] == 1 and (await _row(db_session, "id = :i", i=mid)).status == "scheduled"
    await sync_fallback(db_session, _flashscore(), now=now + timedelta(minutes=3))
    assert (await _row(db_session, "id = :i", i=mid)).status == "scheduled"  # 3 минуты — рано
    done = await sync_fallback(db_session, _flashscore(), now=now + timedelta(minutes=10))
    assert done["final"] == 1
    row = await _row(db_session, "id = :i", i=mid)
    assert (row.status, row.home_score, row.away_score, row.decided_in) == ("final", 6, 3, "regulation")


async def test_overtime_and_shootout_results(db_session) -> None:
    starts = _minsk(2026, 11, 8, 13, 0)
    await upsert_calendar_match(db_session, _cal("442500", starts, "14", "12"), now=starts - timedelta(days=1))
    await upsert_calendar_match(db_session, _cal("442501", starts, "1", "22"), now=starts - timedelta(days=1))
    counts = await sync_fallback(db_session, _flashscore(), now=_minsk(2026, 11, 8, 18, 0))
    assert counts["final"] == 2  # ходов нет — итог сразу, как у основного
    ot = await _row(db_session, "source_match_id = '442500'")
    so = await _row(db_session, "source_match_id = '442501'")
    assert (ot.home_score, ot.away_score, ot.decided_in) == (2, 3, "ot")
    assert (so.home_score, so.away_score, so.decided_in) == (2, 1, "so")


async def test_score_changing_between_polls_goes_to_review(db_session) -> None:
    mid = await _played_row(db_session)
    now = _minsk(2026, 11, 9, 22, 0)
    await sync_fallback(db_session, _flashscore(), now=now)
    changed = _fx("flashscore-extraliga.html").replace("AG÷6¬", "AG÷5¬", 1)
    await sync_fallback(db_session, _flashscore(changed), now=now + timedelta(minutes=20))
    assert (await _row(db_session, "id = :i", i=mid)).status == "review"


async def test_result_without_ending_goes_to_review(db_session) -> None:
    mid = await _played_row(db_session)
    page = _fx("flashscore-extraliga.html").replace("¬AB÷3¬CR÷3¬AC÷3¬", "¬AB÷3¬CR÷3¬AC÷77¬", 1)
    await sync_fallback(db_session, _flashscore(page), now=_minsk(2026, 11, 9, 22, 0))
    assert (await _row(db_session, "id = :i", i=mid)).status == "review"


async def test_official_primary_result_is_never_overwritten(db_session) -> None:
    mid = await _played_row(db_session, pick=False)
    await db_session.execute(
        text(
            "UPDATE hockey_matches SET status = 'final', home_score = 5, away_score = 3, decided_in = 'regulation',"
            " result_source = 'auto' WHERE id = :i"
        ),
        {"i": mid},
    )
    counts = await sync_fallback(db_session, _flashscore(), now=_minsk(2026, 11, 9, 22, 0))
    assert counts["disagree"] == 1
    row = await _row(db_session, "id = :i", i=mid)
    assert (row.home_score, row.away_score) == (5, 3)


async def test_live_score_from_flashscore(db_session) -> None:
    await upsert_calendar_match(db_session, _cal("442600", _minsk(2026, 11, 10, 19, 0), "1", "22"), now=NOW)
    page = _live(_fx("flashscore-extraliga.html"), "lxKmHUZA", 2, 1)
    counts = await sync_fallback(db_session, _flashscore(page), now=_minsk(2026, 11, 10, 19, 40))
    assert counts["live"] == 1
    row = await _row(db_session, "source_match_id = '442600'")
    assert (row.live_home_score, row.live_away_score, row.status, row.home_score) == (2, 1, "scheduled", None)


# ── автомат и проход ──────────────────────────────────────────────────


class Hanging:
    """hockey.by, который не отвечает: каждый запрос — таймаут. ``hang`` — висит по-настоящему (для пробы)."""

    def __init__(self, *, hang: bool = False) -> None:
        self.hang = hang
        self.asked: list[str] = []

    async def calendar_page(self, page: int) -> str:
        return await self.get(f"calendar:{page}")

    async def get(self, url: str) -> str:
        self.asked.append(url)
        if self.hang:
            await asyncio.sleep(3600)
        raise TimeoutError(f"{url}: TLS handshake timeout")


async def _due_details(db_session, n: int) -> None:
    for i in range(n):
        await upsert_calendar_match(
            db_session, _cal(f"4427{i:02d}", _minsk(2026, 11, 11, 19, 0) + timedelta(days=i), "10", "14"), now=NOW
        )


async def test_first_timeout_stops_all_other_requests_of_the_tick(db_session) -> None:
    await _due_details(db_session, 5)
    source = Hanging()
    out = await run_tick(
        db_session, source, now=NOW, calendar_due=True, standings_due=True, fallback=_flashscore(), fallback_due=True
    )
    assert source.asked == ["calendar:1"]  # не 1 + 1 + 5 запросов по 25 секунд
    assert out["calendar_failed"] and out["standings_failed"]
    assert "hockey.by не отвечает" in str(out["primary_down"])
    assert out["fallback"]["inserted"] == 3
    assert await hockeyby_down(db_session, now=NOW)


async def test_probe_after_a_down_tick_is_short_and_spares_the_rest(db_session, monkeypatch) -> None:
    """Прошлый тик hockey.by лежал: проба висит (TLS) — ждём только её короткий таймаут, страницы не трогаем."""
    await _due_details(db_session, 5)
    source = Hanging(hang=True)
    monkeypatch.setattr(xl, "PROBE_TIMEOUT_SEC", 0.05)
    assert await Breaker(source).probe(0.05) is False
    started = time.monotonic()
    out = await run_tick(
        db_session,
        source,
        now=NOW,
        calendar_due=True,
        standings_due=False,
        probe_first=True,
        fallback=_flashscore(),
        fallback_due=True,
    )
    assert time.monotonic() - started < 1.0
    assert source.asked == [xl.PROBE_URL, xl.PROBE_URL]  # только пробы, ни одной страницы
    assert out["primary_down"] and out["fallback"]["inserted"] == 3


async def test_working_primary_does_not_ask_flashscore(db_session) -> None:
    from tests.application.test_extraliga import _season

    source = _season()

    async def any_match_page(url: str) -> str:
        source.asked.append(url)
        return _fx("hockeyby-gamecenter-441978-future.html")

    source.get = any_match_page  # type: ignore[method-assign]
    fetch = _flashscore()
    out = await run_tick(
        db_session, source, now=NOW, calendar_due=True, standings_due=False, fallback=fetch, fallback_due=True
    )
    assert out["primary_down"] is None and out["fallback"] is None and fetch.asked == []
    assert not await hockeyby_down(db_session, now=NOW)


async def test_fallback_off_or_not_due_means_no_request(db_session) -> None:
    fetch = _flashscore()
    out = await run_tick(
        db_session, Hanging(), now=NOW, calendar_due=True, standings_due=False, fallback=fetch, fallback_due=False
    )
    assert out["primary_down"] and out["fallback"] is None and fetch.asked == []
    out = await run_tick(
        db_session, Hanging(), now=NOW, calendar_due=True, standings_due=False, fallback=None, fallback_due=True
    )
    assert out["fallback"] is None


async def test_parse_errors_are_not_mistaken_for_a_dead_site(db_session) -> None:
    class Broken(Hanging):
        async def get(self, url: str) -> str:
            self.asked.append(url)
            return "<html>не та страница</html>"

    await _due_details(db_session, 3)
    source = Broken()
    out = await run_tick(db_session, source, now=NOW, calendar_due=False, standings_due=False)
    assert len(source.asked) == 3  # каждая страница спрошена: сайт жив, разметка другая
    assert out["primary_down"] == "страницы матчей hockey.by не читаются"
    assert not await hockeyby_down(db_session, now=NOW)


async def test_source_down_mark_goes_stale_after_a_day(db_session) -> None:
    await xl.mark_source(db_session, down=True, now=NOW)
    assert await hockeyby_down(db_session, now=NOW + timedelta(hours=1))
    assert not await hockeyby_down(db_session, now=NOW + timedelta(hours=25))
    await xl.mark_source(db_session, down=False, now=NOW + timedelta(hours=2))
    assert not await hockeyby_down(db_session, now=NOW + timedelta(hours=3))


async def test_loop_pass_alerts_honestly_while_the_fallback_works(db_session, monkeypatch) -> None:
    from src.bot import notification_loops as loops

    class Client(Hanging):
        requests = 0

        def __init__(self, *a, **kw) -> None:
            super().__init__()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> None:
            return None

    monkeypatch.setattr(xl, "HockeyByClient", Client)
    sent: list[str] = []

    async def alert(body: str) -> bool:
        sent.append(body)
        return True

    pace, health, fetch = loops.ExtraligaPace(), LoopHealth(), _flashscore()
    outs = []
    for _ in range(3):
        outs.append(await loops._extraliga_pass(pace, health, alert=alert, fallback=fetch))  # noqa: SLF001
    assert pace.primary_down and pace.fallback_ok
    assert all("календарь Экстралиги" not in t and "таблица Экстралиги" not in t for t in sent)
    assert outs[-1]["covered_via"] == "flashscore.com"
    notices = [health.take_fallback_notice(extraliga="flashscore.com", dinamo="sportmail.ru") for _ in range(3)]
    assert notices[:2] == [None, None]
    assert notices[2] == (
        "Кто кого: hockey.by и календарь Динамо не отвечают. "
        "Сейчас на запасных — flashscore.com и sportmail.ru, с ними всё в порядке."
    )
    assert "не обновляются" not in (notices[2] or "") and "/hockey" not in (notices[2] or "")
    # Запасной спрошен один раз: тики шли подряд, а не через 10 минут.
    assert len(fetch.asked) == 1 and pace.fallback_at is not None


def test_dinamo_alert_text_is_unchanged_without_a_note() -> None:
    health = LoopHealth()
    texts = [health.failed("календарь Экстралиги", "таймаут") for _ in range(3)]
    assert "не обновляются" in (texts[2] or "")


def test_fallback_rows_have_no_hockey_by_protocol_link() -> None:
    from types import SimpleNamespace

    from src.application.site_matches import protocol_url

    assert protocol_url(SimpleNamespace(source_match_id="fsW20LzGW0", league="extraliga")) is None
    assert protocol_url(SimpleNamespace(source_match_id="442032", league="extraliga")) == match_page_url("442032")


async def test_mini_app_after_card_knows_the_protocol_is_unavailable(db_session) -> None:
    from src.application.hockey_event import _extraliga_extra

    await sync_fallback(db_session, _flashscore(), now=NOW)
    await db_session.execute(
        text(
            "UPDATE hockey_matches SET status = 'final', home_score = 3, away_score = 1, decided_in = 'regulation',"
            " result_source = 'auto' WHERE source_match_id = 'fslxKmHUZA'"
        )
    )
    row = (await db_session.execute(text("SELECT * FROM hockey_matches WHERE source_match_id = 'fslxKmHUZA'"))).one()
    after = _minsk(2026, 11, 10, 22, 0)
    await xl.mark_source(db_session, down=True, now=after)
    extra = await _extraliga_extra(db_session, row, player_key=1, final=True, now=after)  # noqa: SLF001
    assert extra["details_unavailable"] is True and extra["details"] is None
    assert extra["source_url"] is None  # у fs-строки страницы на hockey.by нет
    await xl.mark_source(db_session, down=False, now=after + timedelta(minutes=10))
    extra = await _extraliga_extra(db_session, row, player_key=1, final=True, now=after + timedelta(minutes=10))  # noqa: SLF001
    assert extra["details_unavailable"] is False
