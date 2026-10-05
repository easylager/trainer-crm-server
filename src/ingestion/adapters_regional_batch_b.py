"""Regional BY IceParser strategies, batch B. Extract only — no ice_sessions writes.

Covers 4 arenas researched in .ai/parsers/<slug>.md with fixtures under
.ai/data/fixtures/<slug>/: grodno-triniti (arena 10), grodno-neman (arena 11),
lida-lds (arena 37), novopolotsk-lds (arena 30). Mirrors the style of
src/ingestion/adapters.py — new file, that module is untouched.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from src.ingestion.htmlutil import html_unescape_cell, parse_tables, strip_tags
from src.ingestion.normalize import parse_price_to_minor
from src.shared.schedule_basis import SCHEDULE_BASIS_PHOTO, SCHEDULE_BASIS_PROJECTED
from src.ingestion.parsers import IceParser
from src.ingestion.seed_config_regional_batch_b import (
    PARSER_KEY_GRODNO_NEMAN,
    PARSER_KEY_GRODNO_TRINITI,
    PARSER_KEY_LIDA_LDS,
    PARSER_KEY_NOVOPOLOTSK_LDS,
)
from src.ingestion.source_io import fetch_http_bytes, fetch_http_text, load_source_json, load_source_text
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob

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

_HHMM = re.compile(r"(\d{1,2})[:.](\d{2})")


def _fmt(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _end_time(start: str, duration_minutes: int) -> str:
    hour, minute = (int(part) for part in start.split(":"))
    end_dt = datetime(2000, 1, 1, hour, minute) + timedelta(minutes=duration_minutes)
    return _fmt(end_dt.hour, end_dt.minute)


# ---------------------------------------------------------------------------
# Гродно, ТЦ «Тринити» (arena 10) — dhtmlx JSON API, richest/simplest source.
# ---------------------------------------------------------------------------


def _triniti_rental_minor(prices_html: str) -> int | None:
    for table in parse_tables(prices_html):
        for row in table:
            if len(row) < 2:
                continue
            if "прокат коньков" not in row[1].strip().lower():
                continue
            last: int | None = None
            for cell in row:
                amount = parse_price_to_minor(cell, already_minor=False)
                if amount is not None:
                    last = amount
            if last is not None:
                return last
    return None


class GrodnoTrinitiParser(IceParser):
    parser_key = PARSER_KEY_GRODNO_TRINITI

    async def extract(self, job: ParserJob) -> Extraction:
        payload = await load_source_json(job, filename="ice.json", url_keys=("api_url", "url"))
        prices_html = await load_source_text(job, filename="prajs.html", url_keys=("prices_url",))
        items = payload.get("data") if isinstance(payload, dict) else payload
        drop_gte = int(job.config.get("drop_if_adult_minor_gte") or 2000)
        age_note = str(job.config.get("age_note") or "детский от 3 до 12 лет")
        rental = _triniti_rental_minor(prices_html)
        if job.config.get("rental_minor") is not None:
            rental = int(job.config["rental_minor"])
        booking_url = str(job.config.get("booking_url") or "").strip() or None
        slots: list[ExtractedSlot] = []
        for item in items or []:
            start_raw = str(item.get("start_date") or "")
            end_raw = str(item.get("end_date") or "")
            if not start_raw:
                continue
            local_date, _, start_time = start_raw.partition(" ")
            _, _, end_time = end_raw.partition(" ")
            adult = parse_price_to_minor(item.get("price"), already_minor=False)
            child = parse_price_to_minor(item.get("c_price"), already_minor=False)
            if adult is not None and adult >= drop_gte:
                continue
            slots.append(
                ExtractedSlot(
                    local_date=local_date,
                    starts_at_local=start_time[:5],
                    ends_at_local=end_time[:5] or None,
                    kind_raw="public_skate",
                    price_adult=adult,
                    price_child=child,
                    price_rental=rental,
                    source_id=str(item.get("id") or "") or None,
                    age_note=age_note,
                    external_url=booking_url,
                )
            )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"ice": payload, "prajs": prices_html},
            slots=slots,
        )


# ---------------------------------------------------------------------------
# Гродно, ЛДС «Неман» (arena 11) — live source is a hockey.by news post, not
# the dedicated (stale) schedule widget. Fragile V1: best-effort weekly poll,
# documented in GRODNO_NEMAN_CONFIG["notes"].
# ---------------------------------------------------------------------------

_NEMAN_MONTHS = "|".join(_MONTHS_GENITIVE)
_NEMAN_ARTICLE_DATE = re.compile(
    rf'<span\s+class="date"[^>]*>.*?(\d{{1,2}})\s+({_NEMAN_MONTHS})\s+(\d{{4}})',
    re.IGNORECASE | re.S,
)
_NEMAN_SESSION = re.compile(
    rf"(\d{{1,2}})\s+({_NEMAN_MONTHS})"
    rf"(?:\s*\([^)]+\))?"
    rf"(?P<venue>.*?)"
    rf"Время:\s*"
    rf"(?P<times>.*?)"
    rf"(?=\d{{1,2}}\s+(?:{_NEMAN_MONTHS})|Стоимость|$)",
    re.IGNORECASE | re.S,
)
_NEMAN_ADULT_PRICE = re.compile(r"Стоимость билета\s*-?\s*(\d+(?:[.,]\d+)?)\s*р", re.IGNORECASE)
_NEMAN_CHILD_PRICE = re.compile(r"Для детей[^-]*-\s*(\d+(?:[.,]\d+)?)\s*р", re.IGNORECASE)
_NEMAN_RENTAL_PRICE = re.compile(r"Прокат коньков\s*-\s*(\d+(?:[.,]\d+)?)\s*р", re.IGNORECASE)
_NEMAN_TITLE = re.compile(r"<h1>([^<]*)</h1>", re.IGNORECASE)
_NEMAN_POST_LINK = re.compile(r'href="(/news/sobytie/news\d+\.html)"[^>]*>([^<]*)<', re.IGNORECASE)


def _neman_title_needle(config: dict[str, Any]) -> str:
    return str(config.get("title_contains") or "массов").strip().lower()


def _neman_title_matches(html: str, needle: str) -> bool:
    match = _NEMAN_TITLE.search(html)
    title = html_unescape_cell(match.group(1)) if match else strip_tags(html)[:200]
    return needle in title.lower()


def _neman_article_text(html: str) -> str:
    """Body copy only — exclude index chrome and the <span class=\"date\"> header."""
    match = _NEMAN_TITLE.search(html)
    if not match:
        return strip_tags(html)
    start = match.end()
    cost_idx = html.lower().find("стоимость билета", start)
    chunk = html[start : cost_idx if cost_idx > start else start + 12_000]
    return strip_tags(chunk)


