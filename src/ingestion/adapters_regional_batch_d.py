"""Regional batch D IceParser strategies (arenas 38/19/42/33). Extract only — no DB writes.

Follows the style of ``src/ingestion/adapters.py``. Sources and gotchas: ``.ai/parsers/*.md``.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

import aiohttp

from src.ingestion.htmlutil import html_unescape_cell, parse_tables
from src.ingestion.normalize import parse_price_to_minor
from src.ingestion.parsers import IceParser
from src.ingestion.seed_config_regional_batch_d import (
    PARSER_KEY_BOBRUISK_ARENA,
    PARSER_KEY_GOMEL_LDS,
    PARSER_KEY_SHKLOV_ARENA,
    PARSER_KEY_SOLIGORSK_SZK,
)
from src.ingestion.source_io import fetch_http_text, load_source_text
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob

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

_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.I)
_TIME_RANGE_DOT = re.compile(r"(\d{1,2})[.:](\d{2})\s*-\s*(\d{1,2})[.:](\d{2})")
_DATE_IN_TEXT = re.compile(
    r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)",
    re.I,
)


def _fmt(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _unescape(text: str) -> str:
    return (
        text.replace("&nbsp;", " ")
        .replace("&ndash;", "–")
        .replace("&mdash;", "—")
        .replace("&laquo;", "«")
        .replace("&raquo;", "»")
        .replace("&amp;", "&")
    )


def _detag_join(raw: str) -> str:
    """Strip tags without inserting spaces at tag boundaries (glued <strong> spans)."""
    text = _TAG.sub("", raw)
    text = _unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _detag_lines(fragment: str) -> list[str]:
    """<br> becomes a line break; everything else collapses. Drops blank lines."""
    text = _BR.sub("\n", fragment)
    text = _TAG.sub("", text)
    text = _unescape(text)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]
    return [ln for ln in lines if ln]


async def _fetch_bytes(url: str) -> bytes:
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers={"User-Agent": "trainer-crm-ice-ingest/1.0"}) as response:
            response.raise_for_status()
            return await response.read()


# --------------------------------------------------------------------------
# Бобруйск-арена (arena_id 38)
# --------------------------------------------------------------------------

_P = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
_TWO_DECIMALS = re.compile(r"(\d+[.,]\d+)")


def _bobruisk_lang_ru_fragment(html: str) -> str:
    start = html.find('class="col-lg-8 col-md-8 lang_ru"')
    if start < 0:
        return html
    start = html.find(">", start) + 1
    end = html.find('class="col-lg-8 col-md-8 lang_by"', start)
    return html[start:end] if end > start else html[start:]


def _bobruisk_schedule_slots(html: str, *, year: int) -> list[tuple[date, str, str]]:
    fragment = _bobruisk_lang_ru_fragment(html)
    paragraphs = [_detag_join(m.group(1)) for m in _P.finditer(fragment)]

    blocks: list[list[str]] = []
    current: list[str] = []
    for text in paragraphs:
        if not text:
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(text)
    if current:
        blocks.append(current)

    results: list[tuple[date, str, str]] = []
    current_date: date | None = None
    for block in blocks:
        first = block[0]
        date_match = _DATE_IN_TEXT.search(first)
        if date_match and not _TIME_RANGE_DOT.search(first):
            month = _MONTHS[date_match.group(2).lower()]
            current_date = date(year, month, int(date_match.group(1)))
            lines = block[1:]
        else:
            # No header paragraph: closed day rolled into the next calendar day (SPEC gotcha).
            if current_date is None:
                continue
            current_date = current_date + timedelta(days=1)
            lines = block
        for line in lines:
            if "массовое катание" not in line.lower():
                continue
            tm = _TIME_RANGE_DOT.search(line)
            if not tm:
                continue
            start = _fmt(int(tm.group(1)), int(tm.group(2)))
            end = _fmt(int(tm.group(3)), int(tm.group(4)))
            results.append((current_date, start, end))
    return results


def _bobruisk_prices(html: str) -> tuple[int | None, int | None, int | None, int | None]:
    weekday_adult = weekend_adult = weekday_rental = weekend_rental = None
    for table in parse_tables(html):
        for row in table:
            if len(row) < 3:
                continue
            label = row[0].lower()
            if "дискотек" in label:
                continue  # different product/price, not the plain MK row (SPEC: none on this snapshot)
            if "массов" in label and "будни" in label:
                weekday_adult = parse_price_to_minor(row[-1], already_minor=False)
            elif "массов" in label and "выходны" in label:
                weekend_adult = parse_price_to_minor(row[-1], already_minor=False)
            elif "прокат коньков" in label:
                nums = _TWO_DECIMALS.findall(row[-1])
                if len(nums) >= 2:
                    weekday_rental = parse_price_to_minor(nums[0], already_minor=False)
                    weekend_rental = parse_price_to_minor(nums[1], already_minor=False)
    return weekday_adult, weekend_adult, weekday_rental, weekend_rental


class BobruiskArenaParser(IceParser):
    parser_key = PARSER_KEY_BOBRUISK_ARENA

    async def extract(self, job: ParserJob) -> Extraction:
        schedule_html = await load_source_text(job, filename="raspisanie.html", url_keys=("schedule_url",))
        prices_html = await load_source_text(job, filename="massovye-kataniya.html", url_keys=("prices_url",))
        year = int(job.config.get("run_year") or date.today().year)
        weekday_adult, weekend_adult, weekday_rental, weekend_rental = _bobruisk_prices(prices_html)
        slots: list[ExtractedSlot] = []
        for local_date, start, end in _bobruisk_schedule_slots(schedule_html, year=year):
            weekend = local_date.weekday() >= 5
            slots.append(
                ExtractedSlot(
                    local_date=local_date.isoformat(),
                    starts_at_local=start,
                    ends_at_local=end,
                    kind_raw="Массовое катание",
                    price_adult=weekend_adult if weekend else weekday_adult,
                    price_child=None,
                    price_rental=weekend_rental if weekend else weekday_rental,
                )
            )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"schedule": schedule_html, "prices": prices_html},
            slots=slots,
        )


# --------------------------------------------------------------------------
# СЗК Солигорск (arena_id 19)
# --------------------------------------------------------------------------

_H3 = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
_DAY_LINE_DASH = re.compile(
    r"^(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
    r"\s*-\s*(.+)$",
    re.I,
)


def _soligorsk_prices(html: str) -> tuple[int | None, int | None, int | None]:
    idx = html.find("Стоимость билетов")
    chunk = html[idx : idx + 1500] if idx >= 0 else html
    text = _detag_join(chunk)
    adult = child = rental = None
    m = re.search(r"Взрослый билет\s*-\s*([\d,]+)", text)
    if m:
        adult = parse_price_to_minor(m.group(1), already_minor=False)
    m = re.search(r"Детский\s*\(до 16 лет\)[^,]*,\s*пенсионный\s*-\s*([\d,]+)", text)
    if m:
        child = parse_price_to_minor(m.group(1), already_minor=False)
    m = re.search(r"Прокат коньков \(1 пара\)\s*-\s*([\d,]+)", text)
    if m:
        rental = parse_price_to_minor(m.group(1), already_minor=False)
    return adult, child, rental


class SoligorskSzkParser(IceParser):
    parser_key = PARSER_KEY_SOLIGORSK_SZK

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="massovoe-katanie.html", url_keys=("url",))
        year = int(job.config.get("run_year") or date.today().year)
        adult, child, rental = _soligorsk_prices(html)
        start_idx = html.upper().find("РАСПИСАНИЕ МАССОВЫХ КАТАНИЙ")
        end_idx = html.find("Продолжительность", start_idx) if start_idx >= 0 else -1
        region = html[start_idx:end_idx] if start_idx >= 0 and end_idx > start_idx else html
        slots: list[ExtractedSlot] = []
        for block in _H3.finditer(region):
            text = _detag_join(block.group(1))
            m = _DAY_LINE_DASH.match(text)
            if not m:
                continue
            month = _MONTHS.get(m.group(2).lower())
            if month is None:
                continue
            local_date = date(year, month, int(m.group(1)))
            for seg in m.group(3).split(";"):
                tm = _TIME_RANGE_DOT.search(seg)
                if not tm:
                    continue
                start = _fmt(int(tm.group(1)), int(tm.group(2)))
                end = _fmt(int(tm.group(3)), int(tm.group(4)))
                label = "Рок-хиты" if "рок-хиты" in seg.lower() else None
                slots.append(
                    ExtractedSlot(
                        local_date=local_date.isoformat(),
                        starts_at_local=start,
                        ends_at_local=end,
                        kind_raw="Массовое катание",
                        price_adult=adult,
                        price_child=child,
                        price_rental=rental,
                        session_label=label,
                        age_note="детский до 16 лет",
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)


# --------------------------------------------------------------------------
# Шклов Ледовая арена (arena_id 42) — weekly poster, OCR'd (rus tesseract CLI)
# --------------------------------------------------------------------------

_ENTRY_TITLE_LINK = re.compile(r'<h2 class="entry-title"><a href="([^"]+)"[^>]*>([^<]*)</a></h2>', re.S)
_IMG_FULL = re.compile(r'<img[^>]+class="[^"]*size-full[^"]*"[^>]+src="([^"]+\.jpg)"', re.I)
_WEEK_FILENAME = re.compile(r"(\d{2})\.(\d{2})-(\d{2})\.(\d{2})\.(\d{4})")
_HEADER_DAY = re.compile(r"^\d{1,2}$")
_OCR_TIME_TOKEN = re.compile(r"^(\d{1,2})[.:](\d{2})-(\d{1,2})[.:](\d{2})$")


def _shklov_find_latest_post(index_html: str, title_contains: str) -> str | None:
    for href, title in _ENTRY_TITLE_LINK.findall(index_html):
        if title_contains.lower() in html_unescape_cell(title).lower():
            return href
    return None


def _shklov_find_image_url(post_html: str) -> str | None:
    m = _IMG_FULL.search(post_html)
    return m.group(1) if m else None


async def _load_shklov_photo(job: ParserJob) -> tuple[bytes, str]:
    fixture_dir = job.config.get("fixture_dir")
    if fixture_dir:
        filename = str(job.config.get("photo_filename") or "31.08-06.09.2026.jpg")
        return (Path(fixture_dir) / filename).read_bytes(), filename
    index_html = await fetch_http_text(str(job.config["index_url"]))
    href = _shklov_find_latest_post(index_html, str(job.config.get("title_contains") or "массового катания"))
    if not href:
        raise RuntimeError("Шклов: свежий пост с расписанием не найден в /category/raspisania/")
    post_url = href if href.startswith("http") else "http://sportshklov.by" + href
    post_html = await fetch_http_text(post_url)
    image_url = _shklov_find_image_url(post_html)
    if not image_url:
        raise RuntimeError("Шклов: фото расписания не найдено в посте")
    filename = image_url.rsplit("/", 1)[-1]
    return await _fetch_bytes(image_url), filename


def _shklov_month_year(filename: str) -> tuple[int, int]:
    m = _WEEK_FILENAME.search(filename)
    if not m:
        today = date.today()
        return today.month, today.year
    end_month = int(m.group(4))
    year = int(m.group(5))
    return end_month, year


def _run_tesseract_tsv(image_bytes: bytes) -> str:
    proc = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", "rus", "--psm", "6", "tsv"],
        input=image_bytes,
        capture_output=True,
        check=True,
    )
    return proc.stdout.decode("utf-8", errors="replace")


async def _ocr_tsv(image_bytes: bytes) -> str:
    return await asyncio.to_thread(_run_tesseract_tsv, image_bytes)


def _shklov_parse_grid(tsv_text: str) -> list[tuple[int, str, str]]:
    """(day_of_month, start, end) using column x-position of tesseract TSV word tokens."""
    tokens: list[tuple[int, int, int, str]] = []
    lines = tsv_text.splitlines()
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        if cols[0] != "5":
            continue
        text = cols[11].strip()
        if not text:
            continue
        try:
            left = int(cols[6])
            top = int(cols[7])
            width = int(cols[8])
        except ValueError:
            continue
        tokens.append((left, top, width, text))

    headers = sorted(
        ((left + width / 2, int(text)) for left, top, width, text in tokens if _HEADER_DAY.fullmatch(text)),
        key=lambda item: item[0],
    )
    if not headers:
        return []
    centers = [c for c, _ in headers]
    days = [d for _, d in headers]

    sessions: list[tuple[int, str, str]] = []
    for left, _top, width, text in tokens:
        tm = _OCR_TIME_TOKEN.match(text)
        if not tm:
            continue
        center = left + width / 2
        idx = min(range(len(centers)), key=lambda i: abs(centers[i] - center))
        day_num = days[idx]
        start = _fmt(int(tm.group(1)), int(tm.group(2)))
        end = _fmt(int(tm.group(3)), int(tm.group(4)))
        sessions.append((day_num, start, end))
    return sessions


def _shklov_prices(html: str) -> tuple[int | None, int | None, int | None]:
    adult = child = rental_adult = None
    section: str | None = None
    for table in parse_tables(html):
        for row in table:
            if not row:
                continue
            if len(row) == 1:
                joined = row[0].upper()
                if "МАССОВОЕ КАТАНИЕ" in joined and "ВЗРОСЛ" in joined:
                    section = "adult"
                elif "МАССОВОЕ КАТАНИЕ" in joined and "ДЕТ" in joined:
                    section = "child"
                elif "ПРОКАТ" in joined:
                    section = "rental"
                continue
            if len(row) < 4:
                continue
            label = row[1].strip().upper()
            price = row[3]
            if section == "adult" and adult is None and label == "ДЛЯ ВЗРОСЛЫХ":
                adult = parse_price_to_minor(price, already_minor=False)
            elif section == "child" and child is None and "ДЛЯ ДЕТЕЙ ДО 14" in label:
                child = parse_price_to_minor(price, already_minor=False)
            elif section == "rental" and rental_adult is None and label == "ДЛЯ ВЗРОСЛЫХ":
                rental_adult = parse_price_to_minor(price, already_minor=False)
    return adult, child, rental_adult


class ShklovArenaParser(IceParser):
    parser_key = PARSER_KEY_SHKLOV_ARENA

    async def extract(self, job: ParserJob) -> Extraction:
        image_bytes, filename = await _load_shklov_photo(job)
        prices_html = await load_source_text(job, filename="uslugi.html", url_keys=("prices_url",))
        month, year = _shklov_month_year(filename)
        adult, child, rental = _shklov_prices(prices_html)
        tsv_text = await _ocr_tsv(image_bytes)
        age_note = "детский до 14 лет; прокат дет. 4.10, в каноне взр. 4.20"
        slots: list[ExtractedSlot] = []
        for day_num, start, end in _shklov_parse_grid(tsv_text):
            slots.append(
                ExtractedSlot(
                    local_date=date(year, month, day_num).isoformat(),
                    starts_at_local=start,
                    ends_at_local=end,
                    kind_raw="Массовое катание",
                    price_adult=adult,
                    price_child=child,
                    price_rental=rental,
                    age_note=age_note,
                )
            )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"photo_filename": filename, "prices": prices_html, "ocr_tsv": tsv_text},
            slots=slots,
        )


# --------------------------------------------------------------------------
# Гомельский ЛДС (arena_id 33) — weekly news post
# --------------------------------------------------------------------------

_NEWS_ITEM = re.compile(
    r'<div class="title"><a href="([^"]+)">([^<]*)</a></div>.*?'
    r'<div class="date"><i class="i-clock-gray"[^>]*></i>\s*(\d{1,2})\s+([а-яё]+)\'(\d{2})',
    re.S | re.I,
)
_PUBLISHED_DATE = re.compile(r"i-clock-gray[^>]*></i>\s*(\d{1,2})\s+([а-яё]+)\s+(\d{4})", re.I)
_PUBLISHED_DATE_SHORT = re.compile(r"i-clock-gray[^>]*></i>\s*(\d{1,2})\s+([а-яё]+)'(\d{2})", re.I)
_GOMEL_DAY_LINE = re.compile(
    r"^(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
    r"\s*\(([^)]*)\)\s*:\s*(.+)$",
    re.I,
)
_TIME_COLON = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def _gomel_find_latest_post(index_html: str, title_contains: str) -> str | None:
    best: tuple[date, str] | None = None
    for href, title, day_s, month_name, year2 in _NEWS_ITEM.findall(index_html):
        if title_contains.lower() not in html_unescape_cell(title).lower():
            continue
        month = _MONTHS.get(month_name.lower())
        if month is None:
            continue
        found_date = date(2000 + int(year2), month, int(day_s))
        if best is None or found_date > best[0]:
            best = (found_date, href)
    return best[1] if best else None


async def _load_gomel_post_html(job: ParserJob) -> str:
    fixture_dir = job.config.get("fixture_dir")
    if fixture_dir:
        filename = str(job.config.get("post_filename") or "news445332.html")
        return (Path(fixture_dir) / filename).read_text(encoding="utf-8")
    index_html = await fetch_http_text(str(job.config["news_index_url"]))
    href = _gomel_find_latest_post(
        index_html, str(job.config.get("title_contains") or "Расписание массовых катаний")
    )
    if not href:
        raise RuntimeError("Гомель: свежий пост «Расписание массовых катаний» не найден в ленте")
    post_url = href if href.startswith("http") else "https://gomel.hockey.by" + href
    return await fetch_http_text(post_url)


def _gomel_publish_year(html: str) -> int | None:
    m = _PUBLISHED_DATE.search(html)
    if m:
        return int(m.group(3))
    m = _PUBLISHED_DATE_SHORT.search(html)
    return 2000 + int(m.group(3)) if m else None


def _gomel_schedule_region_lines(html: str) -> list[str]:
    start = html.find("Расписание массовых катаний")
    end = html.find("Справки по телефонам", start)
    region = html[start:end] if start >= 0 and end > start else html[start : start + 3000]
    return _detag_lines(region)


def _gomel_parse_lines(lines: list[str], *, year: int) -> list[tuple[date, str, str]]:
    slots: list[tuple[date, str, str]] = []
    for line in lines:
        m = _GOMEL_DAY_LINE.match(line)
        if not m:
            continue
        month = _MONTHS.get(m.group(2).lower())
        if month is None:
            continue
        local_date = date(year, month, int(m.group(1)))
        rest = m.group(4).rstrip(". ")
        for seg in rest.split(","):
            tm = _TIME_COLON.search(seg)
            if not tm:
                continue
            start_s = _fmt(int(tm.group(1)), int(tm.group(2)))
            end_s = _fmt(int(tm.group(3)), int(tm.group(4)))
            slots.append((local_date, start_s, end_s))
    return slots


def _gomel_prices(lines: list[str]) -> tuple[int | None, int | None, int | None]:
    joined = " ".join(lines)
    weekday_adult = weekend_adult = rental = None
    m = re.search(r"пн-чт\s*-\s*(\d+)\s*рубл", joined, re.I)
    if m:
        weekday_adult = parse_price_to_minor(m.group(1), already_minor=False)
    m = re.search(r"пт-вс\s*-\s*(\d+)\s*рубл", joined, re.I)
    if m:
        weekend_adult = parse_price_to_minor(m.group(1), already_minor=False)
    m = re.search(r"Прокат коньков:\s*(\d+)\s*рубл", joined, re.I)
    if m:
        rental = parse_price_to_minor(m.group(1), already_minor=False)
    return weekday_adult, weekend_adult, rental


class GomelLdsParser(IceParser):
    parser_key = PARSER_KEY_GOMEL_LDS

    async def extract(self, job: ParserJob) -> Extraction:
        html = await _load_gomel_post_html(job)
        year = _gomel_publish_year(html) or int(job.config.get("run_year") or date.today().year)
        lines = _gomel_schedule_region_lines(html)
        weekday_adult, weekend_adult, rental = _gomel_prices(lines)
        age_note = "детям до 10 лет вход после 21:00 запрещен"
        slots: list[ExtractedSlot] = []
        for local_date, start_s, end_s in _gomel_parse_lines(lines, year=year):
            weekend = local_date.weekday() >= 4  # site buckets пт-вс (Fri-Sun) as "weekend" price
            slots.append(
                ExtractedSlot(
                    local_date=local_date.isoformat(),
                    starts_at_local=start_s,
                    ends_at_local=end_s,
                    kind_raw="Массовое катание",
                    price_adult=weekend_adult if weekend else weekday_adult,
                    price_child=None,
                    price_rental=rental,
                    age_note=age_note,
                )
            )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)
