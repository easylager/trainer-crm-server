"""Экстралига с hockey.by: календарь, страница матча, таблица (TASK-340). Только разбор, без сети и БД.

Календарь — Bitrix-ajax ``2quick:game.calendar`` (PDEC-029): JSON, в нём HTML-куски по 12 матчей.
Года в куске нет — он выводится из сезона («2026-2027»: июль–декабрь → 2026, январь–июнь → 2027).
Страница матча ``/gamecenter/{id}/`` — время с годом, арена, место команд в таблице, ссылка на билеты,
счёт по периодам, голы из ленты событий, лидеры команд; после игры — броски, штраф, зрители из обзора.
id матча в календаре = id страницы матча = ``game_id`` в ленте счёта hockey.by.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from dataclasses import dataclass
from datetime import datetime

from src.ingestion.hockey_sources import DECIDED_OT, DECIDED_REGULATION, DECIDED_SO, MINSK_TZ

HOCKEY_BY_BASE = "https://hockey.by"
CALENDAR_PAGE_URL = f"{HOCKEY_BY_BASE}/calendar/"
CALENDAR_AJAX_URL = f"{HOCKEY_BY_BASE}/bitrix/services/main/ajax.php?mode=class&c=2quick:game.calendar&action=getSelect"

# Сезон 2026/27: id сезона, лиги и дивизиона регулярки на hockey.by (разведка TASK-336).
SEASON_ID = "11"
LEAGUE_EXTRALIGA = "1"
DIVISION_REGULAR = "628"

STATUS_SCHEDULED = "scheduled"
STATUS_PLAYED = "played"  # счёт в календаре есть; официальным его делает страница матча

_MONTHS_NOMINATIVE = {
    "Январь": 1,
    "Февраль": 2,
    "Март": 3,
    "Апрель": 4,
    "Май": 5,
    "Июнь": 6,
    "Июль": 7,
    "Август": 8,
    "Сентябрь": 9,
    "Октябрь": 10,
    "Ноябрь": 11,
    "Декабрь": 12,
}
_MONTHS_GENITIVE = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
# «ОТ» — овертайм, «Бул»/«Б» — буллиты (+1 гол победителю, как в официальном счёте).
_ENDINGS = {"": DECIDED_REGULATION, "ОТ": DECIDED_OT, "Бул": DECIDED_SO, "Б": DECIDED_SO, "ПБ": DECIDED_SO}

_SESSID = re.compile(r"bitrix_sessid['\"]?\s*:\s*['\"]([0-9a-f]{16,64})['\"]")

_ITEM_DATE = re.compile(r'current-game-date">\s*(\d{1,2})\s*<div class="current-game-date-month">([^<]+)</div>')
_ITEM_TEAM = re.compile(
    r'<a href="/new-admin/clubs/(\d+)/" class="current-game-team">.*?current-game-team-name">([^<]*)</div>', re.S
)
_ITEM_POINTS = re.compile(r'current-game-points">(.*?)</div>', re.S)
_ITEM_SCORE = re.compile(r'<a href="/gamecenter/(\d+)/">\s*(\d+)-(\d+)\s*</a>')
_ITEM_ENDING = re.compile(r'game-ending">([^<]*)<')
_ITEM_PLACE = re.compile(r'future-game-place">([^<]*)<')
_ITEM_START = re.compile(r'future-game-start">(?:Начало матча в )?\s*(\d{1,2}):(\d{2})')
_GAMECENTER_ID = re.compile(r"/gamecenter/(\d+)/")
_CITY = re.compile(r"\bг\.\s*([А-ЯЁ][а-яё-]+)")

_GC_NUMBER = re.compile(r'game-header-number">(.*?)</div>', re.S)
_GC_WHEN = re.compile(r"(\d{1,2}):(\d{2}),?\s+(\d{1,2})\s+([а-яё]+)\s+(\d{4})")
_GC_PLACE = re.compile(r'game-header-place">(.*?)</div>', re.S)
_GC_TEAM_BLOCK = re.compile(r'<div class="game-header-team">(.*?)</div><!--\.team-->', re.S)
_GC_TEAM_CLUB = re.compile(r'href="/new-admin/clubs/(\d+)/" class="game-header-team-name">([^<]*)</a>')
_GC_TEAM_RATE = re.compile(r'game-header-team-rates">\s*(\d+)\s*<')
_GC_INFO = re.compile(r'<div class="game-header-info">(.*?)</div><!--\.info-->', re.S)
_GC_SCORE = re.compile(r'game-header-info-score">\s*<span[^>]*>\s*(\d+)\s*</span>\s*:\s*<span[^>]*>\s*(\d+)\s*</span>')
_GC_ENDING = re.compile(r'game-header-info-ending">([^<]*)<')
_GC_PERIOD = re.compile(r'game-header-period">\s*(\d+):(\d+)\s*<')
_GC_CURRENT = re.compile(r'game-header-info-current">([^<]*)<')
_GC_TICKET = re.compile(r'<a href="([^"]+)" class="game-header-info-ticket"')
_GC_EVENT = re.compile(r'<div class="event-slide">(.*?)(?=<div class="event-slide">|</div><!--\.slick-->)', re.S)
_GC_EVENT_GOAL = re.compile(r'event-item-icontype goal"')
_GC_EVENT_TEAM = re.compile(r'event-item-team"><a href="/new-admin/clubs/(\d+)/">')
_GC_EVENT_TIME = re.compile(r'event-item-date">\s*(\d{1,3}):(\d{2})\s*<')
_GC_EVENT_PLAYER = re.compile(r'class="event-item-player">([^<]+)</a>')
# Ассистенты — в подписи события: «18 Мурашов Иван, 98 Соколовский Владислав» (номер, фамилия, имя).
_GC_EVENT_ASSISTS = re.compile(r'event-item-type">(.*?)</div>', re.S)
_GC_ASSIST = re.compile(r"\d+\s+([^,\d]+)")
_GC_BEST = re.compile(r'<div class="game-best-players(.*?)<!--\.game-best-players-->', re.S)
_GC_BEST_GROUP = re.compile(
    r'<div class="best-players-group"> ?<div class="h3 centered">([^<]+)</div>(.*?)(?=<div class="best-players-group">|\Z)', re.S
)
_GC_BEST_COL = re.compile(r'<div class="flx-6 flx-x-12">(.*?)(?=<div class="flx-6 flx-x-12">|\Z)', re.S)
_GC_PLAYER = re.compile(r'class="game-player-name">([^<]+)</a> ?<div class="game-player-points(?:-label)?">(.*?)</div>')
_GC_POINTS = re.compile(r"(\d+)\s*\((\d+)\+(\d+)\)")
_GC_SAVE_PCT = re.compile(r"(\d+(?:[.,]\d+)?)")
_GC_SHOTS = re.compile(r"<b>\s*Броски:\s*</b>\s*(\d+)\b[^–—-]*[–—-]\s*(\d+)")
_GC_PENALTY = re.compile(r"<b>\s*Штраф:\s*</b>\s*(\d+)\s*[–—-]\s*(\d+)")
_GC_BEST_PLAYERS = re.compile(r"<b>\s*Лучшие игроки:\s*</b>\s*([^<]+?)\s*[–—-]\s*([^<]+?)\s*</p>")
_GC_ATTENDANCE = re.compile(r"(\d[\d\s]*)\s+зрител")
_GC_VIDEO = re.compile(r"https://www\.youtube\.com/watch\?v=[\w-]+")
_PLAYER_MARK = re.compile(r"\s*\([^)]*\)\s*$")

_TABLE = re.compile(r"<table.*?</table>", re.S)
_TABLE_ROW = re.compile(r"<tr.*?</tr>", re.S)
_TABLE_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_TABLE_TEAM = re.compile(r"[?&]command=(\d+)")
_TAG = re.compile(r"<[^>]+>")


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(_TAG.sub(" ", fragment or ""))).strip()


@dataclass(frozen=True)
class CalendarMatch:
    match_id: str
    starts_at: datetime
    home: str
    away: str
    home_club_id: str
    away_club_id: str
    arena: str | None
    city: str | None
    status: str
    home_score: int | None = None
    away_score: int | None = None
    decided_in: str | None = None


@dataclass(frozen=True)
class CalendarPage:
    season_start_year: int
    matches: tuple[CalendarMatch, ...]
    # Страница за концом сезона: «Матчей не найдено» вместо матчей.
    empty: bool
    failed: tuple[str, ...] = ()


@dataclass(frozen=True)
class Goal:
    minute: str  # «62:25» — время матча, как на сайте
    club_id: str
    scorer: str
    assists: tuple[str, ...] = ()


@dataclass(frozen=True)
class Leader:
    name: str
    points: int | None = None
    goals: int | None = None
    assists: int | None = None
    save_pct: float | None = None


@dataclass(frozen=True)
class TeamSide:
    club_id: str
    name: str
    place: int | None
    forwards: tuple[Leader, ...] = ()
    defenders: tuple[Leader, ...] = ()
    goalies: tuple[Leader, ...] = ()


@dataclass(frozen=True)
class GameCenter:
    match_id: str
    starts_at: datetime | None
    arena: str | None
    city: str | None
    home: TeamSide
    away: TeamSide
    tickets_url: str | None
    official: bool  # «Официальные данные» — итог утверждён
    home_score: int | None
    away_score: int | None
    decided_in: str | None
    periods: tuple[tuple[int, int], ...]
    goals: tuple[Goal, ...]
    shots: tuple[int, int] | None = None
    penalty_minutes: tuple[int, int] | None = None
    best_players: tuple[str, str] | None = None
    attendance: int | None = None
    video_url: str | None = None


@dataclass(frozen=True)
class StandingRow:
    place: int
    team_id: str | None
    name: str
    games: int
    points: int


def extract_sessid(calendar_html: str) -> str | None:
    """CSRF-токен Bitrix со страницы календаря: без него ajax отвечает ошибкой."""
    found = _SESSID.search(calendar_html or "")
    return found.group(1) if found else None


def calendar_form(sessid: str, *, page: int, season_id: str = SEASON_ID) -> list[tuple[str, str]]:
    """Тело POST, как его шлёт страница календаря (``$('#calendar_filter').serializeArray()``)."""
    fields = (("SEASON", season_id), ("LEAGUE", LEAGUE_EXTRALIGA), ("DIVISION", DIVISION_REGULAR), ("TEAM", "all"), ("MONTH", ""))
    out: list[tuple[str, str]] = []
    for i, (name, value) in enumerate(fields):
        out += [(f"arFilter[{i}][name]", name), (f"arFilter[{i}][value]", value)]
    out += [("status", "all"), ("place", "all"), ("view", "list"), ("page", str(page)), ("sessid", sessid)]
    return out


def _season_start_year(data: dict) -> int:
    for season in data.get("SEASONS") or []:
        if season.get("selected") or str(season.get("UF_SELECTED")) == "1":
            head = re.match(r"(\d{4})", str(season.get("UF_NAME") or ""))
            if head:
                return int(head.group(1))
    raise ValueError("в ответе календаря нет выбранного сезона")


def _ending(raw: str) -> str:
    key = _clean(raw)
    if key not in _ENDINGS:
        raise ValueError(f"неизвестное окончание матча: {key!r}")
    return _ENDINGS[key]


def _calendar_item(fragment: str, *, season_start_year: int) -> CalendarMatch:
    fragment = re.sub(r"\s+", " ", fragment)
    day = _ITEM_DATE.search(fragment)
    teams = _ITEM_TEAM.findall(fragment)
    points = _ITEM_POINTS.search(fragment)
    start = _ITEM_START.search(fragment)
    match_id = _GAMECENTER_ID.search(fragment)
    if not (day and len(teams) == 2 and points and start and match_id):
        raise ValueError("не разобран матч: " + _clean(fragment)[:120])
    month = _MONTHS_NOMINATIVE.get(day.group(2).strip())
    if month is None:
        raise ValueError(f"неизвестный месяц: {day.group(2)!r}")
    year = season_start_year if month >= 7 else season_start_year + 1
    starts_at = datetime(year, month, int(day.group(1)), int(start.group(1)), int(start.group(2)), tzinfo=MINSK_TZ)
    place_m = _ITEM_PLACE.search(fragment)
    arena = _clean(place_m.group(1)) if place_m else None
    city_m = _CITY.search(arena or "")
    score = _ITEM_SCORE.search(points.group(1))
    ending = _ITEM_ENDING.search(fragment)
    return CalendarMatch(
        match_id=match_id.group(1),
        starts_at=starts_at,
        home=_clean(teams[0][1]),
        away=_clean(teams[1][1]),
        home_club_id=teams[0][0],
        away_club_id=teams[1][0],
        arena=arena or None,
        city=city_m.group(1) if city_m else None,
        status=STATUS_PLAYED if score else STATUS_SCHEDULED,
        home_score=int(score.group(2)) if score else None,
        away_score=int(score.group(3)) if score else None,
        decided_in=_ending(ending.group(1) if ending else "") if score else None,
    )


def parse_calendar_response(body: str) -> CalendarPage:
    """Ответ ajax одной страницы. Сломанный кусок не роняет страницу — он в ``failed``."""
    payload = json.loads(body)
    if payload.get("status") != "success":
        raise ValueError(f"календарь hockey.by: status={payload.get('status')!r} errors={payload.get('errors')!r}")
    data = payload.get("data") or {}
    year = _season_start_year(data)
    items = [str(g.get("HTML") or "") for g in data.get("FUTURE_GAMES") or []]
    if len(items) == 1 and "Матчей не найдено" in items[0]:
        return CalendarPage(season_start_year=year, matches=(), empty=True)
    matches: list[CalendarMatch] = []
    failed: list[str] = []
    for fragment in items:
        try:
            matches.append(_calendar_item(fragment, season_start_year=year))
        except ValueError as exc:
            failed.append(str(exc))
    return CalendarPage(season_start_year=year, matches=tuple(matches), empty=not items, failed=tuple(failed))


def _player_name(raw: str) -> str:
    return _PLAYER_MARK.sub("", _clean(raw))


def _leaders(block: str) -> list[list[Leader]]:
    """Колонки хозяев и гостей одной группы лидеров."""
    cols = []
    for col in _GC_BEST_COL.findall(block):
        people = []
        for name, points in _GC_PLAYER.findall(col):
            pts = _GC_POINTS.search(points)
            if pts:
                people.append(Leader(_player_name(name), int(pts.group(1)), int(pts.group(2)), int(pts.group(3))))
            elif "%" in points or "ОБ" in points:
                pct = _GC_SAVE_PCT.search(points)
                people.append(Leader(_player_name(name), save_pct=float(pct.group(1).replace(",", ".")) if pct else None))
        cols.append(people)
    return cols


def _team_side(block: str) -> tuple[str, str, int | None]:
    club = _GC_TEAM_CLUB.search(block)
    if not club:
        raise ValueError("на странице матча не найдена команда")
    rate = _GC_TEAM_RATE.search(block)
    return club.group(1), _clean(club.group(2)), int(rate.group(1)) if rate else None


def parse_gamecenter(page: str, *, match_id: str) -> GameCenter:
    # Атрибуты тегов разнесены по строкам — одна строка без переносов, регулярки проще.
    page = re.sub(r"\s+", " ", page or "")
    header = _GC_NUMBER.search(page)
    when = _GC_WHEN.search(_clean(header.group(1))) if header else None
    if when is None:
        # Будущий матч: время и дата — отдельными блоками в game-header-info.
        info_text = _clean(_GC_INFO.search(page).group(1)) if _GC_INFO.search(page) else ""
        when = re.search(r"(\d{1,2}):(\d{2})\s+(\d{1,2})\s+([а-яё]+)\s+(\d{4})", info_text)
    starts_at = None
    if when and when.group(4) in _MONTHS_GENITIVE:
        starts_at = datetime(
            int(when.group(5)), _MONTHS_GENITIVE[when.group(4)], int(when.group(3)), int(when.group(1)), int(when.group(2)),
            tzinfo=MINSK_TZ,
        )
    place = _GC_PLACE.search(page)
    place_text = _clean(place.group(1)) if place else ""
    arena = place_text.split(",")[0].strip() or None
    city_m = _CITY.search(place_text)
    teams = _GC_TEAM_BLOCK.findall(page)
    if len(teams) != 2:
        raise ValueError(f"матч {match_id}: ожидали две команды в шапке, нашли {len(teams)}")
    (home_id, home_name, home_place), (away_id, away_name, away_place) = (_team_side(t) for t in teams)
    info_m = _GC_INFO.search(page)
    info = info_m.group(1) if info_m else ""
    score = _GC_SCORE.search(info)
    ending = _GC_ENDING.search(info)
    current = _GC_CURRENT.search(info)
    ticket = _GC_TICKET.search(page)

    goals: list[Goal] = []
    for event in _GC_EVENT.findall(page):
        if not _GC_EVENT_GOAL.search(event):
            continue
        team = _GC_EVENT_TEAM.search(event)
        clock = _GC_EVENT_TIME.search(event)
        player = _GC_EVENT_PLAYER.search(event)
        if not (team and clock and player):
            continue
        caption = _GC_EVENT_ASSISTS.search(event)
        assists = tuple(a.strip() for a in _GC_ASSIST.findall(_clean(caption.group(1)))) if caption else ()
        goals.append(Goal(f"{clock.group(1)}:{clock.group(2)}", team.group(1), _clean(player.group(1)), assists))

    leaders: dict[str, list[list[Leader]]] = {}
    best = _GC_BEST.search(page)
    if best:
        for title, block in _GC_BEST_GROUP.findall(best.group(1)):
            leaders[_clean(title).lower()] = _leaders(block)

    def side(i: int) -> dict[str, tuple[Leader, ...]]:
        def pick(group: str) -> tuple[Leader, ...]:
            cols = leaders.get(group) or []
            return tuple(cols[i]) if len(cols) > i else ()

        return {"forwards": pick("нападающие"), "defenders": pick("защитники"), "goalies": pick("вратари")}

    shots = _GC_SHOTS.search(page)
    penalty = _GC_PENALTY.search(page)
    best_players = _GC_BEST_PLAYERS.search(page)
    attendance = _GC_ATTENDANCE.search(page)
    video = _GC_VIDEO.search(page)
    return GameCenter(
        match_id=match_id,
        starts_at=starts_at,
        arena=arena,
        city=city_m.group(1) if city_m else None,
        home=TeamSide(home_id, home_name, home_place, **side(0)),
        away=TeamSide(away_id, away_name, away_place, **side(1)),
        tickets_url=htmllib.unescape(ticket.group(1)) if ticket else None,
        official="Официальные данные" in (current.group(1) if current else ""),
        home_score=int(score.group(1)) if score else None,
        away_score=int(score.group(2)) if score else None,
        decided_in=_ending(ending.group(1)) if score and ending else (DECIDED_REGULATION if score else None),
        periods=tuple((int(a), int(b)) for a, b in _GC_PERIOD.findall(info)),
        goals=tuple(goals),
        shots=(int(shots.group(1)), int(shots.group(2))) if shots else None,
        penalty_minutes=(int(penalty.group(1)), int(penalty.group(2))) if penalty else None,
        best_players=(_clean(best_players.group(1)), _clean(best_players.group(2))) if best_players else None,
        attendance=int(re.sub(r"\s", "", attendance.group(1))) if attendance else None,
        video_url=video.group(0) if video else None,
    )


def parse_standings(page: str) -> list[StandingRow]:
    """Таблица дивизиона: место, команда, игры, очки. Колонки — по заголовку, не по номеру."""
    table = _TABLE.search(page or "")
    if not table:
        raise ValueError("на странице нет турнирной таблицы")
    rows = _TABLE_ROW.findall(table.group(0))
    if not rows:
        raise ValueError("турнирная таблица пуста")
    head = [_clean(c) for c in _TABLE_CELL.findall(rows[0])]
    try:
        i_place, i_team, i_games, i_points = head.index("№"), head.index("Команда"), head.index("И"), head.index("О")
    except ValueError as exc:
        raise ValueError(f"заголовок таблицы изменился: {head}") from exc
    out: list[StandingRow] = []
    for row in rows[1:]:
        cells = _TABLE_CELL.findall(row)
        if len(cells) <= max(i_place, i_team, i_games, i_points):
            continue
        team_id = _TABLE_TEAM.search(cells[i_team])
        out.append(
            StandingRow(
                place=int(_clean(cells[i_place])),
                team_id=team_id.group(1) if team_id else None,
                name=_clean(cells[i_team]),
                games=int(_clean(cells[i_games])),
                points=int(_clean(cells[i_points])),
            )
        )
    return out


__all__ = [
    "CALENDAR_AJAX_URL",
    "CALENDAR_PAGE_URL",
    "CalendarMatch",
    "CalendarPage",
    "GameCenter",
    "Goal",
    "HOCKEY_BY_BASE",
    "Leader",
    "STATUS_PLAYED",
    "STATUS_SCHEDULED",
    "StandingRow",
    "TeamSide",
    "calendar_form",
    "extract_sessid",
    "parse_calendar_response",
    "parse_gamecenter",
    "parse_standings",
]