def _neman_publication_date(html: str) -> date | None:
    match = _NEMAN_ARTICLE_DATE.search(html)
    if not match:
        return None
    month = _MONTHS_GENITIVE.get(match.group(2).lower())
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def _neman_session_year(pub: date, session_month: int, session_day: int) -> int:
    try:
        candidate = date(pub.year, session_month, session_day)
    except ValueError:
        return pub.year
    if candidate < pub - timedelta(days=14):
        return pub.year + 1
    return pub.year


def _neman_session_label(venue: str, default: str) -> str:
    lowered = venue.lower()
    if "пышк" in lowered or "ур." in lowered:
        return "лёд Пышки"
    if "коммуналь" in lowered:
        return "лед Арена"
    return default


def _neman_parse_time_pairs(times_text: str, duration: int) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for match in re.finditer(
        r"(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})",
        times_text,
    ):
        pairs.append(
            (
                _fmt(int(match.group(1)), int(match.group(2))),
                _fmt(int(match.group(3)), int(match.group(4))),
            )
        )
    if pairs:
        return pairs
    starts = sorted({f"{int(h):02d}:{m}" for h, m in _HHMM.findall(times_text)})
    return [(start, _end_time(start, duration)) for start in starts]


def _neman_slots_from_html(html: str, config: dict[str, Any]) -> list[ExtractedSlot]:
    needle = _neman_title_needle(config)
    if not _neman_title_matches(html, needle):
        return []

    pub = _neman_publication_date(html) or date.today()
    duration = int(config.get("default_duration_minutes") or 60)
    default_label = str(config.get("session_label") or "лёд Пышки")
    text = _neman_article_text(html)
    prices_text = strip_tags(html)

    adult_match = _NEMAN_ADULT_PRICE.search(prices_text)
    child_match = _NEMAN_CHILD_PRICE.search(prices_text)
    rental_match = _NEMAN_RENTAL_PRICE.search(prices_text)
    adult = parse_price_to_minor(adult_match.group(1), already_minor=False) if adult_match else None
    child = parse_price_to_minor(child_match.group(1), already_minor=False) if child_match else None
    rental = parse_price_to_minor(rental_match.group(1), already_minor=False) if rental_match else None

    slots: list[ExtractedSlot] = []
    for match in _NEMAN_SESSION.finditer(text):
        month = _MONTHS_GENITIVE.get(match.group(2).lower())
        if not month:
            continue
        day_num = int(match.group(1))
        year = _neman_session_year(pub, month, day_num)
        try:
            local_date = date(year, month, day_num)
        except ValueError:
            continue
        label = _neman_session_label(match.group("venue"), default_label)
        for start, end in _neman_parse_time_pairs(match.group("times"), duration):
            slots.append(
                ExtractedSlot(
                    local_date=local_date.isoformat(),
                    starts_at_local=start,
                    ends_at_local=end,
                    kind_raw="public_skate",
                    price_adult=adult,
                    price_child=child,
                    price_rental=rental,
                    session_label=label,
                )
            )
    return slots


