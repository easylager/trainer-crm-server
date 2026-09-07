"""Batch C regional IceParser strategies. Extract only — persistence is elsewhere.

Arenas: vitebsk-ds (29), mogilev-ds (43), orsha-arena (31), gorki-lds (32),
ostrovets-lds (41). See .ai/parsers/<slug>.md for the reverse-engineering notes
this module implements, and .ai/data/fixtures/<slug>/ for fixtures + hand
extracted ground truth (expected.json).

New file only — does not modify src/ingestion/adapters.py, parsers.py, or
seed_config.py. A later integration step wires these classes into
ParserRegistry / default_registry().
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp

from src.ingestion.htmlutil import parse_tables, price_from_label, strip_tags
from src.ingestion.normalize import parse_price_to_minor
from src.ingestion.parsers import IceParser
from src.ingestion.seed_config_regional_batch_c import (
    PARSER_KEY_GORKI_LDS,
    PARSER_KEY_MOGILEV_DS,
    PARSER_KEY_ORSHA_ARENA,
    PARSER_KEY_OSTROVETS_LDS,
    PARSER_KEY_VITEBSK_DS,
)
from src.ingestion.source_io import load_source_text
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
    "сентяьря": 9,  # snapshot CMS typo (missing б) — see ostrovets-lds.md
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

_WEEKDAYS_RU = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)

_USER_AGENT = "trainer-crm-ice-ingest/1.0"

_RUB_KOP = re.compile(r"(\d+)\s*руб\.?\s*(\d+)\s*коп", re.IGNORECASE)


def _price_minor(text: str) -> int | None:
    """Parse '7 руб. 00 коп.' word-format prices; falls back to parse_price_to_minor.

    ``parse_price_to_minor`` treats any string containing 'коп' as already a
    minor-unit value (its single-field-per-price convention), which mis-parses
    this site family's two-field 'N руб. M коп.' price cells. Extract rubles
    and kopecks explicitly here instead.
    """
    match = _RUB_KOP.search(text)
    if match:
        return int(match.group(1)) * 100 + int(match.group(2))
    return parse_price_to_minor(text, already_minor=False)


def _fmt(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _add_minutes(start: str, minutes: int) -> str:
    hour, minute = (int(part) for part in start.split(":"))
    end_dt = datetime(2000, 1, 1, hour, minute) + timedelta(minutes=minutes)
    return _fmt(end_dt.hour, end_dt.minute)


async def _load_bytes(job: ParserJob, *, filename: str, url: str) -> bytes:
    """Fixture bytes when fixture_dir is set; otherwise a live HTTP GET."""
    fixture_dir = job.config.get("fixture_dir")
    if fixture_dir:
        return (Path(str(fixture_dir)) / filename).read_bytes()
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers={"User-Agent": _USER_AGENT}) as response:
            response.raise_for_status()
            return await response.read()


# ---------------------------------------------------------------------------
# vitebsk-ds (arena_id 29) — hockey.by HTML weekday blocks.
# ---------------------------------------------------------------------------

_VITEBSK_DAY_BLOCK = re.compile(
    r"(?P<day>Понедельник|Вторник|Среда|Четверг|Пятница|Суббота|Воскресенье)"
    r"\s+(?P<dnum>\d{1,2})\s+(?P<month>[А-Яа-яЁё]+)\s*-\s*"
    r"(?P<times>[\d:.,\s]+?)"
    r"(?=(?:Понедельник|Вторник|Среда|Четверг|Пятница|Суббота|Воскресенье)|На поздние|$)"
)
_HHMM_LOOSE = re.compile(r"^(\d+)[:.](\d{2})$")


def _fix_typo_time(raw: str, typo_map: dict[str, str]) -> str:
    raw = raw.strip()
    if raw in typo_map:
        return typo_map[raw]
    match = _HHMM_LOOSE.match(raw)
    if not match:
        return raw
    hour_str, minute = match.groups()
    hour = int(hour_str)
    if hour > 23 and hour_str.startswith("20"):
        hour = 20
    return _fmt(hour, int(minute))


def _guess_year(day: int, month: int, weekday_name: str, anchor_year: int) -> int:
    """Pick the year (near anchor_year) whose real weekday matches the label.

    The source's weekday blocks carry no year; SPEC confirms the snapshot is
    2026 because 30 Apr 2026 really is a Thursday. Search a small window
    around the configured anchor year instead of hardcoding it.
    """
    target_idx = _WEEKDAYS_RU.index(weekday_name)
    for candidate in (anchor_year, anchor_year + 1, anchor_year - 1):
        try:
            if date(candidate, month, day).weekday() == target_idx:
                return candidate
        except ValueError:
            continue
    return anchor_year


class VitebskDsParser(IceParser):
    parser_key = PARSER_KEY_VITEBSK_DS

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="massovoe-katanie.html", url_keys=("url",))
        text = strip_tags(html)
        anchor_year = int(job.config.get("run_year") or date.today().year)
        duration = int(job.config.get("default_duration_minutes") or 60)
        typo_map = dict(job.config.get("typo_times") or {})
        adult_marker = str(job.config.get("adult_price_marker") or "Стоимость билета")
        age_note = job.config.get("age_note")
        adult = price_from_label(text, adult_marker, already_minor=False)

        slots: list[ExtractedSlot] = []
        for match in _VITEBSK_DAY_BLOCK.finditer(text):
            month = _MONTHS.get(match.group("month").lower())
            if not month:
                continue
            day_num = int(match.group("dnum"))
            year = _guess_year(day_num, month, match.group("day"), anchor_year)
            try:
                local_date = date(year, month, day_num)
            except ValueError:
                continue
            for raw_time in match.group("times").split(","):
                raw_time = raw_time.strip()
                if not raw_time:
                    continue
                start = _fix_typo_time(raw_time, typo_map)
                if not _HHMM_LOOSE.match(start):
                    continue
                end = _add_minutes(start, duration)
                slots.append(
                    ExtractedSlot(
                        local_date=local_date.isoformat(),
                        starts_at_local=start,
                        ends_at_local=end,
                        kind_raw="Массовое катание",
                        price_adult=adult,
                        price_child=None,
                        price_rental=None,
                        session_label=None,
                        age_note=age_note,
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)


# ---------------------------------------------------------------------------
# mogilev-ds (arena_id 43) — hockey.by raspisanie table, mixed with СДЮШОР/ХК.
# ---------------------------------------------------------------------------

_MOGILEV_DATE_HEADER = re.compile(
    r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|"
    r"октября|ноября|декабря)\s+(\d{4})",
    re.IGNORECASE,
)
_TIME_RANGE_DOT = re.compile(r"(\d{1,2})[.:](\d{2})\s*[-–—]+\s*(\d{1,2})[.:](\d{2})")


class MogilevDsParser(IceParser):
    parser_key = PARSER_KEY_MOGILEV_DS

    async def extract(self, job: ParserJob) -> Extraction:
        schedule = await load_source_text(job, filename="raspisanie.html", url_keys=("schedule_url",))
        prices_html = await load_source_text(job, filename="uslugi.html", url_keys=("prices_url",))
        keep_substring = str(job.config.get("kind_keep_substring") or "массовое катание").lower()
        age_note = job.config.get("age_note")
        adult, child, rental = _mogilev_prices(prices_html)

        slots: list[ExtractedSlot] = []
        current_date: date | None = None
        # parse_tables returns one giant table (rowspan day headers as 1-cell rows).
        tables = parse_tables(schedule)
        for table in tables:
            for row in table:
                if len(row) == 1:
                    header_match = _MOGILEV_DATE_HEADER.search(row[0])
                    if header_match:
                        day_num = int(header_match.group(1))
                        month = _MONTHS.get(header_match.group(2).lower())
                        year = int(header_match.group(3))
                        if month:
                            try:
                                current_date = date(year, month, day_num)
                            except ValueError:
                                current_date = None
                    continue
                if current_date is None or len(row) < 2:
                    continue
                label = row[-1].strip().lower()
                if keep_substring not in label:
                    continue
                time_match = _TIME_RANGE_DOT.search(row[0])
                if not time_match:
                    continue
                start = _fmt(int(time_match.group(1)), int(time_match.group(2)))
                end = _fmt(int(time_match.group(3)), int(time_match.group(4)))
                slots.append(
                    ExtractedSlot(
                        local_date=current_date.isoformat(),
                        starts_at_local=start,
                        ends_at_local=end,
                        kind_raw="Массовое катание",
                        price_adult=adult,
                        price_child=child,
                        price_rental=rental,
                        session_label=None,
                        age_note=age_note,
                    )
                )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"raspisanie": schedule, "uslugi": prices_html},
            slots=slots,
        )


def _mogilev_prices(html: str) -> tuple[int | None, int | None, int | None]:
    adult = child = rental = None
    for table in parse_tables(html):
        for row in table:
            if len(row) < 2:
                continue
            label = row[0].strip().upper()
            if label.startswith("МАССОВОЕ КАТАНИЕ"):
                amounts = re.findall(r"(\d+[.,]\d{2})\s*руб", row[1])
                if len(amounts) >= 1:
                    adult = parse_price_to_minor(amounts[0] + " руб.", already_minor=False)
                if len(amounts) >= 2:
                    child = parse_price_to_minor(amounts[1] + " руб.", already_minor=False)
            elif "ПРЕДОСТАВЛЕНИЯ КОНЬКОВ" in label:
                amounts = re.findall(r"(\d+[.,]\d{2})\s*руб", row[1])
                if amounts:
                    rental = parse_price_to_minor(amounts[0] + " руб.", already_minor=False)
    return adult, child, rental


# ---------------------------------------------------------------------------
# orsha-arena (arena_id 31) — OCR of a weekly ice-schedule JPG (no HTML grid).
#
# NOTE: this parser requires `pytesseract` (not currently in requirements.txt)
# plus the system `tesseract` binary with the `rus` language pack installed
# on the worker host (`brew install tesseract tesseract-lang` on macOS,
# `apt-get install tesseract-ocr tesseract-ocr-rus` on Debian/Ubuntu). Both
# were added to *this* dev sandbox to build and test the adapter, but neither
# is declared in project requirements — that must happen before this class is
# wired into the scheduler registry, otherwise `extract()` raises at runtime.
# ---------------------------------------------------------------------------

_IMG_TAG = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", re.IGNORECASE)
_HEADER_DATE_TOKEN = re.compile(r"^\d{2}\.\d{2}$")
_CELL_TIME_RANGE = re.compile(r"(\d{1,2})[.:](\d{2})\s*[-–—]+\s*(\d{1,2})[.:](\d{2})")


def _orsha_candidate_images(html: str, base_url: str, config: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (basename, absolute_url) pairs for Ld-*.jpg images, doc order."""
    keep_prefix = str(config.get("image_keep_prefix") or "Ld-")
    drop_prefixes = tuple(config.get("image_drop_prefixes") or ("OL-", "Ol-"))
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _IMG_TAG.finditer(html):
        src = match.group(1)
        basename = urlparse(src).path.rsplit("/", 1)[-1]
        if not basename.lower().endswith(".jpg"):
            continue
        if any(basename.startswith(p) for p in drop_prefixes):
            continue
        if not basename.startswith(keep_prefix):
            continue
        if "-768x" in basename or "-300x" in basename or "-150x" in basename:
            continue  # WP thumbnail variant, not the full image
        if basename in seen:
            continue
        seen.add(basename)
        out.append((basename, urljoin(base_url, src)))
    return out


