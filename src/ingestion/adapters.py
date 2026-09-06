"""Minsk IceParser strategies. Extract only — persistence is IceSessionPublisher."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.ingestion.htmlutil import html_unescape_cell, parse_tables, strip_tags
from src.ingestion.normalize import parse_price_to_minor
from src.ingestion.parsers import IceParser
from src.ingestion.seed_config import PARSER_KEY_MINSK_ARENA
from src.ingestion.source_io import load_source_json, load_source_text
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob

_TIME_RANGE = re.compile(r"(\d{1,2}[:.]\d{2})\s*[-–—]+\s*(\d{1,2}[:.]\d{2})")
_HHMM = re.compile(r"(\d{1,2})[:.](\d{2})")
_MONTHS = {
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
_DAY_DATE = re.compile(
    r"(?:Пн|Вт|Ср|Чт|Пт|Сб|Вс)\.(\d{2})\.(\d{2})\.(\d{4})",
    re.IGNORECASE,
)
_LED_TIME = re.compile(r"(\d{1,2}:\d{2})\s*\((\d+)\s*час", re.IGNORECASE)
_CHIZ_CELL = re.compile(r"(\d{1,2})[.:](\d{2})\s*(МА|БА)", re.IGNORECASE)
_CHIZ_HEADER = re.compile(
    r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)",
    re.IGNORECASE,
)
_DIAMOND_TITLE = re.compile(
    r"(Пн|Вт|Ср|Чт|Пт|Сб|Вс)\s*,\s*(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)",
    re.IGNORECASE,
)


def _fmt(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _norm_hhmm(raw: str) -> str:
    match = _HHMM.search(raw.replace(" ", ""))
    if not match:
        raise ValueError(raw)
    return _fmt(int(match.group(1)), int(match.group(2)))


class MinskArenaSaleframeParser(IceParser):
    parser_key = PARSER_KEY_MINSK_ARENA

    async def extract(self, job: ParserJob) -> Extraction:
        calendar = await load_source_json(job, filename="calendar.json", url_keys=("calendar_url", "url"))
        events_blob = await load_source_json(job, filename="events.json", url_keys=("events_url", "url"))
        init = await load_source_json(job, filename="init.json", url_keys=("init_url", "url"))
        tz = ZoneInfo(str(job.config.get("timezone") or "Europe/Minsk"))
        adult_zone = int(job.config.get("adult_zone_id") or 970)
        child_zone = int(job.config.get("child_zone_id") or 971)
        allow = [s.lower() for s in job.config.get("kind_allow_substrings") or ["массовое катание"]]
        drop_items = [s.lower() for s in job.config.get("drop_item_name_substrings") or ["заточка"]]
        calendar_days = {str(row.get("date")) for row in (calendar or []) if row.get("date")}
        events = events_blob.get("data") if isinstance(events_blob, dict) else events_blob
        zone_names = {}
        for zone in (((init.get("mapData") or {}).get("map") or {}).get("staticZones") or []):
            zone_names[int(zone["id"])] = str(zone.get("name") or "")
        slots: list[ExtractedSlot] = []
        age_note = None
        child_name = zone_names.get(child_zone, "")
        if "до" in child_name.lower():
            age_note = "детский до 14 лет" if "14" in child_name else child_name
        performance = str((init.get("performance") or {}).get("name") or "Массовое катание")
        for event in events or []:
            start_ts = event.get("start")
            end_ts = event.get("end")
            if not start_ts:
                continue
            start_local = datetime.fromtimestamp(int(start_ts), tz=tz)
            if start_local.hour == 3 and start_local.minute == 1:
                continue
            local_date = start_local.date().isoformat()
            if calendar_days and local_date not in calendar_days:
                continue
            end_local = datetime.fromtimestamp(int(end_ts), tz=tz) if end_ts else start_local + timedelta(
                minutes=int(job.config.get("default_duration_minutes") or 45)
            )
            adult = child = None
            zone_hit = False
            for price in event.get("prices") or []:
                zone_id = int(price.get("mapZoneId") or 0)
                name = zone_names.get(zone_id, "")
                if any(token in name.lower() for token in drop_items):
                    continue
                if any(token in name.lower() for token in allow) or zone_id in {adult_zone, child_zone}:
                    zone_hit = True
                amount = price.get("price")
                if zone_id == adult_zone:
                    adult = amount
                elif zone_id == child_zone:
                    child = amount
            if not zone_hit:
                continue
            slots.append(
                ExtractedSlot(
                    local_date=local_date,
                    starts_at_local=_fmt(start_local.hour, start_local.minute),
                    ends_at_local=_fmt(end_local.hour, end_local.minute),
                    kind_raw=performance,
                    price_adult=adult,
                    price_child=child,
                    price_rental=None,
                    source_id=str(event.get("id") or ""),
                    session_label=performance,
                    age_note=age_note,
                )
            )
        snapshot = {"calendar": calendar, "events": events_blob, "init_service": (init.get("service") or {}).get("id")}
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot=snapshot,
            slots=slots,
        )


class ZamokHtmlParser(IceParser):
    parser_key = "zamok_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="ice-rink.html", url_keys=("url",))
        duration = int(job.config.get("duration_minutes") or 45)
        suffix = str(job.config.get("slot_start_suffix") or ":15")
        horizon = int(job.config.get("horizon_days") or 7)
        run_date = date.fromisoformat(str(job.config.get("run_date") or date.today().isoformat()))
        prices = _zamok_price_map(html)
        weekday_adult = prices.get("weekday_adult")
        weekend_adult = prices.get("weekend_adult")
        weekday_child = prices.get("weekday_child")
        weekend_child = prices.get("weekend_child")
        rental = prices.get("rental")
        text = strip_tags(html)
        starts: list[str] = []
        seen: set[str] = set()
        for match in _TIME_RANGE.finditer(text):
            start = _norm_hhmm(match.group(1))
            if not start.endswith(suffix):
                continue
            if start in seen:
                continue
            seen.add(start)
            starts.append(start)
        starts.sort()
        slots: list[ExtractedSlot] = []
        for offset in range(horizon):
            local_date = run_date + timedelta(days=offset)
            weekend = local_date.weekday() >= 5
            adult = weekend_adult if weekend else weekday_adult
            child = weekend_child if weekend else weekday_child
            for start in starts:
                hour, minute = (int(part) for part in start.split(":"))
                end_dt = datetime(2000, 1, 1, hour, minute) + timedelta(minutes=duration)
                slots.append(
                    ExtractedSlot(
                        local_date=local_date.isoformat(),
                        starts_at_local=start,
                        ends_at_local=_fmt(end_dt.hour, end_dt.minute),
                        kind_raw="Массовое катание",
                        price_adult=adult,
                        price_child=child,
                        price_rental=rental,
                        age_note="детский от 3 до 14 лет",
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)


def _price_from_named_row(html: str, needle: str) -> int | None:
    needle_u = needle.upper()
    for table in parse_tables(html):
        for row in table:
            if not row:
                continue
            joined = " ".join(row).upper()
            if needle_u not in joined:
                continue
            if any(skip in joined for skip in ("ПИНГВИН", "ТРИБУН", "ЗАТОЧКА", "ОХМ", "ОФМ")):
                continue
            last: int | None = None
            for cell in row:
                amount = parse_price_to_minor(cell, already_minor=False)
                if amount is not None:
                    last = amount
            if last is not None:
                return last
    return None


def _zamok_price_map(html: str) -> dict[str, int | None]:
    items = re.findall(
        r'et-prices-list-item__title">([^<]*)</span>\s*'
        r'<span class="et-prices-list-item__subtitle">([^<]*)</span>.*?'
        r'et-prices-list-item__value">([^<]*)</div>',
        html,
        re.S,
    )
    found: dict[str, int | None] = {}
    for title, subtitle, value in items:
        blob = f"{title} {subtitle}".lower()
        amount = parse_price_to_minor(value, already_minor=False)
        if "абонемент" in blob or "пингвин" in blob or "морской котик" in blob:
            continue
        if "взрослый" in blob and "будн" in blob:
            found["weekday_adult"] = amount
        elif "взрослый" in blob and "выходн" in blob:
            found["weekend_adult"] = amount
        elif "детский" in blob and "будн" in blob:
            found["weekday_child"] = amount
        elif "детский" in blob and "выходн" in blob:
            found["weekend_child"] = amount
        elif "прокат коньков" in blob and "пара" in blob:
            found["rental"] = amount
    return found


class ChizhovkaHtmlParser(IceParser):
    parser_key = "chizhovka_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        schedule = await load_source_text(job, filename="schedule.html", url_keys=("schedule_url",))
        prices = await load_source_text(job, filename="prices.html", url_keys=("prices_url",))
        year = int(job.config.get("run_year") or 2026)
        duration = int(job.config.get("default_duration_minutes") or 60)
        keep = {label.upper() for label in job.config.get("keep_rink_labels") or ["МА", "БА"]}
        adult = _price_from_named_row(prices, "ВЗРОСЛЫЙ БИЛЕТ")
        child = _price_from_named_row(prices, "ДЕТСКИЙ БИЛЕТ")
        rental = _price_from_named_row(prices, "ОДНА ПАРА КОНЬКОВ")
        slots: list[ExtractedSlot] = []
        for table in parse_tables(schedule):
            if len(table) < 2 or len(table[0]) < 5:
                continue
            header_dates: list[date | None] = []
            for cell in table[0]:
                match = _CHIZ_HEADER.search(cell)
                if not match:
                    header_dates.append(None)
                    continue
                month = _MONTHS[match.group(2).lower()]
                header_dates.append(date(year, month, int(match.group(1))))
            if not any(header_dates):
                continue
            for row in table[1:]:
                for idx, cell in enumerate(row):
                    if idx >= len(header_dates) or header_dates[idx] is None:
                        continue
                    if "билеты проданы" in cell.lower():
                        continue
                    for hit in _CHIZ_CELL.finditer(cell):
                        label = hit.group(3).upper()
                        if label not in keep:
                            continue
                        start = _fmt(int(hit.group(1)), int(hit.group(2)))
                        hour, minute = (int(part) for part in start.split(":"))
                        end_dt = datetime(2000, 1, 1, hour, minute) + timedelta(minutes=duration)
                        slots.append(
                            ExtractedSlot(
                                local_date=header_dates[idx].isoformat(),
                                starts_at_local=start,
                                ends_at_local=_fmt(end_dt.hour, end_dt.minute),
                                kind_raw="Массовое катание",
                                price_adult=adult,
                                price_child=child,
                                price_rental=rental,
                                session_label=label,
                                age_note="детский до 16 лет",
                            )
                        )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"schedule": schedule, "prices": prices},
            slots=slots,
        )


class LedByHtmlParser(IceParser):
    parser_key = "ledby_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        timetable = await load_source_text(job, filename="timetable.html", url_keys=("schedule_url",))
        prices_html = await load_source_text(job, filename="mass_skating.html", url_keys=("prices_url",))
        price_book = _ledby_prices(prices_html)
        slots: list[ExtractedSlot] = []
        for table in parse_tables(timetable):
            if not table:
                continue
            header = [cell.upper() for cell in table[0]]
            mk_idx = next((i for i, cell in enumerate(header) if "МАССОВОЕ КАТАНИЕ" in cell), None)
            if mk_idx is None:
                continue
            for row in table[1:]:
                if not row:
                    continue
                day_match = _DAY_DATE.search(row[0])
                if not day_match:
                    continue
                local_date = date(int(day_match.group(3)), int(day_match.group(2)), int(day_match.group(1)))
                cell = row[mk_idx] if mk_idx < len(row) else ""
                disco = "*" in cell
                time_match = _LED_TIME.search(cell)
                if not time_match:
                    continue
                start = _norm_hhmm(time_match.group(1))
                hours = int(time_match.group(2))
                duration = hours * 60
                hour, minute = (int(part) for part in start.split(":"))
                end_dt = datetime(2000, 1, 1, hour, minute) + timedelta(minutes=duration)
                weekend = local_date.weekday() >= 5
                band = price_book.get(duration) or price_book.get(60) or {}
                key = "weekend" if weekend else "weekday"
                prices = band.get(key) or {}
                slots.append(
                    ExtractedSlot(
                        local_date=local_date.isoformat(),
                        starts_at_local=start,
                        ends_at_local=_fmt(end_dt.hour, end_dt.minute),
                        kind_raw="Массовое катание",
                        price_adult=prices.get("adult"),
                        price_child=prices.get("child"),
                        price_rental=band.get("rental"),
                        session_label="дискотека" if disco else None,
                        age_note="детский с 3 до 14 лет",
                    )
                )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"timetable": timetable, "prices": prices_html},
            slots=slots,
        )


def _ledby_prices(html: str) -> dict[int, dict[str, Any]]:
    """duration_minutes → weekday/weekend adult/child + rental."""
    book: dict[int, dict[str, Any]] = {
        45: {"weekday": {}, "weekend": {}, "rental": 450},
        60: {"weekday": {}, "weekend": {}, "rental": 500},
        75: {"weekday": {}, "weekend": {}, "rental": 550},
    }
    slides = re.findall(r"class='et_slidecontent'>(.*?)</div>", html, re.S)
    durations = [45, 60, 75]
    for duration, slide in zip(durations, slides):
        plain = html_unescape_cell(slide)
        weekday = re.search(
            r"Взрослый\s*[—\-]\s*([\d,]+)\s*руб\.;\s*детский[^—\-]*[—\-]\s*([\d,]+)",
            plain,
            re.I,
        )
        weekend = re.search(
            r"выходные[^:]*:\s*взрослый\s*[—\-]\s*([\d,]+)\s*руб\.;\s*детский[^—\-]*[—\-]\s*([\d,]+)",
            plain,
            re.I,
        )
        if weekday:
            book[duration]["weekday"] = {
                "adult": parse_price_to_minor(weekday.group(1) + " руб.", already_minor=False),
                "child": parse_price_to_minor(weekday.group(2) + " руб.", already_minor=False),
            }
        if weekend:
            book[duration]["weekend"] = {
                "adult": parse_price_to_minor(weekend.group(1) + " руб.", already_minor=False),
                "child": parse_price_to_minor(weekend.group(2) + " руб.", already_minor=False),
            }
        elif weekday and duration == 75:
            book[duration]["weekend"] = dict(book[duration]["weekday"])
    rental_blob = html_unescape_cell(html)
    for duration, needle in ((45, "45 минут"), (60, "60 минут"), (75, "1 час 15")):
        match = re.search(rf"на сеанс {needle}\s*—\s*([\d,]+)\s*руб", rental_blob)
        if match:
            book[duration]["rental"] = parse_price_to_minor(match.group(1) + " руб.", already_minor=False)
    return book


def _parse_diamond_columns(html: str) -> list[tuple[str, list[str]]]:
    """Regex extract of the 7-column MK grid (id irqsbii62).

    Cells are ``.list__item`` wrappers. Text lives in ``span`` or ``div``
    ``text-block-wrap-div``; a single MK cell may hold two intervals.
    """
    start = html.find("id='irqsbii62_0'")
    if start < 0:
        start = html.find('id="irqsbii62_0"')
    chunk = html[start:] if start >= 0 else html
    columns: list[tuple[str, list[str]]] = []
    parts = re.split(r"<div class='blocklist__item_title[^']*'\s*id='[^']+'>", chunk)
    for part in parts[1:]:
        title_match = re.search(r"text-block-wrap-div'\s*>(.*?)</div>", part, re.S)
        if not title_match:
            continue
        title = html_unescape_cell(title_match.group(1))
        list_html = part.split("blocklist__item_text", 1)[0]
        items = [html_unescape_cell(body) for body in re.split(r"<div class='list__item\b", list_html)[1:]]
        if title and items:
            columns.append((title, items))
            if len(columns) >= 7:
                break
    return columns


class DiamondHtmlParser(IceParser):
    parser_key = "diamond_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="ledovaya-arena.html", url_keys=("schedule_url", "url"))
        year = int(job.config.get("run_year") or 2026)
        drop = [label.lower() for label in job.config.get("drop_labels") or []]
        keep = [label.lower() for label in job.config.get("keep_labels") or ["мк"]]
        disco_marker = str(job.config.get("disco_marker") or "ДИСКОТЕКА").lower()
        slots: list[ExtractedSlot] = []
        for title, items in _parse_diamond_columns(html):
            title_match = _DIAMOND_TITLE.search(title)
            if not title_match:
                continue
            month = _MONTHS[title_match.group(3).lower()]
            local_date = date(year, month, int(title_match.group(2)))
            weekend = local_date.weekday() >= 5
            adult = 1200 if weekend else 1100
            child = 900 if weekend else 800
            rental = 1000
            for item in items:
                lower = item.lower()
                if any(token.lower() in lower for token in drop):
                    continue
                if not any(token in lower for token in keep):
                    continue
                label = "дискотека" if disco_marker in lower else None
                for match in _TIME_RANGE.finditer(item.replace("--", "-")):
                    start = _norm_hhmm(match.group(1))
                    end = _norm_hhmm(match.group(2))
                    slots.append(
                        ExtractedSlot(
                            local_date=local_date.isoformat(),
                            starts_at_local=start,
                            ends_at_local=end,
                            kind_raw="МК",
                            price_adult=adult,
                            price_child=child,
                            price_rental=rental,
                            session_label=label,
                            age_note="дети 3–14 лет включительно",
                        )
                    )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)