def _neman_latest_post_url(index_html: str, base_url: str, needle: str) -> str | None:
    for match in _NEMAN_POST_LINK.finditer(index_html):
        href, title = match.group(1), html_unescape_cell(match.group(2))
        if needle in title.lower():
            return urljoin(base_url, href)
    return None


class GrodnoNemanParser(IceParser):
    parser_key = PARSER_KEY_GRODNO_NEMAN

    async def extract(self, job: ParserJob) -> Extraction:
        config = job.config or {}
        needle = _neman_title_needle(config)
        fixture_name = str(config.get("fixture_post_filename") or "news446875.html")
        if config.get("fixture_dir"):
            html = await load_source_text(job, filename=fixture_name, url_keys=("news_url", "url"))
        else:
            index_url = str(config["news_index_url"])
            index_html = await fetch_http_text(index_url)
            post_url = _neman_latest_post_url(index_html, index_url, needle)
            if not post_url:
                return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=index_html, slots=[])
            html = await fetch_http_text(post_url)

        slots = _neman_slots_from_html(html, config)
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)


# ---------------------------------------------------------------------------
# Лида, ЛДС «Лида» (arena 37) — weekly JPG for times (transcribed, not OCR'd
# at runtime), live HTML for prices.
# ---------------------------------------------------------------------------

_LIDA_AMOUNT_RUB = re.compile(r"(\d+(?:[.,]\d+)?)\s*рубл", re.IGNORECASE)
_LIDA_IMG_SRC = re.compile(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)
_LIDA_OCR_DATE_LINE = re.compile(
    rf"(\d{{1,2}})\s+({_NEMAN_MONTHS})\s*[\]|｜}}\s]*\s*([\d:;,\s]+)",
    re.IGNORECASE,
)
_LIDA_WEEKDAY_SCHEDULE: dict[int, list[str]] = {
    0: [],
    1: ["21:15"],
    2: [],
    3: [],
    4: ["13:45", "21:15"],
    5: ["17:00", "19:15", "20:45"],
    6: ["11:00", "17:15", "18:45", "20:15"],
}


def _lida_prices(html: str) -> dict[str, int | None]:
    text = strip_tags(html)
    result: dict[str, int | None] = {"adult": None, "child": None, "rental": None}

    start = text.find("посещение без предоставления коньков")
    if start >= 0:
        end = text.find("прокат коньков:", start)
        segment = text[start : end if end > start else start + 300]
        amounts = _LIDA_AMOUNT_RUB.findall(segment)
        if len(amounts) >= 1:
            result["adult"] = parse_price_to_minor(amounts[0] + " руб.", already_minor=False)
        if len(amounts) >= 2:
            result["child"] = parse_price_to_minor(amounts[1] + " руб.", already_minor=False)

    start2 = text.find("прокат коньков:")
    if start2 >= 0:
        end2 = text.find("посещение с прокатом", start2)
        segment2 = text[start2 : end2 if end2 > start2 else start2 + 200]
        amounts2 = _LIDA_AMOUNT_RUB.findall(segment2)
        if amounts2:
            result["rental"] = parse_price_to_minor(amounts2[0] + " руб.", already_minor=False)

    return result