def _yellow_mask_components(img: Any, *, min_w: int = 60, min_h: int = 30) -> list[tuple[int, int, int, int]]:
    """Connected components of yellow-highlighted cells, via run merging.

    No numpy/opencv available; Pillow point()+ImageChops build a binary mask
    fast (C-level), then a simple row-run vertical-merge stands in for
    connected-component labeling — good enough for a handful of blocky,
    well-separated highlighted cells in a printed timetable graphic.
    """
    from PIL import ImageChops

    w, h = img.size
    r, g, b = img.split()
    r_mask = r.point(lambda p: 255 if p > 170 else 0)
    g_mask = g.point(lambda p: 255 if p > 170 else 0)
    b_mask = b.point(lambda p: 255 if p < 110 else 0)
    mask = ImageChops.multiply(ImageChops.multiply(r_mask, g_mask), b_mask)
    px = mask.load()

    active: list[dict[str, int]] = []
    finished: list[dict[str, int]] = []
    for y in range(h):
        runs: list[tuple[int, int]] = []
        x = 0
        while x < w:
            if px[x, y] == 255:
                x0 = x
                while x < w and px[x, y] == 255:
                    x += 1
                if x - x0 >= 15:
                    runs.append((x0, x))
            else:
                x += 1
        matched = [False] * len(runs)
        new_active: list[dict[str, int]] = []
        for comp in active:
            best = None
            for i, (x0, x1) in enumerate(runs):
                if matched[i]:
                    continue
                if x0 < comp["x1"] and x1 > comp["x0"]:
                    best = i
                    break
            if best is not None:
                x0, x1 = runs[best]
                comp["x0"] = min(comp["x0"], x0)
                comp["x1"] = max(comp["x1"], x1)
                comp["y1"] = y
                matched[best] = True
                new_active.append(comp)
            else:
                finished.append(comp)
        for i, (x0, x1) in enumerate(runs):
            if not matched[i]:
                new_active.append({"x0": x0, "x1": x1, "y0": y, "y1": y})
        active = new_active
    finished.extend(active)
    return [
        (c["x0"], c["y0"], c["x1"], c["y1"])
        for c in finished
        if (c["x1"] - c["x0"]) >= min_w and (c["y1"] - c["y0"]) >= min_h
    ]


