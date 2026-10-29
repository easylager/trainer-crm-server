"""Матчи Динамо-Минск: разбор hcdinamo.by и ленты счёта hockey.by (TASK-296). Только разбор, без сети и БД.

hcdinamo.by — основной источник: окно календаря на ``/matches/`` и страница матча ``/matches/{id}/``
(время, хозяева, гости, счёт, счёт по частям). Явного «матч окончен» на странице нет.
hockey.by — сверка: в ленте счёта у сыгранного матча есть ``hsc-completed`` и метка «ОТ» / «Б».
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.ingestion.htmlutil import strip_tags

MINSK_TZ = ZoneInfo("Europe/Minsk")

HCDINAMO_BASE = "https://hcdinamo.by"
HCDINAMO_CALENDAR_URL = f"{HCDINAMO_BASE}/matches/"
# Следующие месяцы сайт отдаёт только POST-ом; в адресе это лишь ключ, ``default_fetch`` шлёт POST.
HCDINAMO_MONTH_PREFIX = f"{HCDINAMO_CALENDAR_URL}?data_calendar="
HOCKEY_BY_URL = "https://hockey.by/"

DECIDED_REGULATION = "regulation"
DECIDED_OT = "ot"
DECIDED_SO = "so"

# Три периода — основное время, четвёртая часть — овертайм, пятая — серия буллитов (+1 гол победителю).
_DECIDED_BY_PARTS = {3: DECIDED_REGULATION, 4: DECIDED_OT, 5: DECIDED_SO}

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

_CALENDAR_LINK = re.compile(r'href="/matches/(\d+)/"')
_CALENDAR_NEXT = re.compile(r'<a[^>]*class="next a"[^>]*data-date="(\d+)"')
_MATCH_WRAP = re.compile(r'<div class="match_wrap">(.*?)<div class="periods_wrap">', re.S)
_KICKOFF = re.compile(r"<p>\s*(\d{1,2}):(\d{2}),\s*(\d{1,2})\s+([а-яё]+)\s+(\d{4})\s*</p>")
_CLUB_NAME = re.compile(r'<td class="club_name (l|r)">.*?<span class="name">(.*?)</span>', re.S)
_CLUB_CELL = re.compile(r'<td class="club_name(?: ([lr]))?">(.*?)</td>', re.S)
_IMG_SRC = re.compile(r'\bsrc="([^"]+)"')
_NAMED_SPAN = re.compile(r'<span class="name">(.*?)</span>', re.S)
_BARE_SPAN = re.compile(r"<span>(.*?)</span>", re.S)
_IMG_ALT = re.compile(r'\balt="([^"]*)"')
_SCORE_NUM = re.compile(r'<div class="num">\s*(\d+)\s*<span>:</span>\s*(\d+)\s*</div>')
_INLINE_SCORE = re.compile(r'<div class="inline_score">(.*?)</div>', re.S)
_PART = re.compile(r"<span[^>]*>\s*(\d+):(\d+)\s*</span>")

_TICKER_ITEM_SPLIT = re.compile(r'(?=<div class="hsc-item)')
_TICKER_HEAD = re.compile(r'<div class="hsc-item([^"]*)"[^>]*data-time="(\d{2})\.(\d{2})\.(\d{2})"')
_TICKER_LEAGUE = re.compile(r'<div class="hsc-league">(.*?)</div>', re.S)
# У несыгранного матча счёта в ленте нет совсем.
_TICKER_TEAM = re.compile(
    r'<span class="hsc-team-name">(.*?)</span>(?:\s*<span class="hsc-team-points">\s*(\d*)\s*</span>)?',
    re.S,
)
_TICKER_EXTD = re.compile(r'<div class="hsc-match-circle">(.*?)</div>', re.S)
_TICKER_GAME = re.compile(r'href="/gamecenter/(\d+)/"')


@dataclass(frozen=True)
class HcdinamoMatch:
    source_match_id: str
    starts_at: datetime
    home: str
    away: str
    home_score: int | None
    away_score: int | None
    parts: tuple[tuple[int, int], ...]
    home_logo: str | None = None
    away_logo: str | None = None

    @property
    def decided_in(self) -> str | None:
        return _DECIDED_BY_PARTS.get(len(self.parts))

    @property
    def looks_final(self) -> bool:
        """Счёт сложился из 3–5 частей без ничьей. Это ещё не «окончен»: нужна сверка."""
        if self.home_score is None or self.away_score is None or self.decided_in is None:
            return False
        if self.home_score == self.away_score:
            return False
        home_sum = sum(h for h, _ in self.parts)
        away_sum = sum(a for _, a in self.parts)
        if (home_sum, away_sum) != (self.home_score, self.away_score):
            return False
        if self.decided_in != DECIDED_REGULATION and abs(self.home_score - self.away_score) != 1:
            return False
        return True


@dataclass(frozen=True)
class TickerResult:
    game_id: str
    league: str
    local_date: date
    completed: bool
    teams: tuple[str, str]
    points: tuple[int | None, int | None]
    extra: str | None

    @property
    def decided_in(self) -> str:
        if self.extra == "ОТ":
            return DECIDED_OT
        if self.extra in {"Б", "ПБ"}:
            return DECIDED_SO
        return DECIDED_REGULATION


def _text(fragment: str) -> str:
    return strip_tags(fragment).strip()


def _cell_name(cell: str) -> str:
    named = _NAMED_SPAN.search(cell)
    if named is not None and _text(named.group(1)):
        return _text(named.group(1))
    alt = _IMG_ALT.search(cell)
    if alt is not None and alt.group(1).strip():
        return alt.group(1).strip()
    bare = _BARE_SPAN.search(cell)
    return _text(bare.group(1)) if bare is not None else ""


def parse_hcdinamo_logo_index(html: str) -> dict[str, str]:
    """Имя команды → ``src`` логотипа. Календарь (``td.club_name``) и страница матча (``l`` / ``r``)."""
    found: dict[str, str] = {}
    for _side, cell in _CLUB_CELL.findall(html):
        src = _IMG_SRC.search(cell)
        name = _cell_name(cell)
        if src is None or not name:
            continue
        found.setdefault(name, src.group(1))
    return found


def _side_logos(block: str) -> dict[str, str]:
    logos: dict[str, str] = {}
    for side, cell in _CLUB_CELL.findall(block):
        if side not in {"l", "r"}:
            continue
        src = _IMG_SRC.search(cell)
        if src is not None:
            logos[side] = src.group(1)
    return logos


def parse_hcdinamo_calendar(html: str) -> list[str]:
    """Номера матчей из окна календаря, по порядку появления, без повторов."""
    seen: dict[str, None] = {}
    for match_id in _CALENDAR_LINK.findall(html):
        seen.setdefault(match_id, None)
    return list(seen)


def parse_hcdinamo_next_month(html: str) -> str | None:
    """Метка следующего месяца из стрелки «вперёд» календаря; ``None`` — стрелки нет."""
    found = _CALENDAR_NEXT.search(html)
    return found.group(1) if found else None


def hcdinamo_month_url(stamp: str) -> str:
    return f"{HCDINAMO_MONTH_PREFIX}{stamp}"


def hcdinamo_month_stamp(url: str) -> str | None:
    """Обратное к ``hcdinamo_month_url``: метка месяца или ``None`` для обычного адреса."""
    if not url.startswith(HCDINAMO_MONTH_PREFIX):
        return None
    stamp = url[len(HCDINAMO_MONTH_PREFIX) :]
    return stamp if stamp.isdigit() else None


def parse_hcdinamo_match(html: str, *, source_match_id: str) -> HcdinamoMatch:
    """Страница матча. ``ValueError`` — если разметка не та, что мы знаем."""
    wrap = _MATCH_WRAP.search(html)
    if wrap is None:
        raise ValueError("hcdinamo: блок match_wrap не найден")
    block = wrap.group(1)

    kickoff = _KICKOFF.search(block)
    if kickoff is None:
        raise ValueError("hcdinamo: время матча не найдено")
    hour, minute, day, month_word, year = kickoff.groups()
    month = _MONTHS_GENITIVE.get(month_word)
    if month is None:
        raise ValueError(f"hcdinamo: неизвестный месяц {month_word!r}")
    starts_at = datetime(int(year), month, int(day), int(hour), int(minute), tzinfo=MINSK_TZ)

    names = {side: _text(name) for side, name in _CLUB_NAME.findall(block)}
    if not names.get("l") or not names.get("r"):
        raise ValueError("hcdinamo: команды не найдены")

    home_score: int | None = None
    away_score: int | None = None
    parts: tuple[tuple[int, int], ...] = ()
    inline = _INLINE_SCORE.search(block)
    if inline is not None:
        parts = tuple((int(h), int(a)) for h, a in _PART.findall(inline.group(1)))
    num = _SCORE_NUM.search(block)
    if num is not None and parts:
        # До матча там «0:0» без частей — это не счёт.
        home_score, away_score = int(num.group(1)), int(num.group(2))

    logos = _side_logos(block)
    return HcdinamoMatch(
        source_match_id=source_match_id,
        starts_at=starts_at,
        home=names["l"],
        away=names["r"],
        home_score=home_score,
        away_score=away_score,
        parts=parts,
        home_logo=logos.get("l"),
        away_logo=logos.get("r"),
    )


def parse_hockey_by_ticker(html: str) -> list[TickerResult]:
    out: list[TickerResult] = []
    for chunk in _TICKER_ITEM_SPLIT.split(html):
        head = _TICKER_HEAD.match(chunk)
        if head is None:
            continue
        classes, dd, mm, yy = head.groups()
        teams = _TICKER_TEAM.findall(chunk)
        if len(teams) != 2:
            continue
        league = _TICKER_LEAGUE.search(chunk)
        extd = _TICKER_EXTD.search(chunk)
        game = _TICKER_GAME.search(chunk)
        points = tuple(int(p) if p else None for _, p in teams)
        out.append(
            TickerResult(
                game_id=game.group(1) if game else "",
                league=_text(league.group(1)) if league else "",
                local_date=date(2000 + int(yy), int(mm), int(dd)),
                completed="hsc-completed" in classes.split(),
                teams=(_text(teams[0][0]), _text(teams[1][0])),
                points=(points[0], points[1]),
                extra=_text(extd.group(1)) or None if extd else None,
            )
        )
    return out


__all__ = [
    "DECIDED_OT",
    "DECIDED_REGULATION",
    "DECIDED_SO",
    "HCDINAMO_BASE",
    "HCDINAMO_CALENDAR_URL",
    "HCDINAMO_MONTH_PREFIX",
    "HOCKEY_BY_URL",
    "MINSK_TZ",
    "HcdinamoMatch",
    "TickerResult",
    "hcdinamo_month_stamp",
    "hcdinamo_month_url",
    "parse_hcdinamo_calendar",
    "parse_hcdinamo_next_month",
    "parse_hcdinamo_logo_index",
    "parse_hcdinamo_match",
    "parse_hockey_by_ticker",
]
