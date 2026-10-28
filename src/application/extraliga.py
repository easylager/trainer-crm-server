"""Матчи Экстралиги с hockey.by: календарь, страница матча, таблица (TASK-340, PDEC-029).

Матчи лежат в ``hockey_matches`` (source='hockeyby', league='extraliga') рядом с матчами Динамо, но игра
«Кто кого» их не видит — она читает ``kk_matches``. Итог ставит страница матча, когда на ней
«Официальные данные»; если её не дождались — счёт из календаря через 6 часов после начала.

Календарь хранится целиком, а показ — партиями клубов: ``extraliga_clubs`` в настройках (решение
владельца 2026-10-28 — включать клубы постепенно).

Нагрузка на hockey.by: календарь раз в сутки (страница + ~31 запрос ajax), страницы матчей на
неделю вперёд раз в сутки и каждые 15 минут в день матча, таблица раз в сутки. Между запросами пауза.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
# Сыгранный матч без официального протокола — страницу дочитываем раз в час, до трёх дней.
POST_MATCH_WINDOW = timedelta(days=3)
POST_MATCH_EVERY = timedelta(hours=1)

USER_AGENT = "Mozilla/5.0 (compatible; GlideBot/1.0; +https://glideclub.by)"


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
        arena = COALESCE(:arena, arena), city = COALESCE(:city, city), checked_at = :now, updated_at = :now
    WHERE id = :id AND status = 'scheduled'
    """)

_TOUCH = text("UPDATE hockey_matches SET checked_at = :now WHERE id = :id")

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
    WHERE source = 'hockeyby'
      AND (
        (status IN ('scheduled', 'review') AND starts_at >= :from_ AND starts_at <= :until)
        OR (status = 'final' AND starts_at >= :post_from
            AND COALESCE((details ->> 'official')::boolean, false) = false)
      )
    ORDER BY starts_at
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


async def upsert_calendar_match(session: AsyncSession, m: CalendarMatch, *, now: datetime) -> str:
    params = _params(m, now)
    record = (await session.execute(_SELECT, {"source_match_id": m.match_id})).one_or_none()
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
    return counts


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
            {"minute": x.minute, "side": sides.get(x.club_id), "scorer": x.scorer, "assists": list(x.assists)}
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


async def sync_details(session: AsyncSession, source: Source, *, now: datetime) -> dict[str, int]:
    """Страницы матчей на неделю вперёд и сегодняшних — снимок, билеты, официальный итог."""
    counts = {"checked": 0, "final": 0, "failed": 0}
    params = {
        "from_": _utc(now) - MATCH_DAY_AFTER,
        "until": _utc(now) + DETAILS_AHEAD,
        "post_from": _utc(now) - POST_MATCH_WINDOW,
    }
    for row in (await session.execute(_DUE_DETAILS, params)).all():
        if row.status == "final":
            if row.details_checked_at is not None and _utc(now) - _utc(row.details_checked_at) < POST_MATCH_EVERY:
                continue
        elif not details_due(row.starts_at, row.details_checked_at, now=now):
            continue
        try:
            g = parse_gamecenter(await source.get(match_page_url(row.source_match_id)), match_id=row.source_match_id)
        except Exception:
            logger.warning("extraliga match %s failed", row.source_match_id, exc_info=True)
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
        if g.official and g.home_score is not None and g.away_score is not None and g.home_score != g.away_score:
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


async def run_tick(
    session: AsyncSession,
    source: Source,
    *,
    now: datetime,
    calendar_due: bool,
    standings_due: bool,
) -> dict[str, object]:
    """Один проход: календарь и таблица — когда пора, страницы матчей — всегда. Не коммитит.

    Сбой одной части не мешает остальным; ``*_failed`` — чтобы цикл повторил её на следующем тике.
    """
    out: dict[str, object] = {"calendar": None, "calendar_failed": False, "standings": None, "standings_failed": False}
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
    return out


def club_cities(names: Iterable[str]) -> dict[str, str]:
    by_name = {club.name: club.city for club in CLUBS.values()}
    return {name: by_name[name] for name in names if name in by_name}


__all__ = [
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
    "match_page_url",
    "run_tick",
    "sync_calendar",
    "sync_details",
    "sync_standings",
    "upsert_calendar_match",
]
