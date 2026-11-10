"""Матчи Экстралиги с hockey.by: календарь, страница матча, таблица (TASK-340, PDEC-029).

Матчи лежат в ``hockey_matches`` (source='hockeyby', league='extraliga') рядом с матчами Динамо.
Игра «Кто кого» читает их через ``game_matches`` (Динамо — ещё и ``kk_matches``). Итог ставит страница
матча, когда на ней «Официальные данные»; если её не дождались — счёт из календаря через 6 часов после
начала. Второго источника у Экстралиги нет, поэтому итог публикуется только после двух одинаковых
опросов подряд с разницей не меньше 15 минут (``confirm_result``); иначе матч уходит на ручную проверку.

Календарь хранится целиком, а показ — партиями клубов: ``extraliga_clubs`` в настройках (решение
владельца 2026-10-28 — включать клубы постепенно).

Нагрузка на hockey.by: календарь раз в сутки (страница + ~31 запрос ajax), страницы матчей на
неделю вперёд раз в сутки и каждые 15 минут в день матча, таблица раз в сутки. Между запросами пауза.

Запасной источник — flashscore.com (TASK-364): hockey.by не ответил — до конца прохода его больше не
спрашиваем (``Breaker``), а календарь, итоги и живой счёт берём одним запросом к flashscore. Строки,
заведённые запасным, имеют ``source_match_id`` вида ``fs<id>`` и «усыновляются» hockey.by, как только он
вернётся. Итог — тем же ``confirm_result``. Страниц матчей и таблицы у запасного нет.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.flashscore_sources import (
    FLASHSCORE_EXTRALIGA_URL,
    STATUS_FINAL as FS_FINAL,
    STATUS_LIVE as FS_LIVE,
    STATUS_SCHEDULED as FS_SCHEDULED,
    FlashscoreMatch,
    parse_flashscore_league,
)
from src.ingestion.hockey_sources import MINSK_TZ
from src.ingestion.hockeyby_sources import (
    CALENDAR_AJAX_URL,
    CALENDAR_PAGE_URL,
    HOCKEY_BY_BASE,
    STATUS_PLAYED,
    CalendarMatch,
    CalendarPage,
    GameCenter,
    TeamSide,
    calendar_form,
    extract_sessid,
    parse_calendar_response,
    parse_gamecenter,
    parse_standings,
)

logger = logging.getLogger(__name__)

SOURCE_HOCKEYBY = "hockeyby"
LEAGUE_EXTRALIGA = "extraliga"

# Сезон — 31 страница по 12 матчей; потолок — на случай, если «Матчей не найдено» исчезнет.
MAX_CALENDAR_PAGES = 45
REQUEST_PAUSE_SEC = 2.0
DETAILS_AHEAD = timedelta(days=7)
DETAILS_EVERY = timedelta(hours=24)
# День матча: за 12 часов до начала и 5 часов после — страница матча каждые 15 минут.
MATCH_DAY_BEFORE = timedelta(hours=12)
MATCH_DAY_AFTER = timedelta(hours=5)
MATCH_DAY_EVERY = timedelta(minutes=15)
# Страница матча так и не сказала «официально» — берём счёт из календаря.
CALENDAR_RESULT_AFTER = timedelta(hours=6)
# Итог без второго источника: один и тот же счёт и способ в двух опросах не ближе друг к другу, чем это.
RESULT_STABLE_AFTER = timedelta(minutes=15)
_DECIDED = ("regulation", "ot", "so")
# Сыгранный матч без официального протокола — страницу дочитываем раз в час, до трёх дней.
POST_MATCH_WINDOW = timedelta(days=3)
POST_MATCH_EVERY = timedelta(hours=1)
# Старые сыгранные без протокола (закрыты календарём до появления цикла) — дочитываем понемногу,
# свежие сначала: «прошлая встреча» и серии голов нужны на странице матча.
BACKFILL_PER_TICK = 10

USER_AGENT = "Mozilla/5.0 (compatible; GlideBot/1.0; +https://glideclub.by)"

# Запасной источник (flashscore.com): строка календаря ``fs<id>``; запрос не чаще раза в 10 минут.
FALLBACK_PREFIX = "fs"
FALLBACK_EVERY = timedelta(minutes=10)
# В игру и на сайт новые матчи заводим не дальше этого: flashscore отдаёт ~8 недель вперёд.
FALLBACK_HORIZON = timedelta(days=35)
# Итоги запасной ставит только недавним матчам — как и страница матча (POST_MATCH_WINDOW).
FALLBACK_RESULTS_BACK = POST_MATCH_WINDOW
# Прошлый проход не достучался до hockey.by: сначала дешёвый пробный запрос с коротким таймаутом,
# чтобы лежащий сайт не съедал по 25 секунд каждый тик (и не задерживал цикл Динамо).
PROBE_URL = f"{HOCKEY_BY_BASE}/robots.txt"
PROBE_TIMEOUT_SEC = 3.0
# Отметка «hockey.by не отвечает» старше суток не в счёт: цикл мог просто стоять.
SOURCE_DOWN_FRESH = timedelta(hours=24)


@dataclass(frozen=True)
class Club:
    name: str  # имя в hockey_matches и TEAMS
    city: str  # город клуба, как в каталоге (без ё)
    team_id: str  # id команды сезона 2026/27 — в турнирной таблице


# Ключ — club id hockey.by (стабилен между сезонами, есть и в календаре, и на странице матча).
CLUBS: dict[str, Club] = {
    "10": Club("Юность", "Минск", "5676"),
    "14": Club("Неман", "Гродно", "5671"),
    "11": Club("Брест", "Брест", "5672"),
    "12": Club("Шахтер", "Солигорск", "5674"),
    "13": Club("Динамо-Молодечно", "Молодечно", "5678"),
    "20": Club("Лида", "Лида", "5679"),
    "21": Club("Авиатор", "Барановичи", "5680"),
    "16": Club("Металлург Жлобин", "Жлобин", "5681"),
    "22": Club("Витебск", "Витебск", "5682"),
    "225": Club("Славутич", "Смоленск", "5683"),
    "1": Club("Гомель", "Гомель", "5685"),
    "15": Club("Химик", "Новополоцк", "5686"),
    "19": Club("Локомотив Орша", "Орша", "5687"),
    "23": Club("Могилев", "Могилев", "5688"),
}
_BY_TEAM_ID = {club.team_id: club for club in CLUBS.values()}


def club_name(club_id: str, fallback: str) -> str:
    """Имя клуба для базы; новый клуб без записи в CLUBS — как на сайте (и алерт в логах)."""
    club = CLUBS.get(club_id)
    if club is None:
        logger.warning("extraliga: unknown hockey.by club %s (%s)", club_id, fallback)
        return fallback
    return club.name


def enabled_clubs(raw: str | None) -> frozenset[str]:
    """``extraliga_clubs``: имена клубов через запятую. Пусто — Экстралига не показывается."""
    names = {part.strip() for part in (raw or "").split(",") if part.strip()}
    known = {club.name for club in CLUBS.values()}
    unknown = names - known
    if unknown:
        logger.warning("extraliga_clubs: unknown clubs %s", sorted(unknown))
    return frozenset(names & known)


def match_page_url(source_match_id: str) -> str:
    return f"{HOCKEY_BY_BASE}/gamecenter/{source_match_id}/"


STANDINGS_URL = f"{HOCKEY_BY_BASE}/statistic/tables/?division=628"


# ── Сеть ─────────────────────────────────────────────────────────────


class HockeyByClient:
    """Сессия hockey.by: cookie и CSRF-токен календаря живут всю синхронизацию, запросы — с паузой."""

    def __init__(self, *, pause_sec: float = REQUEST_PAUSE_SEC, timeout_s: float = 25) -> None:
        self.pause_sec = pause_sec
        self.timeout_s = timeout_s
        self._session = None
        self._sessid: str | None = None
        self._last: float | None = None
        self.requests = 0

    async def __aenter__(self) -> "HockeyByClient":
        from src.ingestion.source_io import client_session

        self._session = client_session(self.timeout_s)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._session is not None:
            await self._session.close()

    async def _wait(self) -> None:
        loop = asyncio.get_running_loop()
        if self._last is not None:
            delay = self.pause_sec - (loop.time() - self._last)
            if delay > 0:
                await asyncio.sleep(delay)
        self._last = loop.time()
        self.requests += 1

    async def get(self, url: str) -> str:
        from src.ingestion.source_io import current_egress_proxy

        await self._wait()
        assert self._session is not None
        async with self._session.get(url, headers={"User-Agent": USER_AGENT}, proxy=current_egress_proxy()) as resp:
            resp.raise_for_status()
            return await resp.text()

    async def calendar_page(self, page: int) -> str:
        from src.ingestion.source_io import current_egress_proxy

        if self._sessid is None:
            self._sessid = extract_sessid(await self.get(CALENDAR_PAGE_URL))
            if self._sessid is None:
                raise RuntimeError("на странице календаря hockey.by нет bitrix_sessid — сменилась вёрстка")
        await self._wait()
        assert self._session is not None
        headers = {
            "User-Agent": USER_AGENT,
            "X-Bitrix-Csrf-Token": self._sessid,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": CALENDAR_PAGE_URL,
        }
        async with self._session.post(
            CALENDAR_AJAX_URL,
            data=calendar_form(self._sessid, page=page),
            headers=headers,
            proxy=current_egress_proxy(),
        ) as resp:
            resp.raise_for_status()
            return await resp.text()


class Source(Protocol):
    """То, что нужно синхронизации от сети. В тестах — фикстуры."""

    async def calendar_page(self, page: int) -> str: ...

    async def get(self, url: str) -> str: ...


Fetch = Callable[[str], Awaitable[str]]


class SourceDown(RuntimeError):
    """hockey.by уже не ответил в этом проходе — запрос не делали."""


def is_network_failure(exc: BaseException) -> bool:
    """Сайт недоступен (таймаут, нет соединения, 5xx), а не «страница не разобралась»."""
    import aiohttp

    if isinstance(exc, (TimeoutError, aiohttp.ClientConnectionError)):
        return True
    return isinstance(exc, aiohttp.ClientResponseError) and exc.status >= 500


class Breaker:
    """Автомат на hockey.by: первый сетевой сбой за проход — остальные запросы прохода не делаются.

    Без него лежащий сайт стоил бы по 25 секунд таймаута на каждую страницу матча, а за Экстралигой
    в том же цикле ждёт Динамо. ``down`` — причина; ``answered`` — сколько запросов прошло.
    """

    def __init__(self, source: Source) -> None:
        self._source = source
        self.down: str | None = None
        self.answered = 0

    async def _call(self, request: Callable[[], Awaitable[str]]) -> str:
        if self.down is not None:
            raise SourceDown(self.down)
        try:
            body = await request()
        except Exception as exc:
            if is_network_failure(exc):
                self.down = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                raise SourceDown(self.down) from exc
            raise
        self.answered += 1
        return body

    async def calendar_page(self, page: int) -> str:
        return await self._call(lambda: self._source.calendar_page(page))

    async def get(self, url: str) -> str:
        return await self._call(lambda: self._source.get(url))

    async def probe(self, timeout_sec: float | None = None) -> bool:
        """Пробный запрос: ответил ли hockey.by вообще. Ответ с ошибкой (404) — сайт жив."""
        timeout_sec = PROBE_TIMEOUT_SEC if timeout_sec is None else timeout_sec
        try:
            await asyncio.wait_for(self.get(PROBE_URL), timeout_sec)
        except SourceDown:
            return False
        except TimeoutError:
            self.down = f"нет ответа за {timeout_sec:g} с"
            return False
        except Exception:
            logger.info("extraliga: hockey.by probe answered with an error", exc_info=True)
            self.answered += 1
        return True


# ── База ─────────────────────────────────────────────────────────────

_SELECT = text("""
    SELECT id, status, starts_at, home_team, away_team, arena, city
    FROM hockey_matches WHERE source = 'hockeyby' AND source_match_id = :source_match_id
    """)

_INSERT = text("""
    INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, home_club_id, away_club_id,
                                starts_at, arena, city, status, checked_at)
    VALUES ('hockeyby', 'extraliga', :source_match_id, :home_team, :away_team, :home_club_id, :away_club_id,
            :starts_at, :arena, :city, 'scheduled', :now)
    """)

# Перенос: время, команды и арена меняются только у несыгранного матча.
_MOVE = text("""
    UPDATE hockey_matches
    SET starts_at = :starts_at, home_team = :home_team, away_team = :away_team,
        home_club_id = :home_club_id, away_club_id = :away_club_id,
        arena = COALESCE(:arena, arena), city = COALESCE(:city, city), checked_at = :now, updated_at = :now,
        previous_starts_at = CASE WHEN starts_at <> :starts_at THEN starts_at ELSE previous_starts_at END,
        missed_runs = 0
    WHERE id = :id AND status = 'scheduled'
    """)

_TOUCH = text("UPDATE hockey_matches SET checked_at = :now, missed_runs = 0 WHERE id = :id")

# Матч будущий, несыгранный, а в полном прогоне календаря его не было (TASK-347). Две такие подряд — на сайте он скрыт.
_FUTURE_SCHEDULED = text("""
    SELECT COUNT(*) FROM hockey_matches
    WHERE source = 'hockeyby' AND status = 'scheduled' AND starts_at > :now
    """)
_MARK_MISSED = text("""
    UPDATE hockey_matches SET missed_runs = LEAST(missed_runs + 1, 100)
    WHERE source = 'hockeyby' AND status = 'scheduled' AND starts_at > :now
      AND NOT (source_match_id = ANY(:seen))
    """)
_COUNT_MISSED = text("""
    SELECT COUNT(*) FROM hockey_matches
    WHERE source = 'hockeyby' AND status = 'scheduled' AND starts_at > :now
      AND NOT (source_match_id = ANY(:seen))
    """)
# Пропавших больше этой доли будущих матчей — признак сбоя разбора, а не настоящих удалений.
MISSED_SHARE_LIMIT = 0.10
MISSED_FLOOR = 3

_FINAL = text("""
    UPDATE hockey_matches
    SET status = 'final', home_score = :home_score, away_score = :away_score, decided_in = :decided_in,
        result_source = 'auto', finalized_at = :now, review_reason = NULL, checked_at = :now, updated_at = :now
    WHERE id = :id AND status IN ('scheduled', 'review')
    """)

_DETAILS = text("""
    UPDATE hockey_matches
    SET details = CAST(:details AS jsonb), details_checked_at = :now,
        tickets_url = COALESCE(:tickets_url, tickets_url),
        arena = COALESCE(:arena, arena), city = COALESCE(:city, city), updated_at = :now
    WHERE id = :id
    """)

# Несыгранные — на неделю вперёд; сыгранные — пока страница не сказала «официально» (голы, броски,
# зрители появляются там после игры), но не дольше POST_MATCH_WINDOW.
_DUE_DETAILS = text("""
    SELECT id, source_match_id, starts_at, status, details_checked_at
    FROM hockey_matches
    WHERE source = 'hockeyby' AND source_match_id NOT LIKE 'fs%'
      AND (
        (status IN ('scheduled', 'review') AND starts_at >= :from_ AND starts_at <= :until)
        OR (status = 'final' AND starts_at >= :post_from
            AND COALESCE((details ->> 'official')::boolean, false) = false)
      )
    ORDER BY starts_at
    """)

_DETAILS_FAILED = text("UPDATE hockey_matches SET details_checked_at = :now WHERE id = :id")

_BACKFILL = text("""
    SELECT id, source_match_id, starts_at, status, details_checked_at
    FROM hockey_matches
    WHERE source = 'hockeyby' AND source_match_id NOT LIKE 'fs%'
      AND status = 'final' AND details_checked_at IS NULL AND starts_at < :post_from
    ORDER BY starts_at DESC
    LIMIT :limit
    """)

_UPSERT_STANDING = text("""
    INSERT INTO hockey_standings (league, team, place, games, points, updated_at)
    VALUES ('extraliga', :team, :place, :games, :points, :now)
    ON CONFLICT (league, team) DO UPDATE
    SET place = EXCLUDED.place, games = EXCLUDED.games, points = EXCLUDED.points, updated_at = EXCLUDED.updated_at
    """)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _params(m: CalendarMatch, now: datetime) -> dict:
    return {
        "source_match_id": m.match_id,
        "home_team": club_name(m.home_club_id, m.home),
        "away_team": club_name(m.away_club_id, m.away),
        "home_club_id": m.home_club_id,
        "away_club_id": m.away_club_id,
        "starts_at": _utc(m.starts_at),
        "arena": m.arena,
        "city": m.city,
        "now": _utc(now),
    }


_PROBE = text("SELECT result_probe, status FROM hockey_matches WHERE id = :id")

_SET_PROBE = text("""
    UPDATE hockey_matches SET result_probe = CAST(:probe AS jsonb), checked_at = :now, updated_at = :now
    WHERE id = :id
    """)

_HAS_PICKS = text("SELECT EXISTS(SELECT 1 FROM hockey_picks WHERE match_id = :id)")

_TO_REVIEW = text("""
    UPDATE hockey_matches
    SET status = 'review', review_reason = :reason, result_probe = CAST(:probe AS jsonb),
        checked_at = :now, updated_at = :now
    WHERE id = :id AND status IN ('scheduled', 'review')
    """)


def _result_problem(home: int | None, away: int | None, decided_in: str | None) -> str | None:
    if home is None or away is None or home == away:
        return "счёт не определён"
    if decided_in not in _DECIDED:
        return "нет метки способа окончания (основное время, овертайм, буллиты)"
    if decided_in != "regulation" and abs(home - away) != 1:
        return "в овертайме и по буллитам разница должна быть ровно в одну шайбу"
    return None


async def confirm_result(
    session: AsyncSession, match_id: int, *, home: int | None, away: int | None, decided_in: str | None, now: datetime
) -> bool:
    """Можно ли публиковать итог: тот же счёт и способ в двух опросах подряд, между ними не меньше 15 минут.

    Если ходов на матч нет, проверять нечего: итог ставится сразу. Первый опрос запоминает итог и возвращает ``False``. Счёт изменился между опросами или не хватает метки
    способа — матч на ручную проверку (``review``), запомненный итог заменяется последним. Админ сильнее:
    ручной ввод закрывает матч без этой проверки.
    """
    now = _utc(now)
    row = (await session.execute(_PROBE, {"id": match_id})).one()
    problem = _result_problem(home, away, decided_in)
    probe = {"home": home, "away": away, "decided_in": decided_in, "first_seen_at": now.isoformat()}
    if problem is not None:
        await session.execute(_TO_REVIEW, {"id": match_id, "reason": problem, "probe": json.dumps(probe), "now": now})
        return False
    # Ходов на матч нет — очки считать не из чего, итог ставим сразу (старые матчи при первом чтении календаря).
    if not (await session.execute(_HAS_PICKS, {"id": match_id})).scalar_one():
        return True
    old = row.result_probe
    same = bool(old) and (old.get("home"), old.get("away"), old.get("decided_in")) == (home, away, decided_in)
    if same:
        first = datetime.fromisoformat(old["first_seen_at"])
        if now - _utc(first) >= RESULT_STABLE_AFTER:
            return True
        return False
    if old:
        await session.execute(
            _TO_REVIEW,
            {
                "id": match_id,
                "reason": f"счёт менялся между опросами: был {old.get('home')}:{old.get('away')}",
                "probe": json.dumps(probe),
                "now": now,
            },
        )
        return False
    await session.execute(_SET_PROBE, {"id": match_id, "probe": json.dumps(probe), "now": now})
    return False


async def upsert_calendar_match(session: AsyncSession, m: CalendarMatch, *, now: datetime) -> str:
    params = _params(m, now)
    record = (await session.execute(_SELECT, {"source_match_id": m.match_id})).one_or_none()
    if record is None:
        record = await _adopt_fallback_row(session, params)
    if record is None:
        await session.execute(_INSERT, params)
        await session.flush()
        record = (await session.execute(_SELECT, {"source_match_id": m.match_id})).one()
        outcome = "inserted"
    else:
        outcome = "unchanged"
        if record.status == "scheduled":
            same = (_utc(record.starts_at), record.home_team, record.away_team) == (
                params["starts_at"],
                params["home_team"],
                params["away_team"],
            )
            if not same:
                await session.execute(_MOVE, {**params, "id": record.id})
                from src.application.hockey_game import on_match_moved

                await on_match_moved(session, match_id=record.id, starts_at=params["starts_at"])
                outcome = "moved"
            else:
                await session.execute(_TOUCH, {"id": record.id, "now": params["now"]})
    # Запасной итог: страница матча молчит, а в календаре счёт уже давно.
    if (
        m.status == STATUS_PLAYED
        and record.status in ("scheduled", "review")
        and _utc(m.starts_at) <= _utc(now) - CALENDAR_RESULT_AFTER
        and m.home_score is not None
        and m.away_score is not None
        and m.home_score != m.away_score
        and await confirm_result(
            session, record.id, home=m.home_score, away=m.away_score, decided_in=m.decided_in, now=now
        )
    ):
        await session.execute(
            _FINAL,
            {
                "id": record.id,
                "home_score": m.home_score,
                "away_score": m.away_score,
                "decided_in": m.decided_in,
                "now": _utc(now),
            },
        )
        outcome = "final" if outcome == "unchanged" else outcome
    return outcome


async def sync_calendar(session: AsyncSession, source: Source, *, now: datetime) -> dict[str, int]:
    """Весь сезон по страницам до «Матчей не найдено». Пустой сезон или битые куски — ошибка цикла."""
    counts = {"inserted": 0, "moved": 0, "unchanged": 0, "final": 0, "failed": 0, "pages": 0}
    seen: set[str] = set()
    for number in range(1, MAX_CALENDAR_PAGES + 1):
        page: CalendarPage = parse_calendar_response(await source.calendar_page(number))
        counts["pages"] = number
        counts["failed"] += len(page.failed)
        for reason in page.failed:
            logger.warning("extraliga calendar page %s: %s", number, reason)
        if page.empty:
            break
        for m in page.matches:
            if m.match_id in seen:
                continue
            seen.add(m.match_id)
            counts[await upsert_calendar_match(session, m, now=now)] += 1
    if not seen:
        raise CalendarEmpty("календарь Экстралиги пуст — похоже, сменился ответ hockey.by")
    if counts["failed"] > max(3, len(seen) // 20):
        raise CalendarBroken(f"не разобрано {counts['failed']} матчей из {len(seen) + counts['failed']}")
    counts["missed"] = await mark_missed(session, seen, now=now)
    return counts


async def mark_missed(session: AsyncSession, seen: set[str], *, now: datetime) -> int:
    """Отметить будущие матчи, которых нет в полном прогоне. Много сразу — не трогаем: разбор мог сломаться."""
    params = {"now": _utc(now), "seen": sorted(seen)}
    missing = int((await session.execute(_COUNT_MISSED, params)).scalar_one())
    if not missing:
        return 0
    future = int((await session.execute(_FUTURE_SCHEDULED, {"now": _utc(now)})).scalar_one())
    if missing > max(MISSED_FLOOR, int(future * MISSED_SHARE_LIMIT)):
        logger.warning("extraliga: %s of %s future matches absent from the calendar — not marking", missing, future)
        return 0
    await session.execute(_MARK_MISSED, params)
    return missing


class CalendarEmpty(RuntimeError):
    """Ответы пришли, а матчей нет — в сезон это поломка разбора."""


class CalendarBroken(RuntimeError):
    """Разобралась только часть календаря — вёрстка куска матча поменялась."""


def _side_json(side: TeamSide) -> dict:
    return {
        "place": side.place,
        "forwards": [asdict(p) for p in side.forwards],
        "defenders": [asdict(p) for p in side.defenders],
        "goalies": [asdict(p) for p in side.goalies],
    }


def details_json(g: GameCenter) -> dict:
    """Снимок страницы матча для API: только то, что показывает экран 12 холста."""
    sides = {g.home.club_id: "home", g.away.club_id: "away"}
    return {
        "official": g.official,
        "periods": [list(p) for p in g.periods],
        "goals": [
            {
                "minute": x.minute,
                "side": sides.get(x.club_id),
                "scorer": x.scorer,
                "assists": list(x.assists),
                "streak": x.streak,
            }
            for x in g.goals
        ],
        "home": _side_json(g.home),
        "away": _side_json(g.away),
        "shots": list(g.shots) if g.shots else None,
        "penalty_minutes": list(g.penalty_minutes) if g.penalty_minutes else None,
        "best_players": list(g.best_players) if g.best_players else None,
        "attendance": g.attendance,
        "video_url": g.video_url,
    }


def details_due(starts_at: datetime, checked_at: datetime | None, *, now: datetime) -> bool:
    now = _utc(now)
    starts_at = _utc(starts_at)
    if checked_at is None:
        return True
    match_day = starts_at - MATCH_DAY_BEFORE <= now <= starts_at + MATCH_DAY_AFTER
    return now - _utc(checked_at) >= (MATCH_DAY_EVERY if match_day else DETAILS_EVERY)


def _details_wanted(row, *, now: datetime) -> bool:
    if row.status != "final":
        return details_due(row.starts_at, row.details_checked_at, now=now)
    # Сыгранный: дозагрузка (ни разу не читали) или протокол ещё не официальный — раз в час.
    return row.details_checked_at is None or _utc(now) - _utc(row.details_checked_at) >= POST_MATCH_EVERY


async def _record_live_score(session: AsyncSession, row, g: GameCenter, *, now: datetime) -> int:
    """Счёт идущего матча со страницы — в живые очки игры (TASK-334). Итог и его сверку не трогает.

    Берём неофициальный счёт начавшегося матча: тот же запрос страницы, что и раз в 15 минут в день матча,
    лишних обращений к hockey.by нет. Любой сбой записи молча пропускается — итог от него не зависит.
    """
    if g.official or g.home_score is None or g.away_score is None or _utc(now) < _utc(row.starts_at):
        return 0
    from src.application.hockey_game import set_live_score

    try:
        async with session.begin_nested():
            ok = await set_live_score(session, match_id=row.id, home=g.home_score, away=g.away_score, now=now)
    except Exception:
        logger.warning("extraliga live score %s failed", row.source_match_id, exc_info=True)
        return 0
    return int(ok)


async def sync_details(session: AsyncSession, source: Source, *, now: datetime) -> dict[str, int]:
    """Страницы матчей на неделю вперёд и сегодняшних — снимок, билеты, официальный итог."""
    counts = {"checked": 0, "final": 0, "failed": 0, "live": 0}
    params = {
        "from_": _utc(now) - MATCH_DAY_AFTER,
        "until": _utc(now) + DETAILS_AHEAD,
        "post_from": _utc(now) - POST_MATCH_WINDOW,
    }
    rows = list((await session.execute(_DUE_DETAILS, params)).all())
    backfill = (await session.execute(_BACKFILL, {"post_from": params["post_from"], "limit": BACKFILL_PER_TICK})).all()
    for row in rows + list(backfill):
        if not _details_wanted(row, now=now):
            continue
        try:
            g = parse_gamecenter(await source.get(match_page_url(row.source_match_id)), match_id=row.source_match_id)
        except SourceDown:
            # Сайт лежит: остальные страницы не ждём, отметку не ставим — вернётся, прочитаем сразу.
            counts["skipped"] = counts.get("skipped", 0) + 1
            break
        except Exception:
            logger.warning("extraliga match %s failed", row.source_match_id, exc_info=True)
            # Битая страница не дёргается каждый тик: следующая попытка — по обычному расписанию.
            await session.execute(_DETAILS_FAILED, {"id": row.id, "now": _utc(now)})
            counts["failed"] += 1
            continue
        await session.execute(
            _DETAILS,
            {
                "id": row.id,
                "details": json.dumps(details_json(g), ensure_ascii=False),
                "tickets_url": g.tickets_url,
                "arena": g.arena,
                "city": g.city,
                "now": _utc(now),
            },
        )
        counts["checked"] += 1
        live = await _record_live_score(session, row, g, now=now)
        counts["live"] += live
        if (
            g.official
            and g.home_score is not None
            and g.away_score is not None
            and g.home_score != g.away_score
            and await confirm_result(
                session, row.id, home=g.home_score, away=g.away_score, decided_in=g.decided_in, now=now
            )
        ):
            closed = await session.execute(
                _FINAL,
                {
                    "id": row.id,
                    "home_score": g.home_score,
                    "away_score": g.away_score,
                    "decided_in": g.decided_in,
                    "now": _utc(now),
                },
            )
            counts["final"] += closed.rowcount
    return counts


async def sync_standings(session: AsyncSession, source: Source, *, now: datetime) -> int:
    rows = parse_standings(await source.get(STANDINGS_URL))
    stored = 0
    for r in rows:
        club = _BY_TEAM_ID.get(r.team_id or "")
        name = club.name if club else r.name
        await session.execute(
            _UPSERT_STANDING, {"team": name, "place": r.place, "games": r.games, "points": r.points, "now": _utc(now)}
        )
        stored += 1
    if stored < 10:
        raise ValueError(f"в таблице Экстралиги только {stored} команд")
    return stored


# ── Запасной источник: flashscore.com ────────────────────────────────

_ADOPT_SELECT = text("""
    SELECT id FROM hockey_matches
    WHERE source = 'hockeyby' AND source_match_id LIKE 'fs%'
      AND home_club_id = :home_club_id AND away_club_id = :away_club_id
      AND (starts_at AT TIME ZONE 'Europe/Minsk')::date = :day
    ORDER BY id LIMIT 1
    """)

_ADOPT = text("UPDATE hockey_matches SET source_match_id = :source_match_id, updated_at = :now WHERE id = :id")

_FALLBACK_ROWS = text("""
    SELECT id, source_match_id, status, starts_at, home_club_id, away_club_id, home_score, away_score, decided_in
    FROM hockey_matches
    WHERE source = 'hockeyby' AND starts_at >= :since AND starts_at <= :until
    ORDER BY starts_at, id
    """)

# Арена нового матча — та, где хозяева последний раз играли дома по данным hockey.by: без арены сайт
# матч не покажет, а выдумывать её нельзя.
_INSERT_FALLBACK = text("""
    INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, home_club_id, away_club_id,
                                starts_at, arena, city, status, checked_at)
    VALUES ('hockeyby', 'extraliga', :source_match_id, :home_team, :away_team, CAST(:home_club_id AS varchar),
            :away_club_id, :starts_at,
            (SELECT arena FROM hockey_matches
             WHERE source = 'hockeyby' AND home_club_id = CAST(:home_club_id AS varchar) AND arena IS NOT NULL
             ORDER BY starts_at DESC LIMIT 1),
            :city, 'scheduled', :now)
    """)

_SOURCE_STATUS = text("""
    INSERT INTO hockey_source_status (source, ok_at, failed_at)
    VALUES (:source, :ok_at, :failed_at)
    ON CONFLICT (source) DO UPDATE
    SET ok_at = COALESCE(EXCLUDED.ok_at, hockey_source_status.ok_at),
        failed_at = COALESCE(EXCLUDED.failed_at, hockey_source_status.failed_at)
    """)

_SOURCE_DOWN = text("""
    SELECT failed_at > COALESCE(ok_at, '-infinity'::timestamptz) AND failed_at >= :fresh
    FROM hockey_source_status WHERE source = :source
    """)


def _minsk_day(value: datetime):
    return _utc(value).astimezone(MINSK_TZ).date()


async def _adopt_fallback_row(session: AsyncSession, params: dict):
    """hockey.by вернулся: матч, который завёл запасной (``fs…``), получает его id — без дубля.

    Пара клубов и минский день; время, арену и прочее дальше правит обычный путь (основному верим)."""
    found = (
        await session.execute(
            _ADOPT_SELECT,
            {
                "home_club_id": params["home_club_id"],
                "away_club_id": params["away_club_id"],
                "day": _minsk_day(params["starts_at"]),
            },
        )
    ).one_or_none()
    if found is None:
        return None
    await session.execute(_ADOPT, {"id": found.id, "source_match_id": params["source_match_id"], "now": params["now"]})
    logger.info("extraliga: hockey.by %s adopted fallback row %s", params["source_match_id"], found.id)
    return (await session.execute(_SELECT, {"source_match_id": params["source_match_id"]})).one()


def _fs_params(m: FlashscoreMatch, now: datetime) -> dict:
    home, away = CLUBS[m.home_club_id or ""], CLUBS[m.away_club_id or ""]
    return {
        "source_match_id": f"{FALLBACK_PREFIX}{m.source_match_id}",
        "home_team": home.name,
        "away_team": away.name,
        "home_club_id": m.home_club_id,
        "away_club_id": m.away_club_id,
        "starts_at": _utc(m.starts_at),
        "arena": None,
        "city": home.city,
        "now": _utc(now),
    }


async def _fallback_live(session: AsyncSession, row, m: FlashscoreMatch, *, now: datetime) -> int:
    """Счёт идущего матча с flashscore — в живые очки игры, как ``_record_live_score``: молча при сбое."""
    if m.home_score is None or m.away_score is None or _utc(now) < _utc(row.starts_at):
        return 0
    from src.application.hockey_game import set_live_score

    try:
        async with session.begin_nested():
            ok = await set_live_score(session, match_id=row.id, home=m.home_score, away=m.away_score, now=now)
    except Exception:
        logger.warning("extraliga fallback live score %s failed", row.source_match_id, exc_info=True)
        return 0
    return int(ok)


async def sync_fallback(session: AsyncSession, fetch: Fetch, *, now: datetime) -> dict[str, int]:
    """Календарь, итоги и живой счёт с flashscore.com, пока hockey.by не отвечает. Один запрос.

    * не сыгранный матч в пределах ``FALLBACK_HORIZON``: тот же день и те же клубы уже есть — не трогаем
      (времени основного верим); нет — ищем строку с той же парой клубов, пропавшую со своего дня
      (перенос: двигаем, ходы — через ``on_match_moved``), иначе вставляем ``fs<id>``;
    * завершённый: итог через ``confirm_result`` (два одинаковых опроса не ближе 15 минут, иначе проверка);
      уже закрытый основным матч не перезаписываем, расхождение — только в лог;
    * идущий: живой счёт.
    Клуб не из ``CLUBS`` пропускаем; исчезнувший матч сами не отменяем.
    """
    from src.application.hockey_matches import SEASON_MONTHS

    counts = {
        "inserted": 0,
        "moved": 0,
        "unchanged": 0,
        "final": 0,
        "pending": 0,
        "disagree": 0,
        "live": 0,
        "skipped": 0,
    }
    matches = parse_flashscore_league(await fetch(FLASHSCORE_EXTRALIGA_URL))
    now = _utc(now)
    if not matches and now.astimezone(MINSK_TZ).month in SEASON_MONTHS:
        raise CalendarEmpty("лента flashscore пуста в сезон — похоже, сменилась вёрстка")
    known = [m for m in matches if m.home_club_id in CLUBS and m.away_club_id in CLUBS]
    for m in matches:
        if m not in known:
            counts["skipped"] += 1
            logger.warning("extraliga fallback: unknown flashscore club in %s — %s", m.home, m.away)
    rows = list(
        (
            await session.execute(
                _FALLBACK_ROWS,
                {"since": now - FALLBACK_RESULTS_BACK, "until": now + FALLBACK_HORIZON + timedelta(days=1)},
            )
        ).all()
    )
    by_key = {(r.home_club_id, r.away_club_id, _minsk_day(r.starts_at)): r for r in rows}
    by_id = {r.source_match_id: r for r in rows}
    fs_keys = {(m.home_club_id, m.away_club_id, _minsk_day(m.starts_at)) for m in known}
    last_fixture = max((_utc(m.starts_at) for m in known if m.status == FS_SCHEDULED), default=now)
    # Несыгранные строки, у которых в ленте нет матча в их день, — кандидаты на «перенесён».
    orphans = [
        r
        for r in rows
        if r.status == "scheduled"
        and now < _utc(r.starts_at) <= min(last_fixture, now + FALLBACK_HORIZON)
        and (r.home_club_id, r.away_club_id, _minsk_day(r.starts_at)) not in fs_keys
    ]
    for m in known:
        key = (m.home_club_id, m.away_club_id, _minsk_day(m.starts_at))
        row = by_id.get(f"{FALLBACK_PREFIX}{m.source_match_id}") or by_key.get(key)
        if m.status == FS_FINAL:
            if row is None or _utc(row.starts_at) < now - FALLBACK_RESULTS_BACK:
                continue
            ours = (m.home_score, m.away_score, m.decided_in)
            if row.status == "final":
                if (row.home_score, row.away_score, row.decided_in) != ours:
                    counts["disagree"] += 1
                    logger.warning("extraliga fallback: match %s final differs from flashscore %s", row.id, ours)
                continue
            if row.status not in ("scheduled", "review"):
                continue
            if await confirm_result(
                session, row.id, home=m.home_score, away=m.away_score, decided_in=m.decided_in, now=now
            ):
                closed = await session.execute(
                    _FINAL,
                    {
                        "id": row.id,
                        "home_score": m.home_score,
                        "away_score": m.away_score,
                        "decided_in": m.decided_in,
                        "now": now,
                    },
                )
                counts["final"] += closed.rowcount
            else:
                counts["pending"] += 1
            continue
        if m.status == FS_LIVE:
            if row is not None and row.status == "scheduled":
                counts["live"] += await _fallback_live(session, row, m, now=now)
            continue
        if m.status != FS_SCHEDULED or not now < _utc(m.starts_at) <= now + FALLBACK_HORIZON:
            continue
        params = _fs_params(m, now)
        if row is not None:
            # Свою строку запасной ведёт сам: другого источника у неё нет.
            if row.source_match_id.startswith(FALLBACK_PREFIX) and _utc(row.starts_at) != params["starts_at"]:
                await _move(session, row.id, params)
                counts["moved"] += 1
            else:
                counts["unchanged"] += 1
            continue
        twins = [r for r in orphans if (r.home_club_id, r.away_club_id) == (m.home_club_id, m.away_club_id)]
        if twins:
            twin = min(twins, key=lambda r: abs(_utc(r.starts_at) - params["starts_at"]))
            orphans.remove(twin)
            await _move(session, twin.id, params)
            counts["moved"] += 1
            continue
        await session.execute(_INSERT_FALLBACK, params)
        counts["inserted"] += 1
    return counts


async def _move(session: AsyncSession, match_id: int, params: dict) -> None:
    await session.execute(_MOVE, {**params, "id": match_id})
    from src.application.hockey_game import on_match_moved

    await on_match_moved(session, match_id=match_id, starts_at=params["starts_at"])


async def mark_source(session: AsyncSession, *, down: bool, now: datetime) -> None:
    """Отметка для сайта: последний разговор с hockey.by удался или нет (заглушка «статистика недоступна»)."""
    now = _utc(now)
    await session.execute(
        _SOURCE_STATUS,
        {"source": SOURCE_HOCKEYBY, "ok_at": None if down else now, "failed_at": now if down else None},
    )


async def hockeyby_down(session: AsyncSession, *, now: datetime) -> bool:
    """hockey.by сейчас не отвечает: последняя отметка — сбой, и она свежая."""
    found = (
        await session.execute(_SOURCE_DOWN, {"source": SOURCE_HOCKEYBY, "fresh": _utc(now) - SOURCE_DOWN_FRESH})
    ).scalar_one_or_none()
    return bool(found)


def _primary_problem(out: dict[str, object], breaker: Breaker) -> str | None:
    """Почему этот проход нужен запасной: hockey.by не отвечает, календарь не читается или все страницы
    матчей битые. ``None`` — основной в порядке."""
    if breaker.down is not None:
        return f"hockey.by не отвечает ({breaker.down})"
    if out.get("calendar_failed"):
        return f"календарь hockey.by не читается ({out.get('calendar_error')})"
    det = out.get("details") or {}
    if isinstance(det, dict) and det.get("failed") and not det.get("checked"):
        return "страницы матчей hockey.by не читаются"
    return None


async def run_tick(
    session: AsyncSession,
    source: Source,
    *,
    now: datetime,
    calendar_due: bool,
    standings_due: bool,
    probe_first: bool = False,
    fallback: Fetch | None = None,
    fallback_due: bool = False,
) -> dict[str, object]:
    """Один проход: календарь и таблица — когда пора, страницы матчей — всегда. Не коммитит.

    Сбой одной части не мешает остальным; ``*_failed`` — чтобы цикл повторил её на следующем тике.
    ``probe_first`` — прошлый проход hockey.by не достучался: сначала пробный запрос с коротким таймаутом.
    ``fallback`` — чтение flashscore (``None`` — запасной выключен); ``fallback_due`` — пора ли его спрашивать.
    ``primary_down`` в ответе — почему основной не годится в этом проходе (``None`` — годится).
    """
    out: dict[str, object] = {"calendar": None, "calendar_failed": False, "standings": None, "standings_failed": False}
    breaker = Breaker(source)
    source = breaker
    if probe_first:
        await breaker.probe()
    if calendar_due:
        try:
            async with session.begin_nested():
                out["calendar"] = await sync_calendar(session, source, now=now)
        except Exception as exc:
            logger.warning("extraliga calendar sync failed", exc_info=True)
            out["calendar_failed"] = True
            out["calendar_error"] = str(exc) or type(exc).__name__
    if standings_due:
        try:
            async with session.begin_nested():
                out["standings"] = await sync_standings(session, source, now=now)
        except Exception as exc:
            logger.warning("extraliga standings failed", exc_info=True)
            out["standings_failed"] = True
            out["standings_error"] = str(exc) or type(exc).__name__
    out["details"] = await sync_details(session, source, now=now)
    if breaker.down is not None or breaker.answered:
        await mark_source(session, down=breaker.down is not None, now=now)
    out["primary_down"] = _primary_problem(out, breaker)
    out["fallback"] = None
    if fallback is not None and fallback_due and out["primary_down"]:
        try:
            async with session.begin_nested():
                out["fallback"] = await sync_fallback(session, fallback, now=now)
        except Exception as exc:
            logger.warning("extraliga fallback failed", exc_info=True)
            out["fallback_failed"] = True
            out["fallback_error"] = str(exc) or type(exc).__name__
    return out


async def fetch_flashscore(url: str) -> str:
    """Один запрос к flashscore: честный User-Agent, без повторов — следующий через 10 минут."""
    from src.ingestion.source_io import fetch_http_text

    return await fetch_http_text(url, headers={"User-Agent": USER_AGENT})


def club_cities(names: Iterable[str]) -> dict[str, str]:
    by_name = {club.name: club.city for club in CLUBS.values()}
    return {name: by_name[name] for name in names if name in by_name}


__all__ = [
    "Breaker",
    "CLUBS",
    "CalendarBroken",
    "CalendarEmpty",
    "Club",
    "HockeyByClient",
    "LEAGUE_EXTRALIGA",
    "SOURCE_HOCKEYBY",
    "club_cities",
    "club_name",
    "details_due",
    "details_json",
    "enabled_clubs",
    "fetch_flashscore",
    "hockeyby_down",
    "match_page_url",
    "run_tick",
    "sync_fallback",
    "sync_calendar",
    "sync_details",
    "sync_standings",
    "upsert_calendar_match",
]