def _lida_monday_on_or_before(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _lida_infer_year(month: int, ref: date) -> int:
    if month < ref.month - 2:
        return ref.year + 1
    return ref.year


def _lida_image_urls(html: str, base_url: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in _LIDA_IMG_SRC.finditer(html):
        src = match.group(1).strip()
        lowered = src.lower()
        if any(token in lowered for token in ("logo", "bpro.jpg", "ico/")):
            continue
        if not lowered.endswith((".jpg", ".jpeg", ".png")):
            continue
        url = urljoin(base_url, src)
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _lida_ocr_schedule(image_bytes: bytes) -> list[tuple[date, str]]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return []

    img = Image.open(io.BytesIO(image_bytes))
    text = pytesseract.image_to_string(img, lang="rus", config="--psm 6")
    ref = date.today()
    slots: list[tuple[date, str]] = []
    for match in _LIDA_OCR_DATE_LINE.finditer(text):
        month = _MONTHS_GENITIVE.get(match.group(2).lower())
        if not month:
            continue
        day_num = int(match.group(1))
        year = _lida_infer_year(month, ref)
        try:
            local_date = date(year, month, day_num)
        except ValueError:
            continue
        for hour, minute in _HHMM.findall(match.group(3)):
            slots.append((local_date, _fmt(int(hour), int(minute))))
    return slots


async def _lida_load_image_bytes(job: ParserJob, url: str, basename: str) -> bytes:
    fixture_dir = job.config.get("fixture_dir")
    if fixture_dir:
        path = Path(str(fixture_dir)) / basename
        if path.is_file():
            return path.read_bytes()
    return await fetch_http_bytes(url)


def _lida_slots_from_weekday_config(
    job: ParserJob,
    *,
    prices: dict[str, int | None],
    duration: int,
    age_note: str,
) -> list[ExtractedSlot]:
    week_start_raw = job.config.get("week_start")
    if week_start_raw:
        week_start = date.fromisoformat(str(week_start_raw))
    else:
        week_start = _lida_monday_on_or_before(date.today())
    horizon = int(job.config.get("horizon_days") or 7)
    raw_schedule = job.config.get("weekday_schedule")
    schedule: dict[int, list[str]] = (
        {int(k): list(v) for k, v in raw_schedule.items()} if raw_schedule else _LIDA_WEEKDAY_SCHEDULE
    )
    adult, child, rental = prices["adult"], prices["child"], prices["rental"]
    slots: list[ExtractedSlot] = []
    for offset in range(horizon):
        local_date = week_start + timedelta(days=offset)
        for start in schedule.get(local_date.weekday(), []):
            slots.append(
                ExtractedSlot(
                    local_date=local_date.isoformat(),
                    starts_at_local=start,
                    ends_at_local=_end_time(start, duration),
                    kind_raw="public_skate",
                    price_adult=adult,
                    price_child=child,
                    price_rental=rental,
                    age_note=age_note,
                )
            )
    return slots


class LidaLdsParser(IceParser):
    parser_key = PARSER_KEY_LIDA_LDS

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="massovoe-katanie.html", url_keys=("prices_url", "url"))
        duration = int(job.config.get("default_duration_minutes") or 45)
        age_note = str(job.config.get("age_note") or "детский до 16 лет")
        prices = _lida_prices(html)

        if job.config.get("fixture_dir") and job.config.get("week_start"):
            slots = _lida_slots_from_weekday_config(
                job, prices=prices, duration=duration, age_note=age_note
            )
            return Extraction(
                arena_id=job.arena_id,
                parser_key=self.parser_key,
                snapshot=html,
                slots=slots,
                schedule_basis=SCHEDULE_BASIS_PROJECTED,
            )

        base_url = str(job.config.get("prices_url") or "https://hc-lida.by/")
        best: list[tuple[date, str]] = []
        for url in _lida_image_urls(html, base_url):
            basename = urlparse(url).path.rsplit("/", 1)[-1]
            try:
                image_bytes = await _lida_load_image_bytes(job, url, basename)
                parsed = _lida_ocr_schedule(image_bytes)
            except Exception:
                continue
            if len(parsed) > len(best):
                best = parsed

        slots: list[ExtractedSlot] = []
        if best:
            adult, child, rental = prices["adult"], prices["child"], prices["rental"]
            for local_date, start in sorted(set(best)):
                slots.append(
                    ExtractedSlot(
                        local_date=local_date.isoformat(),
                        starts_at_local=start,
                        ends_at_local=_end_time(start, duration),
                        kind_raw="public_skate",
                        price_adult=adult,
                        price_child=child,
                        price_rental=rental,
                        age_note=age_note,
                    )
                )
        basis = SCHEDULE_BASIS_PHOTO if slots else None
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot=html,
            slots=slots,
            schedule_basis=basis,
        )


