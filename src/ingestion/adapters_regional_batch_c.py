"""Batch C regional IceParser strategies. Extract only — persistence is elsewhere.

Arenas: vitebsk-ds (29), mogilev-ds (43), orsha-arena (31), gorki-lds (32),
ostrovets-lds (41), raubichi-rcop (15). See data/parsers/<slug>.md for notes
this module implements, and .ai/data/fixtures/<slug>/ for fixtures + hand
extracted ground truth (expected.json).

New file only — does not modify src/ingestion/adapters.py, parsers.py, or
seed_config.py. A later integration step wires these classes into
ParserRegistry / default_registry().
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse


from src.ingestion.dates import infer_date_from_day_month, parser_reference_date
from src.ingestion.htmlutil import parse_tables, strip_tags
from src.ingestion.normalize import parse_price_to_minor
from src.ingestion.parsers import IceParser
from src.ingestion.seed_config_regional_batch_c import (
    PARSER_KEY_GORKI_LDS,
    PARSER_KEY_MOGILEV_DS,
    PARSER_KEY_ORSHA_ARENA,
    PARSER_KEY_OSTROVETS_LDS,
    PARSER_KEY_RAUBICHI,
    PARSER_KEY_VITEBSK_DS,
)
from src.shared.schedule_basis import SCHEDULE_BASIS_LIVE
from src.ingestion.cpu_work import run_cpu_bound
from src.ingestion.image_io import open_image_bytes
from src.ingestion.source_io import fetch_http_bytes, fetch_http_text, load_source_text
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
    return await fetch_http_bytes(url, headers={"User-Agent": _USER_AGENT})


# ---------------------------------------------------------------------------
# vitebsk-ds (arena_id 29) — 24afisha schedule API.
# hockey.by still shows the April–May 2026 grid, so the public page was empty.
# ---------------------------------------------------------------------------

_VITEBSK_AFISHA_EVENT_ID = 1385106
_VITEBSK_AFISHA_CITY_ID = 11
_VITEBSK_AFISHA_OBJECT_ID = 124
_VITEBSK_EVENT_PAGE = (
    "https://24afisha.by/ru/vitebsk/event/massovoe-katanie-v-vitebskom-dvortse-sporta"
)
_VITEBSK_SESSION_TICKETS = "https://saleframe.24afisha.by/?sid={session_id}&lang=ru"
_AFISHA_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_HG_SECURITY = re.compile(r"hg-security=([^;\"\s]+)")
_AFISHA_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": _USER_AGENT,
}


def vitebsk_schedule_url(config: dict) -> str:
    """Live schedule URL. Existing jobs still point ``url`` at hockey.by."""
    explicit = config.get("schedule_api_url")
    if explicit:
        return str(explicit)
    event_id = int(config.get("afisha_event_id") or _VITEBSK_AFISHA_EVENT_ID)
    city_id = int(config.get("afisha_city_id") or _VITEBSK_AFISHA_CITY_ID)
    return (
        f"https://api.24afisha.by/api/v2/schedule/events/{event_id}"
        f"?cityId={city_id}&lang=ru&slug=true&jsonld=0&ignoreEndTime=1"
    )


def _afisha_local_date(value: str) -> str | None:
    parts = str(value or "").strip().split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    day, month, year = (int(part) for part in parts)
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _afisha_hhmm(value: str) -> str | None:
    match = _AFISHA_HHMM.match(str(value or "").strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return _fmt(hour, minute)


def vitebsk_slots_from_schedule(payload: Any, config: dict) -> list[ExtractedSlot]:
    """Sessions from ``GET /api/v2/schedule/events/{id}``.

    ``minPrice`` is already minor units (700 = 7.00 BYN). ``dateStr`` / ``timeStr``
    are local Europe/Minsk. Duration comes from the event (60). Buy link is the
    saleframe widget for that session id.
    """
    events = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        return []
    object_id = int(config.get("afisha_object_id") or _VITEBSK_AFISHA_OBJECT_ID)
    age_note = config.get("age_note")
    fallback_duration = int(config.get("default_duration_minutes") or 60)
    tickets_template = str(config.get("session_tickets_url") or _VITEBSK_SESSION_TICKETS)
    slots: list[ExtractedSlot] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        try:
            duration = int(event.get("duration") or fallback_duration)
        except (TypeError, ValueError):
            duration = fallback_duration
        if duration <= 0:
            duration = fallback_duration
        for obj in event.get("objects") or []:
            if not isinstance(obj, dict):
                continue
            try:
                if int(obj.get("id") or 0) != object_id:
                    continue
            except (TypeError, ValueError):
                continue
            for session in obj.get("sessions") or []:
                if not isinstance(session, dict):
                    continue
                local_date = _afisha_local_date(str(session.get("dateStr") or ""))
                start = _afisha_hhmm(str(session.get("timeStr") or ""))
                if not local_date or not start:
                    continue
                session_id = session.get("id")
                external_url = None
                source_id = None
                if session_id is not None:
                    source_id = str(session_id)
                    external_url = tickets_template.format(session_id=source_id)
                slots.append(
                    ExtractedSlot(
                        local_date=local_date,
                        starts_at_local=start,
                        ends_at_local=_add_minutes(start, duration),
                        kind_raw="Массовое катание",
                        price_adult=session.get("minPrice"),
                        price_child=None,
                        price_rental=None,
                        source_id=source_id,
                        session_label=None,
                        age_note=age_note,
                        external_url=external_url,
                    )
                )
    return slots


def afisha_clearance_cookie(body: str) -> str | None:
    """24afisha answers bots with an HTML interstitial that sets ``hg-security``.

    The value is in the page script. Sending it back on the next GET returns
    the schedule JSON. No browser and no JS execution.
    """
    match = _HG_SECURITY.search(body or "")
    if not match:
        return None
    return f"hg-security={match.group(1)}"


def _json_body(body: str) -> Any | None:
    stripped = body.lstrip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


async def fetch_afisha_schedule(url: str) -> Any:
    body = await fetch_http_text(url, headers=_AFISHA_HEADERS)
    payload = _json_body(body)
    if payload is not None:
        return payload
    cookie = afisha_clearance_cookie(body)
    if not cookie:
        raise RuntimeError("24afisha schedule was not JSON and had no clearance cookie")
    body = await fetch_http_text(url, headers={**_AFISHA_HEADERS, "Cookie": cookie})
    payload = _json_body(body)
    if payload is None:
        raise RuntimeError("24afisha schedule stayed behind the verification page")
    return payload


async def _load_vitebsk_schedule(job: ParserJob) -> Any:
    fixture_dir = job.config.get("fixture_dir")
    if fixture_dir:
        path = Path(str(fixture_dir)) / "schedule.json"
        return json.loads(path.read_text(encoding="utf-8"))
    return await fetch_afisha_schedule(vitebsk_schedule_url(job.config))


class VitebskDsParser(IceParser):
    parser_key = PARSER_KEY_VITEBSK_DS

    async def extract(self, job: ParserJob) -> Extraction:
        payload = await _load_vitebsk_schedule(job)
        slots = vitebsk_slots_from_schedule(payload, job.config)
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot=payload,
            slots=slots,
        )


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

    img = open_image_bytes(image_bytes).convert("RGB")
    columns = _orsha_header_columns(img)
    if not columns:
        return None, []
    reference = parser_reference_date(config)
    col_dates: list[tuple[int, date]] = []
    for x_center, token in columns:
        day_str, month_str = token.split(".")
        month = int(month_str)
        day = int(day_str)
        local = infer_date_from_day_month(day, month, reference)
        if local is None:
            continue
        col_dates.append((x_center, local))
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
    for row in rows_flat:
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
            week_start, cells = await run_cpu_bound(_orsha_extract_from_image, image_bytes, job.config)
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

_GORKI_HEAD = re.compile(r"(\d{1,2})(?:\s*[-–—]\s*(\d{1,2}))?\s+([А-ЯЁа-яё]+)\s*:?\s*(.*)")
_GORKI_TIME = re.compile(r"(\d{1,2})[.:](\d{2})")


class GorkiLdsParser(IceParser):
    parser_key = PARSER_KEY_GORKI_LDS

    async def extract(self, job: ParserJob) -> Extraction:
        home_html = await load_source_text(job, filename="mass-skating-home-excerpt.html", url_keys=("schedule_url",))
        prices_html = await load_source_text(job, filename="uslugi.html", url_keys=("prices_url",))
        duration = int(job.config.get("default_duration_minutes") or 45)
        heading = str(job.config.get("mk_heading") or "МАССОВОЕ КАТАНИЕ")
        age_note = job.config.get("age_note")
        adult, child, rental = _gorki_prices(prices_html)

        # No page-year override: the first "20xx" on the page may be next year's
        # holiday heading or a footer year; nearest-date inference needs neither.
        reference = parser_reference_date(job.config)

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
            head = _GORKI_HEAD.search(text)
            if not head:
                continue
            d1, d2, month_word, tail = head.groups()
            month = _MONTHS.get(month_word.lower())
            times = _GORKI_TIME.findall(tail)
            if not month or not times:
                continue
            first = int(d1)
            last = int(d2) if d2 else first
            for day_num in range(first, last + 1):
                local_date = infer_date_from_day_month(day_num, month, reference)
                if local_date is None:
                    continue
                for hh, mm in times:
                    slots.append(
                        _gorki_slot(local_date, _fmt(int(hh), int(mm)), duration, adult, child, rental, age_note)
                    )
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


def _ostrovets_header_date(cell: str, reference: date) -> date | None:
    for num, word in _HEADER_DATE_PAIR.findall(cell):
        month = _MONTHS.get(word.lower())
        if month:
            return infer_date_from_day_month(int(num), month, reference)
    return None


class OstrovetsLdsParser(IceParser):
    parser_key = PARSER_KEY_OSTROVETS_LDS

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="katanie-na-konkah.html", url_keys=("url",))
        prices_html = await load_source_text(job, filename="prejskurant-cen.html", url_keys=("prices_url",))
        reference = parser_reference_date(job.config)
        duration = int(job.config.get("default_duration_minutes") or 45)
        empty_marker = str(job.config.get("empty_cell_marker") or "нет катаний").lower()
        age_note = job.config.get("age_note")
        adult, child, rental = _ostrovets_prices(prices_html)

        slots: list[ExtractedSlot] = []
        for table in parse_tables(html):
            if not table or len(table[0]) != 7:
                continue  # skip the redundant 3-column responsive duplicate
            header = table[0]
            col_dates = [_ostrovets_header_date(cell, reference) for cell in header]
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


# --------------------------------------------------------------------------
# РЦОП Раубичи (arena_id 15) — rau.by/skates/ h5 grid
# --------------------------------------------------------------------------

_RAUBICHI_SCHEDULE_MARKER = "Расписание массовых катаний"
_RAUBICHI_CLOSED_PHRASE = "не проводятся"
_RAUBICHI_H5_SLOT = re.compile(r"<h5[^>]*wb-stl-custom135[^>]*>(.*?)</h5>", re.I | re.S)
_RAUBICHI_H5_PRICE = re.compile(r"<h5[^>]*wb-stl-custom22[^>]*>(.*?)</h5>", re.I | re.S)
_RAUBICHI_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_RAUBICHI_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")


def _raubichi_prices(html: str) -> tuple[int | None, int | None, int | None]:
    adult = child = rental = None
    for match in _RAUBICHI_H5_PRICE.finditer(html):
        line = strip_tags(match.group(1)).strip()
        low = line.lower()
        if "руб" not in low:
            continue
        if "взрослый" in low:
            adult = parse_price_to_minor(line, already_minor=False)
        elif "детский" in low:
            child = parse_price_to_minor(line, already_minor=False)
        elif low.startswith("прокат"):
            rental = parse_price_to_minor(line, already_minor=False)
    return adult, child, rental


def _raubichi_schedule_slots(
    html: str,
    *,
    duration_minutes: int,
) -> list[tuple[date, str, str]]:
    marker_idx = html.find(_RAUBICHI_SCHEDULE_MARKER)
    if marker_idx < 0:
        return []
    region = html[marker_idx:]
    lines: list[str] = []
    for match in _RAUBICHI_H5_SLOT.finditer(region):
        line = strip_tags(match.group(1)).strip()
        if line:
            lines.append(line)
    if not lines:
        return []
    has_date = any(_RAUBICHI_DATE.match(line) for line in lines)
    if not has_date and any(_RAUBICHI_CLOSED_PHRASE in line.lower() for line in lines):
        return []

    current: date | None = None
    slots: list[tuple[date, str, str]] = []
    for line in lines:
        date_match = _RAUBICHI_DATE.match(line)
        if date_match:
            current = date(
                int(date_match.group(3)),
                int(date_match.group(2)),
                int(date_match.group(1)),
            )
            continue
        time_match = _RAUBICHI_TIME.match(line)
        if time_match and current is not None:
            start = _fmt(int(time_match.group(1)), int(time_match.group(2)))
            slots.append((current, start, _add_minutes(start, duration_minutes)))
    return slots


class RaubichiHtmlParser(IceParser):
    parser_key = PARSER_KEY_RAUBICHI

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="skates.html", url_keys=("url",))
        duration = int(job.config.get("default_duration_minutes") or 45)
        adult, child, rental = _raubichi_prices(html)
        slots: list[ExtractedSlot] = []
        for local_date, start, end in _raubichi_schedule_slots(html, duration_minutes=duration):
            slots.append(
                ExtractedSlot(
                    local_date=local_date.isoformat(),
                    starts_at_local=start,
                    ends_at_local=end,
                    kind_raw="Массовое катание",
                    price_adult=adult,
                    price_child=child,
                    price_rental=rental,
                )
            )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot=html,
            slots=slots,
            schedule_basis=SCHEDULE_BASIS_LIVE if slots else None,
        )