def _orsha_header_columns(img: Any) -> list[tuple[int, str]]:
    """(x_center, 'DD.MM') for each day column header, sorted left→right."""
    import pytesseract
    from pytesseract import Output

    data = pytesseract.image_to_data(img, lang="rus", output_type=Output.DICT)
    hits: list[tuple[int, int, str]] = []
    for i, text in enumerate(data["text"]):
        token = text.strip()
        if _HEADER_DATE_TOKEN.match(token):
            hits.append((data["top"][i], data["left"][i] + data["width"][i] // 2, token))
    if not hits:
        return []
    hits.sort()
    band_top = hits[0][0]
    row = [(x, token) for top, x, token in hits if abs(top - band_top) <= 10]
    row.sort()
    return row


def _ocr_box_text(img: Any, box: tuple[int, int, int, int]) -> str:
    import pytesseract

    x0, y0, x1, y1 = box
    pad = 6
    crop = img.crop((max(0, x0 - pad), max(0, y0 - pad), x1 + pad, y1 + pad))
    crop = crop.resize((crop.width * 3, crop.height * 3))
    return pytesseract.image_to_string(crop, lang="rus", config="--psm 6").strip()


def _orsha_extract_from_image(image_bytes: bytes, config: dict[str, Any]) -> tuple[date | None, list[dict[str, Any]]]:
    """Returns (week_start_date, raw_cell_dicts) for one Ld-*.jpg schedule photo."""
    from PIL import Image

    img = Image.open(__import__("io").BytesIO(image_bytes)).convert("RGB")
    columns = _orsha_header_columns(img)
    if not columns:
        return None, []
    year = int(config.get("run_year") or date.today().year)
    col_dates: list[tuple[int, date]] = []
    for x_center, token in columns:
        day_str, month_str = token.split(".")
        month = int(month_str)
        day = int(day_str)
        # Month can roll backwards at a month boundary (e.g. "31.08" before "01.09").
        col_year = year
        if col_dates and month < col_dates[-1][1].month and col_dates[-1][1].month == 12:
            col_year = year + 1
        try:
            col_dates.append((x_center, date(col_year, month, day)))
        except ValueError:
            continue
    if not col_dates:
        return None, []
    week_start = min(d for _, d in col_dates)

    boxes = _yellow_mask_components(img)
    cells: list[dict[str, Any]] = []
    for box in boxes:
        text = _ocr_box_text(img, box)
        if "массов" not in text.lower():
            continue
        time_match = _CELL_TIME_RANGE.search(text.replace("\n", " "))
        if not time_match:
            continue
        box_x_center = (box[0] + box[2]) / 2
        nearest_date = min(col_dates, key=lambda pair: abs(pair[0] - box_x_center))[1]
        cells.append(
            {
                "local_date": nearest_date,
                "starts_at_local": _fmt(int(time_match.group(1)), int(time_match.group(2))),
                "ends_at_local": _fmt(int(time_match.group(3)), int(time_match.group(4))),
            }
        )
    return week_start, cells


def _orsha_prices(html: str) -> tuple[int | None, int | None, int | None]:
    adult = child = rental = None
    rows_flat: list[list[str]] = []
    for table in parse_tables(html):
        rows_flat.extend(table)
    section = None
    for idx, row in enumerate(rows_flat):
        if len(row) == 1:
            section = row[0].strip().upper()
            continue
        if not row:
            continue
        label = row[0].strip().lower()
        if section and "МАССОВОЕ КАТАНИЕ" in section and "БЕЗ ПРЕДОСТАВЛЕНИЯ" in section:
            if label == "взрослый" and len(row) >= 3:
                adult = _price_minor(row[2])
            elif label.startswith("детский") and len(row) >= 3:
                child = _price_minor(row[2])
        if section == "УСЛУГИ ПРОКАТА" and label == "предоставление коньков" and len(row) >= 3:
            rental = _price_minor(row[2])
    return adult, child, rental


class OrshaArenaParser(IceParser):
    parser_key = PARSER_KEY_ORSHA_ARENA

    async def extract(self, job: ParserJob) -> Extraction:
        schedule_html = await load_source_text(job, filename="schedule.html", url_keys=("schedule_url",))
        prices_html = await load_source_text(job, filename="prices.html", url_keys=("prices_url",))
        duration = int(job.config.get("default_duration_minutes") or 45)
        age_note = job.config.get("age_note")
        adult, child, rental = _orsha_prices(prices_html)

        base_url = str(job.config.get("schedule_url") or "")
        candidates = _orsha_candidate_images(schedule_html, base_url, job.config)

        best_week: date | None = None
        best_cells: list[dict[str, Any]] = []
        for basename, url in candidates:
            image_bytes = await _load_bytes(job, filename=basename, url=url)
            week_start, cells = _orsha_extract_from_image(image_bytes, job.config)
            if week_start is None:
                continue
            if best_week is None or week_start > best_week:
                best_week = week_start
                best_cells = cells

        slots: list[ExtractedSlot] = []
        for cell in best_cells:
            slots.append(
                ExtractedSlot(
                    local_date=cell["local_date"].isoformat(),
                    starts_at_local=cell["starts_at_local"],
                    ends_at_local=cell["ends_at_local"] or _add_minutes(cell["starts_at_local"], duration),
                    kind_raw="Массовое катание",
                    price_adult=adult,
                    price_child=child,
                    price_rental=rental,
                    session_label="Массовое катание",
                    age_note=age_note,
                )
            )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"schedule": schedule_html, "prices": prices_html, "images": [c[0] for c in candidates]},
            slots=slots,
        )


