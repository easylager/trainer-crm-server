"""Minsk IceParser strategies. Extract only — persistence is IceSessionPublisher."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from src.ingestion.dates import infer_date_from_day_month, parser_reference_date
from src.ingestion.htmlutil import html_unescape_cell, parse_tables, strip_tags
from src.ingestion.normalize import parse_price_to_minor
from src.ingestion.parsers import IceParser
from src.ingestion.seed_config import (
    MINSK_ARENA_SALEFRAME_CONFIG,
    PARSER_KEY_MINSK_ARENA,
    PARSER_KEY_MINSK_MAIN_ARENA,
    PARSER_KEY_MINSK_SPEED_OVAL,
)
from src.ingestion.koronaticket_rink import enrich_zamok_slots, load_korona_rink_html
from src.ingestion.source_io import fetch_http_json, load_source_json, load_source_text
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
_CHIZ_RINK_LABELS = {"МА": "Малая арена", "БА": "Большая арена"}
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


def _join_api_url(host: str, path: str, query: dict[str, Any] | None = None) -> str:
    url = host.rstrip("/") + "/" + str(path).lstrip("/")
    if query:
        url = f"{url}?{urlencode(query)}"
    return url


def minsk_arena_init_url(config: dict[str, Any]) -> str:
    service_id = int(config.get("service_id") or 55)
    path = str(config.get("init_path") or "/api/v3/frame/init")
    query = dict(config.get("init_query") or {"seid": service_id, "target": "saleframe", "lang": "ru"})
    return _join_api_url(str(config["api_host"]), path, query)


def minsk_arena_calendar_url(config: dict[str, Any]) -> str:
    service_id = int(config.get("service_id") or 55)
    path = str(config.get("calendar_path") or "/api/v1/frame/service/{service_id}/calendar").format(
        service_id=service_id
    )
    return _join_api_url(str(config["api_host"]), path)


def minsk_arena_events_url(config: dict[str, Any], *, local_date: date, tz: ZoneInfo) -> str:
    service_id = int(config.get("service_id") or 55)
    path = str(config.get("events_path") or "/api/v1/frame/service/{service_id}/events").format(
        service_id=service_id
    )
    start = datetime(local_date.year, local_date.month, local_date.day, tzinfo=tz)
    end = start + timedelta(days=1)
    query = dict(config.get("events_query") or {})
    query["from"] = int(start.timestamp())
    query["to"] = int(end.timestamp())
    return _join_api_url(str(config["api_host"]), path, query)


async def _load_minsk_arena_payloads(job: ParserJob) -> tuple[Any, Any, Any]:
    """Fixture JSON when fixture_dir is set; otherwise ABWS init/calendar/events."""
    if job.config.get("fixture_dir"):
        calendar = await load_source_json(job, filename="calendar.json", url_keys=("calendar_url", "url"))
        events_blob = await load_source_json(job, filename="events.json", url_keys=("events_url", "url"))
        init = await load_source_json(job, filename="init.json", url_keys=("init_url", "url"))
        return calendar, events_blob, init
    tz = ZoneInfo(str(job.config.get("timezone") or "Europe/Minsk"))
    init = await fetch_http_json(minsk_arena_init_url(job.config))
    calendar = await fetch_http_json(minsk_arena_calendar_url(job.config))
    events: list[Any] = []
    for row in calendar or []:
        day_raw = row.get("date") if isinstance(row, dict) else None
        if not day_raw:
            continue
        blob = await fetch_http_json(
            minsk_arena_events_url(job.config, local_date=date.fromisoformat(str(day_raw)), tz=tz)
        )
        chunk = blob.get("data") if isinstance(blob, dict) else blob
        events.extend(chunk or [])
    return calendar, {"data": events}, init


async def _load_rental_prices_by_start(
    job: ParserJob, *, calendar_days: set[str], tz: ZoneInfo
) -> dict[int, Any]:
    """Map event.start unix → rental price (already minor). Empty if job has no rental_service_id."""
    rental_id = job.config.get("rental_service_id")
    if not rental_id:
        return {}
    events: list[Any] = []
    fixture_dir = job.config.get("fixture_dir")
    if fixture_dir:
        path = Path(str(fixture_dir)) / "rental_events.json"
        if not path.is_file():
            return {}
        blob = json.loads(path.read_text(encoding="utf-8"))
        chunk = blob.get("data") if isinstance(blob, dict) else blob
        events = list(chunk or [])
    else:
        rental_cfg = dict(job.config)
        rental_cfg["service_id"] = int(rental_id)
        days = set(calendar_days)
        if not days:
            calendar = await fetch_http_json(minsk_arena_calendar_url(rental_cfg))
            days = {str(row.get("date")) for row in (calendar or []) if row.get("date")}
        for day_raw in sorted(days):
            blob = await fetch_http_json(
                minsk_arena_events_url(
                    rental_cfg, local_date=date.fromisoformat(str(day_raw)), tz=tz
                )
            )
            chunk = blob.get("data") if isinstance(blob, dict) else blob
            events.extend(chunk or [])
    zone = int(job.config.get("rental_zone_id") or 0)
    out: dict[int, Any] = {}
    for event in events:
        start_ts = event.get("start")
        if not start_ts:
            continue
        for price in event.get("prices") or []:
            zone_id = int(price.get("mapZoneId") or 0)
            if zone and zone_id != zone:
                continue
            amount = price.get("price")
            if amount is not None:
                out[int(start_ts)] = amount
                break
    return out


def _norm_hhmm(raw: str) -> str:
    match = _HHMM.search(raw.replace(" ", ""))
    if not match:
        raise ValueError(raw)
    return _fmt(int(match.group(1)), int(match.group(2)))


class MinskArenaSaleframeParser(IceParser):
    parser_key = PARSER_KEY_MINSK_ARENA

    async def extract(self, job: ParserJob) -> Extraction:
        calendar, events_blob, init = await _load_minsk_arena_payloads(job)
        tz = ZoneInfo(str(job.config.get("timezone") or "Europe/Minsk"))
        adult_zone = int(job.config.get("adult_zone_id") or 970)
        child_zone = int(job.config.get("child_zone_id") or 971)
        allow = [s.lower() for s in job.config.get("kind_allow_substrings") or ["массовое катание"]]
        drop_items = [s.lower() for s in job.config.get("drop_item_name_substrings") or ["заточка"]]
        calendar_days = {str(row.get("date")) for row in (calendar or []) if row.get("date")}
        rental_by_start = await _load_rental_prices_by_start(job, calendar_days=calendar_days, tz=tz)
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
                    price_rental=rental_by_start.get(int(start_ts)),
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


class MinskMainArenaSaleframeParser(MinskArenaSaleframeParser):
    """ABWS saleframe/62 — «Массовое катание на главной арене» (object «Арена»)."""

    parser_key = PARSER_KEY_MINSK_MAIN_ARENA


def _hockey_mk_saleframe_config(job: ParserJob) -> dict | None:
    """Service/55 config for a second pass when arena 115 job also covers hockey MK."""
    if job.config.get("hockey_mk_service_id") is None:
        return None
    if job.config.get("fixture_dir"):
        hockey_dir = job.config.get("hockey_mk_fixture_dir")
        if not hockey_dir:
            return None
        return {**MINSK_ARENA_SALEFRAME_CONFIG, "fixture_dir": str(hockey_dir)}
    return dict(MINSK_ARENA_SALEFRAME_CONFIG)


class MinskSpeedOvalParser(MinskArenaSaleframeParser):
    """ABWS saleframe/139 on object id=4; hockey rink /55 merged here (uq_ice_parser_jobs_arena_id)."""

    parser_key = PARSER_KEY_MINSK_SPEED_OVAL

    async def extract(self, job: ParserJob) -> Extraction:
        oval = await super().extract(job)
        hockey_cfg = _hockey_mk_saleframe_config(job)
        if hockey_cfg is None:
            return oval
        hockey_job = replace(job, config=hockey_cfg, parser_key=PARSER_KEY_MINSK_ARENA)
        hockey = await MinskArenaSaleframeParser().extract(hockey_job)
        snapshot = dict(oval.snapshot) if isinstance(oval.snapshot, dict) else {"oval": oval.snapshot}
        snapshot["hockey_mk_service"] = hockey.snapshot
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot=snapshot,
            slots=[*oval.slots, *hockey.slots],
        )


class ZamokHtmlParser(IceParser):
    parser_key = "zamok_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="ice-rink.html", url_keys=("url",))
        duration = int(job.config.get("duration_minutes") or 45)
        suffix = str(job.config.get("slot_start_suffix") or ":15")
        horizon = int(job.config.get("horizon_days") or 7)
        run_date = parser_reference_date(job.config)
        prices = _zamok_price_map(html)
        tickets_url = _zamok_tickets_url(html)
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
                        external_url=tickets_url,
                    )
                )
        korona_html = await load_korona_rink_html(job)
        if korona_html:
            enrich_zamok_slots(slots, korona_html)
        from src.shared.schedule_basis import SCHEDULE_BASIS_PROJECTED

        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot=html,
            slots=slots,
            schedule_basis=SCHEDULE_BASIS_PROJECTED,
        )


def _price_from_named_row(html: str, needle: str, *, allow_ohm: bool = False) -> int | None:
    needle_u = needle.upper()
    for table in parse_tables(html):
        for row in table:
            if not row:
                continue
            joined = " ".join(row).upper()
            if needle_u not in joined:
                continue
            skip_tokens = ("ПИНГВИН", "ТРИБУН", "ЗАТОЧКА", "ОФМ")
            if not allow_ohm:
                skip_tokens = (*skip_tokens, "ОХМ")
            if any(skip in joined for skip in skip_tokens):
                continue
            last: int | None = None
            for cell in row:
                amount = parse_price_to_minor(cell, already_minor=False)
                if amount is not None:
                    last = amount
            if last is not None:
                return last
    return None


_BUY_LINK = re.compile(r'<a\b[^>]*href="(https?://[^"]+)"[^>]*>\s*Купить\s+билет', re.I)


def _zamok_tickets_url(html: str) -> str | None:
    """Кнопка «Купить билет» на странице катка (касса koronaticket.by).

    Ссылку берём со страницы, а не прописываем: сменит ТЦ кассу — сменится и у нас.
    Нет кнопки — None, и карточка не обещает онлайн-покупку. Чужие utm-метки меняем на
    свои: касса должна видеть, что покупатель пришёл из каталога, а не со страницы ТЦ.
    """
    match = _BUY_LINK.search(html)
    if not match:
        return None
    parts = urlsplit(match.group(1).replace("&amp;", "&"))
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")]
    query += [("utm_source", "glide"), ("utm_medium", "catalog")]
    return urlunsplit(parts._replace(query=urlencode(query)))


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


def _chizhovka_table_slots(
    schedule: str,
    *,
    reference: date,
    duration_minutes: int,
    keep_rink_labels: set[str],
    kind_raw: str,
    price_adult: int | None,
    price_child: int | None,
    price_rental: int | None,
    age_note: str | None,
    capacity_note: str | None = None,
) -> list[ExtractedSlot]:
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
            header_dates.append(
                infer_date_from_day_month(int(match.group(1)), month, reference)
            )
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
                    if label not in keep_rink_labels:
                        continue
                    start = _fmt(int(hit.group(1)), int(hit.group(2)))
                    hour, minute = (int(part) for part in start.split(":"))
                    end_dt = datetime(2000, 1, 1, hour, minute) + timedelta(minutes=duration_minutes)
                    slots.append(
                        ExtractedSlot(
                            local_date=header_dates[idx].isoformat(),
                            starts_at_local=start,
                            ends_at_local=_fmt(end_dt.hour, end_dt.minute),
                            kind_raw=kind_raw,
                            price_adult=price_adult,
                            price_child=price_child,
                            price_rental=price_rental,
                            session_label=_CHIZ_RINK_LABELS.get(label, label),
                            age_note=age_note,
                            capacity_note=capacity_note,
                        )
                    )
    return slots


class ChizhovkaHtmlParser(IceParser):
    parser_key = "chizhovka_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        schedule = await load_source_text(job, filename="schedule.html", url_keys=("schedule_url",))
        prices = await load_source_text(job, filename="prices.html", url_keys=("prices_url",))
        reference = parser_reference_date(job.config)
        duration = int(job.config.get("default_duration_minutes") or 60)
        keep = {label.upper() for label in job.config.get("keep_rink_labels") or ["МА", "БА"]}
        adult = _price_from_named_row(prices, "ВЗРОСЛЫЙ БИЛЕТ")
        child = _price_from_named_row(prices, "ДЕТСКИЙ БИЛЕТ")
        rental = _price_from_named_row(prices, "ОДНА ПАРА КОНЬКОВ")
        slots = _chizhovka_table_slots(
            schedule,
            reference=reference,
            duration_minutes=duration,
            keep_rink_labels=keep,
            kind_raw="Массовое катание",
            price_adult=adult,
            price_child=child,
            price_rental=rental,
            age_note="детский до 16 лет",
        )
        ohm_schedule: str | None = None
        if job.config.get("ohm_schedule_url"):
            ohm_schedule = await load_source_text(
                job, filename="ohm_schedule.html", url_keys=("ohm_schedule_url",)
            )
            ohm_adult = _price_from_named_row(prices, "ОХМ", allow_ohm=True)
            ohm_duration = int(job.config.get("ohm_duration_minutes") or duration)
            ohm_keep = {
                label.upper() for label in job.config.get("ohm_keep_rink_labels") or ["МА", "БА"]
            }
            slots.extend(
                _chizhovka_table_slots(
                    ohm_schedule,
                    reference=reference,
                    duration_minutes=ohm_duration,
                    keep_rink_labels=ohm_keep,
                    kind_raw="hockey_practice",
                    price_adult=ohm_adult,
                    price_child=None,
                    price_rental=None,
                    age_note=str(
                        job.config.get("ohm_age_note")
                        or "полная хоккейная экипировка; дети 4–14 лет только с инструктором"
                    ),
                    capacity_note=str(job.config.get("ohm_capacity_note") or "до 30 билетов"),
                )
            )
        snapshot: dict[str, Any] = {"schedule": schedule, "prices": prices}
        if ohm_schedule is not None:
            snapshot["ohm_schedule"] = ohm_schedule
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot=snapshot,
            slots=slots,
        )


def _ledby_ohm_price_bands(job: ParserJob) -> dict[int, dict[str, int]]:
    """Adult minor units per duration and weekday/weekend (from led.by/ohm/, not child tiers)."""
    raw = job.config.get("ohm_price_bands")
    if isinstance(raw, dict) and raw:
        out: dict[int, dict[str, int]] = {}
        for key, band in raw.items():
            try:
                duration = int(key)
            except (TypeError, ValueError):
                continue
            if not isinstance(band, dict):
                continue
            row: dict[str, int] = {}
            for day_key in ("weekday", "weekend"):
                value = band.get(day_key)
                if value is not None:
                    row[day_key] = int(value)
            if row:
                out[duration] = row
        if out:
            return out
    return {
        45: {"weekday": 1050, "weekend": 1350},
        60: {"weekday": 1400, "weekend": 1800},
    }


def _ledby_column_slots(
    table: list[list[str]],
    col_idx: int,
    *,
    kind_raw: str,
    price_book: dict[int, dict[str, Any]],
    age_note: str | None,
    capacity_note: str | None = None,
    ohm_adult_only: bool = False,
) -> list[ExtractedSlot]:
    slots: list[ExtractedSlot] = []
    for row in table[1:]:
        if not row:
            continue
        day_match = _DAY_DATE.search(row[0])
        if not day_match:
            continue
        local_date = date(int(day_match.group(3)), int(day_match.group(2)), int(day_match.group(1)))
        cell = row[col_idx] if col_idx < len(row) else ""
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
        day_key = "weekend" if weekend else "weekday"
        if ohm_adult_only:
            adult = band.get(day_key)
            child = None
            rental = None
        else:
            prices = band.get(day_key) or {}
            adult = prices.get("adult")
            child = prices.get("child")
            rental = band.get("rental")
        slots.append(
            ExtractedSlot(
                local_date=local_date.isoformat(),
                starts_at_local=start,
                ends_at_local=_fmt(end_dt.hour, end_dt.minute),
                kind_raw=kind_raw,
                price_adult=adult,
                price_child=child,
                price_rental=rental,
                session_label="дискотека" if disco and not ohm_adult_only else None,
                age_note=age_note,
                capacity_note=capacity_note,
            )
        )
    return slots


class LedByHtmlParser(IceParser):
    parser_key = "ledby_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        timetable = await load_source_text(job, filename="timetable.html", url_keys=("schedule_url",))
        prices_html = await load_source_text(job, filename="mass_skating.html", url_keys=("prices_url",))
        price_book = _ledby_prices(prices_html)
        ohm_price_book = _ledby_ohm_price_bands(job)
        slots: list[ExtractedSlot] = []
        for table in parse_tables(timetable):
            if not table:
                continue
            header = [cell.upper() for cell in table[0]]
            mk_idx = next((i for i, cell in enumerate(header) if "МАССОВОЕ КАТАНИЕ" in cell), None)
            ohm_idx = next(
                (
                    i
                    for i, cell in enumerate(header)
                    if "ОТРАБОТКА" in cell and "ХОККЕЙ" in cell
                ),
                None,
            )
            if mk_idx is None and ohm_idx is None:
                continue
            if mk_idx is not None:
                slots.extend(
                    _ledby_column_slots(
                        table,
                        mk_idx,
                        kind_raw="Массовое катание",
                        price_book=price_book,
                        age_note="детский с 3 до 14 лет",
                    )
                )
            if ohm_idx is not None:
                slots.extend(
                    _ledby_column_slots(
                        table,
                        ohm_idx,
                        kind_raw="hockey_practice",
                        price_book=ohm_price_book,
                        age_note=str(
                            job.config.get("ohm_age_note")
                            or "только в хоккейной экипировке; дети до 14 лет — шлем с маской"
                        ),
                        capacity_note=str(job.config.get("ohm_capacity_note") or "30–35 человек"),
                        ohm_adult_only=True,
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
        reference = parser_reference_date(job.config)
        drop = [label.lower() for label in job.config.get("drop_labels") or []]
        keep = [label.lower() for label in job.config.get("keep_labels") or ["мк"]]
        ohm_labels = [label.lower() for label in job.config.get("ohm_labels") or ["охм"]]
        ohm_adult_minor = int(job.config.get("ohm_adult_minor") or 1400)
        disco_marker = str(job.config.get("disco_marker") or "ДИСКОТЕКА").lower()
        slots: list[ExtractedSlot] = []
        for title, items in _parse_diamond_columns(html):
            title_match = _DIAMOND_TITLE.search(title)
            if not title_match:
                continue
            month = _MONTHS[title_match.group(3).lower()]
            local_date = infer_date_from_day_month(int(title_match.group(2)), month, reference)
            if local_date is None:
                continue
            weekend = local_date.weekday() >= 5
            adult = 1200 if weekend else 1100
            child = 900 if weekend else 800
            rental = 1000
            for item in items:
                lower = item.lower()
                is_ohm = any(token in lower for token in ohm_labels)
                if any(token.lower() in lower for token in drop if token.lower() not in ohm_labels):
                    continue
                is_mk = any(token in lower for token in keep)
                if not is_mk and not is_ohm:
                    continue
                label = "дискотека" if disco_marker in lower and is_mk else None
                kind_raw = "ОХМ" if is_ohm else "МК"
                slot_adult = ohm_adult_minor if is_ohm else adult
                slot_child = None if is_ohm else child
                slot_rental = None if is_ohm else rental
                slot_age = None if is_ohm else "дети 3–14 лет включительно"
                for match in _TIME_RANGE.finditer(item.replace("--", "-")):
                    start = _norm_hhmm(match.group(1))
                    end = _norm_hhmm(match.group(2))
                    slots.append(
                        ExtractedSlot(
                            local_date=local_date.isoformat(),
                            starts_at_local=start,
                            ends_at_local=end,
                            kind_raw=kind_raw,
                            price_adult=slot_adult,
                            price_child=slot_child,
                            price_rental=slot_rental,
                            session_label=label,
                            age_note=slot_age,
                        )
                    )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)


from src.ingestion.adapters_minsk_by_egress import JunostHtmlParser, is_junost_blocked_snapshot  # noqa: E402
