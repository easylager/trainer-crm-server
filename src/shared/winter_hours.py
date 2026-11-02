"""Часы прошлой зимы сезонных точек (TASK-343): строка источника -> расписание по дням.

Формат результата совместим с ``arena_profile.intervals_for_weekday``:
``{"weekly": {"mon": [["07:00", "23:00"]], ...}}``. Дни без интервала — выходной.

Правило: час, которого нет в источнике, не выдумываем. Пустая строка, «согласно
расписанию», «сеансы по расписанию» — ``known=False``. «Круглосуточно» ставим
только когда источник написал это явно.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

WEEKDAY_KEYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_RU_DAYS = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}
_EN_DAYS = {"mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6}
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_RU_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

_TIME = r"(\d{1,2})[:.](\d{2})"
_RANGE_RE = re.compile(rf"{_TIME}\s*[-–—]\s*{_TIME}")
_DAY_TOKEN = r"(?:пн|вт|ср|чт|пт|сб|вс|mo|tu|we|th|fr|sa|su)"
_DAYS_RE = re.compile(
    rf"\b({_DAY_TOKEN})(?:\s*[-–—]\s*({_DAY_TOKEN}))?((?:\s*,\s*{_DAY_TOKEN}(?:\s*[-–—]\s*{_DAY_TOKEN})?)*)",
    re.IGNORECASE,
)
_MONTH_PREFIX_RE = re.compile(r"^\s*([A-Za-z]{3})\s*-\s*([A-Za-z]{3})\s*:?\s*")
_SINGLE_MONTH_PREFIX_RE = re.compile(r"^\s*([A-Za-z]{3})\s*:\s*")
_SEASON_RU_RE = re.compile(r"(\d{1,2})\s+([а-я]+)\s*[—–-]\s*(\d{1,2})\s+([а-я]+)", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedHours:
    """``known`` — расписание по дням есть; ``mode`` — ``daily|weekly|24h|unknown``."""

    known: bool
    mode: str
    opening_hours: dict[str, Any] | None
    raw: str
    #: сезонные рамки из источника ("12-01", "03-01"), если есть
    season_from: str | None = None
    season_to: str | None = None
    #: источник что-то написал, но разобрать не удалось — на глаз админу
    unparsed: bool = False
    note: str | None = field(default=None)


def _hhmm(h: str, m: str) -> str:
    return f"{int(h):02d}:{int(m):02d}"


def _valid(h: str, m: str) -> bool:
    return 0 <= int(h) <= 24 and 0 <= int(m) < 60 and not (int(h) == 24 and int(m) != 0)


def _expand_days(text: str) -> list[int] | None:
    """«пн-пт», «вт,пт», «Mo-Su» -> индексы дней; None — в тексте нет дней."""
    m = _DAYS_RE.search(text)
    if not m:
        return None
    parts = [(m.group(1), m.group(2))]
    for chunk in re.findall(rf"{_DAY_TOKEN}(?:\s*[-–—]\s*{_DAY_TOKEN})?", m.group(3) or "", re.IGNORECASE):
        pair = [t for t in re.split(r"\s*[-–—]\s*", chunk) if t]
        parts.append((pair[0], pair[1] if len(pair) > 1 else None))
    out: list[int] = []
    for first, last in parts:
        i = _day_index(first)
        j = _day_index(last) if last else i
        if i is None or j is None:
            return None
        span = range(i, j + 1) if j >= i else list(range(i, 7)) + list(range(0, j + 1))
        for d in span:
            if d not in out:
                out.append(d)
    return out


def _day_index(token: str | None) -> int | None:
    if not token:
        return None
    t = token.strip().lower()
    return _RU_DAYS.get(t, _EN_DAYS.get(t))


def _season_from_text(text: str) -> tuple[str | None, str | None]:
    m = _SEASON_RU_RE.search(text.lower())
    if m and m.group(2) in _RU_MONTHS and m.group(4) in _RU_MONTHS:
        return (
            f"{_RU_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}",
            f"{_RU_MONTHS[m.group(4)]:02d}-{int(m.group(3)):02d}",
        )
    return None, None


def parse_hours(raw: str | None) -> ParsedHours:
    """Разобрать строку часов из таблицы 2025/26 или OSM."""
    text = (raw or "").strip()
    if not text:
        return ParsedHours(False, "unknown", None, "")
    low = text.lower()
    s_from, s_to = _season_from_text(text)

    if "круглосут" in low or "24/7" in low:
        weekly = {k: [["00:00", "24:00"]] for k in WEEKDAY_KEYS}
        return ParsedHours(True, "24h", {"weekly": weekly}, text, s_from, s_to)

    weekly: dict[str, list[list[str]]] = {}
    season_months: tuple[int, int] | None = None
    anything = False
    for part in re.split(r";", text):
        chunk = part.strip()
        if not chunk:
            continue
        lc = chunk.lower()
        if re.search(r"\b(off|closed)\b", lc):
            continue
        month_range = _MONTH_PREFIX_RE.match(chunk)
        if month_range and month_range.group(1).lower() in _MONTHS and month_range.group(2).lower() in _MONTHS:
            season_months = (_MONTHS[month_range.group(1).lower()], _MONTHS[month_range.group(2).lower()])
            chunk = chunk[month_range.end():]
        else:
            single = _SINGLE_MONTH_PREFIX_RE.match(chunk)
            if single and single.group(1).lower() in _MONTHS:
                chunk = chunk[single.end():]
        # "Dec-Feb Mo-Su 10:00-22:00" без двоеточия после месяцев
        m2 = re.match(r"^\s*([A-Za-z]{3})-([A-Za-z]{3})\s+(?=\S)", chunk)
        if m2 and m2.group(1).lower() in _MONTHS and m2.group(2).lower() in _MONTHS:
            season_months = (_MONTHS[m2.group(1).lower()], _MONTHS[m2.group(2).lower()])
            chunk = chunk[m2.end():]
        ranges = [(a, b, c, d) for a, b, c, d in _RANGE_RE.findall(chunk)]
        ranges = [r for r in ranges if _valid(r[0], r[1]) and _valid(r[2], r[3])]
        if not ranges:
            continue
        days = _expand_days(_RANGE_RE.sub(" ", chunk))
        targets = days if days is not None else list(range(7))
        for d in targets:
            key = WEEKDAY_KEYS[d]
            for a, b, c, dd in ranges:
                weekly.setdefault(key, []).append([_hhmm(a, b), _hhmm(c, dd)])
        anything = True

    if season_months and not (s_from or s_to):
        s_from, s_to = f"{season_months[0]:02d}-01", f"{season_months[1]:02d}-end"
    if not anything:
        # Текст есть, а часов нет: «согласно расписанию», «сеансы по расписанию».
        return ParsedHours(
            False, "unknown", None, text, s_from, s_to, unparsed="расписан" not in low, note=text
        )
    full = {k: weekly.get(k, []) for k in WEEKDAY_KEYS}
    distinct = {tuple(map(tuple, v)) for v in full.values()}
    mode = "daily" if len(distinct) == 1 and next(iter(distinct)) else "weekly"
    return ParsedHours(True, mode, {"weekly": full}, text, s_from, s_to)


def hours_summary_ru(opening_hours: dict[str, Any] | None) -> str | None:
    """«Пн–Пт 17:00–21:00; Сб–Вс 11:00–22:00» — для подписи. None — часы неизвестны."""
    if not opening_hours or not isinstance(opening_hours.get("weekly"), dict):
        return None
    weekly = opening_hours["weekly"]
    names = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
    sigs = [" и ".join(f"{a}–{b}" for a, b in (weekly.get(k) or [])) or None for k in WEEKDAY_KEYS]
    if not any(sigs):
        return None
    if all(s == sigs[0] for s in sigs):
        return "Ежедневно " + sigs[0] if sigs[0] != "00:00–24:00" else "Круглосуточно"
    groups: list[tuple[int, int, str | None]] = []
    for i, s in enumerate(sigs):
        if groups and groups[-1][2] == s:
            groups[-1] = (groups[-1][0], i, s)
        else:
            groups.append((i, i, s))
    out = []
    for a, b, s in groups:
        label = names[a] if a == b else f"{names[a]}–{names[b]}"
        out.append(f"{label} {s}" if s else f"{label} выходной")
    return "; ".join(out)