# ---------------------------------------------------------------------------
# gorki-lds (arena_id 32) — hand-written MK announcements on the home page.
# ---------------------------------------------------------------------------

_GORKI_RANGE = re.compile(
    r"(\d{1,2})\s*[-–—]\s*(\d{1,2})\s+([А-ЯЁа-яё]+)\s*:?\s*(\d{1,2})[.:](\d{2})"
)
_GORKI_SINGLE = re.compile(r"(\d{1,2})\s+([А-ЯЁа-яё]+)\s*:?\s*(\d{1,2})[.:](\d{2})")
_YEAR_TOKEN = re.compile(r"\b(20\d{2})\b")


class GorkiLdsParser(IceParser):
    parser_key = PARSER_KEY_GORKI_LDS

    async def extract(self, job: ParserJob) -> Extraction:
        home_html = await load_source_text(job, filename="mass-skating-home-excerpt.html", url_keys=("schedule_url",))
        prices_html = await load_source_text(job, filename="uslugi.html", url_keys=("prices_url",))
        duration = int(job.config.get("default_duration_minutes") or 45)
        heading = str(job.config.get("mk_heading") or "МАССОВОЕ КАТАНИЕ")
        age_note = job.config.get("age_note")
        adult, child, rental = _gorki_prices(prices_html)

        anchor_year = int(job.config.get("run_year") or date.today().year)
        year_match = _YEAR_TOKEN.search(strip_tags(home_html))
        year = int(year_match.group(1)) if year_match else anchor_year

        slots: list[ExtractedSlot] = []
        paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", home_html, re.S | re.IGNORECASE)
        seen_heading = False
        for raw_p in paragraphs:
            text = strip_tags(raw_p)
            if not text.strip():
                continue
            if heading.upper() in text.upper():
                seen_heading = True
                continue
            if not seen_heading:
                continue
            if "ОТМЕНЯ" in text.upper():
                continue
            range_match = _GORKI_RANGE.search(text)
            if range_match:
                d1, d2, month_word, hh, mm = range_match.groups()
                month = _MONTHS.get(month_word.lower())
                if not month:
                    continue
                start = _fmt(int(hh), int(mm))
                for day_num in (int(d1), int(d2)):
                    try:
                        local_date = date(year, month, day_num)
                    except ValueError:
                        continue
                    slots.append(_gorki_slot(local_date, start, duration, adult, child, rental, age_note))
                continue
            single_match = _GORKI_SINGLE.search(text)
            if single_match:
                d1, month_word, hh, mm = single_match.groups()
                month = _MONTHS.get(month_word.lower())
                if not month:
                    continue
                start = _fmt(int(hh), int(mm))
                try:
                    local_date = date(year, month, int(d1))
                except ValueError:
                    continue
                slots.append(_gorki_slot(local_date, start, duration, adult, child, rental, age_note))
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"home": home_html, "uslugi": prices_html},
            slots=slots,
        )