# ---------------------------------------------------------------------------
# Новополоцк, ЛДС (ХК «Химик») (arena 30) — plain HTML schedules-table + a
# separate free-text price list ("Прейскурант").
# ---------------------------------------------------------------------------

_NOVO_DATE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")
_NOVO_DURATION = re.compile(r"(\d+)\s*минут", re.IGNORECASE)
_NOVO_WEEKDAY_ADULT = re.compile(r"будние дни[^\d]*?(\d+(?:[.,]\d+)?)\s*рубл", re.IGNORECASE | re.S)
_NOVO_WEEKEND_ADULT = re.compile(
    r"выходные и праздничные дни[^\d]*?(\d+(?:[.,]\d+)?)\s*рубл", re.IGNORECASE | re.S
)
_NOVO_RENTAL = re.compile(r"[Сс]тоимость проката коньков[^\d]*?(\d+(?:[.,]\d+)?)\s*рубл", re.IGNORECASE | re.S)


def _novopolotsk_prices(html: str, config: dict[str, Any]) -> dict[str, int | None]:
    text = strip_tags(html)
    weekday = _NOVO_WEEKDAY_ADULT.search(text)
    weekend = _NOVO_WEEKEND_ADULT.search(text)
    rental = _NOVO_RENTAL.search(text)
    return {
        "weekday_adult": (
            parse_price_to_minor(weekday.group(1) + " руб.", already_minor=False)
            if weekday
            else config.get("weekday_adult_minor_fallback")
        ),
        "weekend_adult": (
            parse_price_to_minor(weekend.group(1) + " руб.", already_minor=False)
            if weekend
            else config.get("weekend_adult_minor_fallback")
        ),
        "rental": (
            parse_price_to_minor(rental.group(1) + " руб.", already_minor=False)
            if rental
            else config.get("rental_minor_fallback")
        ),
    }


class NovopolotskLdsParser(IceParser):
    parser_key = PARSER_KEY_NOVOPOLOTSK_LDS

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="mass-skating.html", url_keys=("url",))
        default_duration = int(job.config.get("default_duration_minutes") or 45)
        drop_substrings = [s.lower() for s in job.config.get("drop_place_substrings") or ["тренировочн"]]
        prices = _novopolotsk_prices(html, job.config)
        weekday_adult = prices["weekday_adult"]
        weekend_adult = prices["weekend_adult"]
        rental = prices["rental"]

        slots: list[ExtractedSlot] = []
        for table in parse_tables(html):
            if not table:
                continue
            header = [cell.lower() for cell in table[0]]
            if not any("дата" in cell for cell in header):
                continue
            for row in table[1:]:
                if len(row) < 3:
                    continue
                date_match = _NOVO_DATE.match(row[0].strip())
                if not date_match:
                    continue
                time_match = _HHMM.search(row[1])
                if not time_match:
                    continue
                place = row[3] if len(row) > 3 else ""
                if any(token in place.lower() for token in drop_substrings):
                    continue
                duration_match = _NOVO_DURATION.search(row[2])
                duration = int(duration_match.group(1)) if duration_match else default_duration
                local_date = date(int(date_match.group(3)), int(date_match.group(2)), int(date_match.group(1)))
                weekend = local_date.weekday() >= 5
                adult = weekend_adult if weekend else weekday_adult
                start = _fmt(int(time_match.group(1)), int(time_match.group(2)))
                slots.append(
                    ExtractedSlot(
                        local_date=local_date.isoformat(),
                        starts_at_local=start,
                        ends_at_local=_end_time(start, duration),
                        kind_raw="public_skate",
                        price_adult=adult,
                        price_child=None,
                        price_rental=rental,
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)