def _gorki_slot(
    local_date: date,
    start: str,
    duration: int,
    adult: int | None,
    child: int | None,
    rental: int | None,
    age_note: str | None,
) -> ExtractedSlot:
    return ExtractedSlot(
        local_date=local_date.isoformat(),
        starts_at_local=start,
        ends_at_local=_add_minutes(start, duration),
        kind_raw="Массовое катание",
        price_adult=adult,
        price_child=child,
        price_rental=rental,
        session_label=None,
        age_note=age_note,
    )


def _gorki_prices(html: str) -> tuple[int | None, int | None, int | None]:
    adult = child = rental = None
    for table in parse_tables(html):
        for row in table:
            if len(row) < 4:
                continue
            label = row[1].strip().lower()
            if "массовое катание" in label and "абонемент" not in label:
                if "взросл" in label:
                    adult = _price_minor(row[3])
                elif "дет" in label:
                    child = _price_minor(row[3])
            elif label == "предоставление коньков":
                rental = _price_minor(row[3])
    return adult, child, rental


# ---------------------------------------------------------------------------
# ostrovets-lds (arena_id 41) — two weekly `table.cool-table` grids.
# ---------------------------------------------------------------------------

_HEADER_DATE_PAIR = re.compile(r"(\d{1,2})\s*([А-Яа-яЁё]+)")


def _ostrovets_header_date(cell: str, year: int) -> date | None:
    for num, word in _HEADER_DATE_PAIR.findall(cell):
        month = _MONTHS.get(word.lower())
        if month:
            try:
                return date(year, month, int(num))
            except ValueError:
                return None
    return None


class OstrovetsLdsParser(IceParser):
    parser_key = PARSER_KEY_OSTROVETS_LDS

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="katanie-na-konkah.html", url_keys=("url",))
        prices_html = await load_source_text(job, filename="prejskurant-cen.html", url_keys=("prices_url",))
        year = int(job.config.get("run_year") or date.today().year)
        duration = int(job.config.get("default_duration_minutes") or 45)
        empty_marker = str(job.config.get("empty_cell_marker") or "нет катаний").lower()
        age_note = job.config.get("age_note")
        adult, child, rental = _ostrovets_prices(prices_html)

        slots: list[ExtractedSlot] = []
        for table in parse_tables(html):
            if not table or len(table[0]) != 7:
                continue  # skip the redundant 3-column responsive duplicate
            header = table[0]
            col_dates = [_ostrovets_header_date(cell, year) for cell in header]
            for row in table[1:]:
                for idx, cell in enumerate(row):
                    if idx >= len(col_dates) or col_dates[idx] is None:
                        continue
                    if empty_marker in cell.lower():
                        continue
                    for time_match in re.finditer(r"(\d{1,2})[.:](\d{2})", cell):
                        start = _fmt(int(time_match.group(1)), int(time_match.group(2)))
                        slots.append(
                            ExtractedSlot(
                                local_date=col_dates[idx].isoformat(),
                                starts_at_local=start,
                                ends_at_local=_add_minutes(start, duration),
                                kind_raw="Массовое катание",
                                price_adult=adult,
                                price_child=child,
                                price_rental=rental,
                                session_label=None,
                                age_note=age_note,
                            )
                        )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"katanie": html, "prejskurant": prices_html},
            slots=slots,
        )


def _ostrovets_prices(html: str) -> tuple[int | None, int | None, int | None]:
    adult = child = rental = None
    for table in parse_tables(html):
        for row in table:
            if len(row) < 2:
                continue
            label = row[1].strip().lower()
            if "сеанс массового катания" in label and "взросл" in label:
                adult = parse_price_to_minor(row[-1], already_minor=False)
            elif "сеанс массового катания" in label and "дети" in label:
                child = parse_price_to_minor(row[-1], already_minor=False)
            elif label == "услуга предоставления" and len(row) >= 3 and row[2].strip().lower() == "коньков":
                rental = parse_price_to_minor(row[-1], already_minor=False)
    return adult, child, rental
