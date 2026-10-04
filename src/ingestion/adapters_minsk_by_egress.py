"""Minsk arenas that require Belarus egress (ledlife.by, junost.by)."""
from __future__ import annotations

import html as html_lib
import re
from datetime import date, datetime, timedelta
from typing import Any

from src.ingestion.htmlutil import parse_tables, strip_tags
from src.ingestion.normalize import parse_price_to_minor
from src.ingestion.parsers import IceParser
from src.ingestion.source_io import fetch_http_text_optional, load_source_text
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob

_BY_BLOCK_MARKER = "403 Forbidden"

# Прейскурант «Крытый каток» от 01.09.2026 (фото на krytyi_katok434451): цена **с НДС**, касса, 45 мин МК.
LEDLIFE_MK_PRICE_BANDS_VAT_2026_09: dict[str, dict[str, int]] = {
    "day_45": {"adult": 1000, "child": 800},
    "evening_45": {"adult": 1100, "child": 900},
}
_LED_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{2})")
_LED_TIME = re.compile(r"^(\d{1,2})-(\d{2})$")
_MASS_LABEL = re.compile(r"МАССОВ(ЫЕ|ОЕ)\s+КАТАН", re.IGNORECASE)
_JUNOST_DAY_LINE = re.compile(
    r"(?:понедельник|вторник|среда|четверг|пятница|суббота|воскресенье)"
    r"\s*,?\s*(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)",
    re.IGNORECASE,
)
_JUNOST_TIME_RANGE = re.compile(r"(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})")
_JUNOST_MONTHS = {
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


def is_by_origin_blocked_snapshot(html: str) -> bool:
    if _BY_BLOCK_MARKER in html:
        return True
    if "</html>" not in html.lower():
        return True
    return False


def _fmt(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _norm_led_time(raw: str) -> str | None:
    raw = raw.strip()
    match = _LED_TIME.match(raw)
    if not match:
        return None
    return _fmt(int(match.group(1)), int(match.group(2)))


def _parse_led_date(cell: str, *, pivot_year: int) -> date | None:
    match = _LED_DATE.search(cell)
    if not match:
        return None
    day, month, yy = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    year = 2000 + yy if yy < 100 else yy
    if year < pivot_year - 1:
        year += 100
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_ledlife_style_table(
    html: str,
    *,
    pivot_year: int | None = None,
) -> list[ExtractedSlot]:
    """Schedule grid shared by ledlife.by and junost.by origin pages."""
    anchor = pivot_year or date.today().year
    slots: list[ExtractedSlot] = []
    current_date: date | None = None
    for table in parse_tables(html):
        if not table:
            continue
        header = [c.strip().lower() for c in table[0]]
        if not header or "дата" not in header[0]:
            continue
        for row in table[1:]:
            if not row:
                continue
            cells = [c.strip() for c in row]
            while cells and not cells[0]:
                cells = cells[1:]
            if not cells:
                continue
            if _LED_DATE.search(cells[0]):
                current_date = _parse_led_date(cells[0], pivot_year=anchor)
                if current_date is None:
                    continue
                start_raw, arena, duration_raw, label = _row_tail(cells, offset=1)
            else:
                if current_date is None:
                    continue
                start_raw, arena, duration_raw, label = _row_tail(cells, offset=0)
            if not label or not _MASS_LABEL.search(label):
                continue
            start = _norm_led_time(start_raw)
            if not start:
                continue
            try:
                duration = int(re.sub(r"\D", "", duration_raw) or "45")
            except ValueError:
                duration = 45
            hour, minute = (int(p) for p in start.split(":"))
            end_dt = datetime(2000, 1, 1, hour, minute) + timedelta(minutes=duration)
            slots.append(
                ExtractedSlot(
                    local_date=current_date.isoformat(),
                    starts_at_local=start,
                    ends_at_local=_fmt(end_dt.hour, end_dt.minute),
                    kind_raw="Массовое катание",
                    session_label=arena or None,
                )
            )
    return slots


def _row_tail(cells: list[str], *, offset: int) -> tuple[str, str, str, str]:
    chunk = cells[offset:]
    if len(chunk) >= 4:
        return chunk[0], chunk[1], chunk[2], chunk[3]
    if len(chunk) == 3:
        return chunk[0], "", chunk[1], chunk[2]
    return "", "", "", ""


def _price_pair_from_cell(price_cell: str) -> tuple[int, int] | None:
    nums = re.findall(r"(\d+)[,.](\d{2})", price_cell)
    if len(nums) < 2:
        return None
    adult = int(nums[0][0]) * 100 + int(nums[0][1])
    child = int(nums[1][0]) * 100 + int(nums[1][1])
    return adult, child


def _ledlife_mk_band_key(label_plain: str) -> str | None:
    lower = label_plain.lower()
    if "дневной" in lower or ("07:00" in label_plain and "17:00" in label_plain):
        return "day_45"
    if "17:00" in label_plain or "выходные" in lower or "празднич" in lower:
        return "evening_45"
    return None


def _ledlife_prices_from_stoimost_tables(tables: list[list[list[str]]]) -> dict[str, dict[str, int]]:
    book: dict[str, dict[str, int]] = {}
    in_mk = False
    for table in tables:
        for row in table:
            if not row:
                continue
            label_html = row[0]
            label_plain = strip_tags(label_html)
            lower = label_plain.lower()
            if "семейное массовое" in lower or (
                "абонемент" in lower and "массового катания" in lower
            ):
                in_mk = False
                continue
            if "массовое катание" in lower and "семейн" not in lower and "большое" not in lower:
                in_mk = True
            if not in_mk:
                continue
            duration_cell = strip_tags(row[1]) if len(row) > 2 else ""
            if "45" not in duration_cell and "45" not in label_plain:
                continue
            pair = _price_pair_from_cell(row[-1] if row else "")
            if not pair:
                continue
            band = _ledlife_mk_band_key(label_plain)
            if band is None and "day_45" in book and "evening_45" not in book:
                band = "evening_45"
            if band is None:
                band = "day_45"
            book[band] = {"adult": pair[0], "child": pair[1]}
    return book


def _ledlife_prices_from_stoimost_plain(plain: str) -> dict[str, dict[str, int]]:
    book: dict[str, dict[str, int]] = {}
    focus = plain
    idx = plain.lower().find("массовое катание на коньках")
    if idx >= 0:
        focus = plain[idx : idx + 4000]
    day = re.search(
        r"дневной\s+сеанс.*?(\d+)[,.](\d{2}).*?(\d+)[,.](\d{2})",
        focus,
        flags=re.I | re.S,
    )
    if day:
        book["day_45"] = {
            "adult": int(day.group(1)) * 100 + int(day.group(2)),
            "child": int(day.group(3)) * 100 + int(day.group(4)),
        }
    evening = re.search(
        r"17:00.*?(\d+)[,.](\d{2}).*?(\d+)[,.](\d{2})",
        focus,
        flags=re.I | re.S,
    )
    if evening:
        book["evening_45"] = {
            "adult": int(evening.group(1)) * 100 + int(evening.group(2)),
            "child": int(evening.group(3)) * 100 + int(evening.group(4)),
        }
    return book


def _ledlife_mk_price_bands_from_config(job: ParserJob) -> dict[str, dict[str, int]]:
    raw = job.config.get("mk_price_bands")
    if not isinstance(raw, dict):
        return dict(LEDLIFE_MK_PRICE_BANDS_VAT_2026_09)
    out: dict[str, dict[str, int]] = {}
    for key, band in raw.items():
        if isinstance(band, dict) and "adult" in band and "child" in band:
            out[str(key)] = {"adult": int(band["adult"]), "child": int(band["child"])}
    return out or dict(LEDLIFE_MK_PRICE_BANDS_VAT_2026_09)


def _ledlife_prices_from_preiskurant_page(html: str, job: ParserJob) -> dict[str, dict[str, int]]:
    """Site publishes preiskurant as scanned pages (images), not HTML tables."""
    if re.search(r"preiskurant|прейскурант", html, re.I):
        return _ledlife_mk_price_bands_from_config(job)
    return {}


def _ledlife_is_schedule_html(html: str) -> bool:
    plain = strip_tags(html)
    return len(re.findall(r"\b\d{2}\.\d{2}\.\d{2}\b", plain)) >= 5


def _ledlife_schedule_url(job: ParserJob) -> str:
    return str(job.config.get("url") or "").rstrip("/")


def _ledlife_skip_price_url(job: ParserJob, url: str) -> bool:
    u = url.rstrip("/")
    sched = _ledlife_schedule_url(job)
    if sched and u == sched:
        return True
    return "massovye_kataniya" in u.lower()


def _ledlife_prices_from_mk_amount_run(html: str) -> dict[str, dict[str, int]]:
    """Fallback when ledlife reformatted prices outside classic tables."""
    if _ledlife_is_schedule_html(html):
        return {}
    plain = strip_tags(html)
    lower = plain.lower()
    start = -1
    for needle in (
        "массовое катание на коньках",
        "массовое катание",
        "большое массовое катание",
    ):
        start = lower.find(needle)
        if start >= 0:
            break
    if start < 0:
        return {}
    end = len(plain)
    for stop in ("семейное массовое", "абонемент", "заточка коньков", "прокат коньков"):
        pos = lower.find(stop, start + 10)
        if pos > start:
            end = min(end, pos)
    section = plain[start:end]
    amounts: list[int] = []
    for whole, frac in re.findall(r"\b(\d{1,2})[,.](\d{2})\b", section):
        minor = int(whole) * 100 + int(frac)
        if 300 <= minor <= 2500:
            amounts.append(minor)
    if len(amounts) >= 4:
        return {
            "day_45": {"adult": amounts[0], "child": amounts[1]},
            "evening_45": {"adult": amounts[2], "child": amounts[3]},
        }
    if len(amounts) >= 2:
        pair = {"adult": amounts[0], "child": amounts[1]}
        return {"day_45": pair, "evening_45": dict(pair)}
    return {}


def _ledlife_discover_price_page_urls(html: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in re.finditer(r'href="(/[^"#?]+)"', html, flags=re.I):
        path = match.group(1).strip()
        low = path.lower()
        if any(skip in low for skip in ("javascript", "mailto", "callback", "feedback", ".pdf", "viber:")):
            continue
        if not any(
            token in low
            for token in ("stoimost", "massovoe", "katan", "katok", "prejskur", "prajs", "tsen", "uslug")
        ):
            continue
        url = f"https://ledlife.by{path}"
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _ledlife_prices_candidate_urls(job: ParserJob, stoimost_html: str) -> list[str]:
    """Hub stoimost_uslug often 403/empty on subpaths — try several BY pages."""
    seen: set[str] = set()
    urls: list[str] = []

    def add(raw: str | None) -> None:
        if not raw:
            return
        u = raw.strip()
        if not u or u in seen:
            return
        seen.add(u)
        urls.append(u)

    add(job.config.get("prices_detail_url"))
    add("https://ledlife.by/krytyi_katok434451/")
    for pattern in (
        r'href="(/krytyi_katok\d+/)"',
        r'href="(/krytyi_ledovyi_katok/)"',
        r'href="(/massovoe_katanie/)"',
    ):
        match = re.search(pattern, stoimost_html, flags=re.I)
        if match:
            add(f"https://ledlife.by{match.group(1)}")
    fallbacks = job.config.get("prices_fallback_urls")
    if isinstance(fallbacks, list):
        for item in fallbacks:
            add(str(item))
    else:
        add("https://ledlife.by/krytyi_ledovyi_katok/")
        add("https://ledlife.by/massovoe_katanie/")
        add("https://ledlife.by/krytyi_katok434451/")
    return urls


async def _load_ledlife_prices_html(job: ParserJob) -> str:
    primary = await load_source_text(job, filename="stoimost_uslug.html", url_keys=("prices_url",))
    if _ledlife_prices_from_stoimost(primary, job):
        return primary
    fixture_dir = job.config.get("fixture_dir")
    if fixture_dir:
        from pathlib import Path

        for name in ("krytyi_katok434451.html", "krytyi_katok.html", "prices_detail.html"):
            path = Path(str(fixture_dir)) / name
            if path.is_file():
                detail = path.read_text(encoding="utf-8")
                if _ledlife_prices_from_stoimost(detail, job):
                    return detail
        return primary
    prices_url = str(job.config.get("prices_url") or "https://ledlife.by/stoimost_uslug/").rstrip("/")
    queue = list(_ledlife_prices_candidate_urls(job, primary))
    seen_urls: set[str] = set()
    while queue and len(seen_urls) < 18:
        url = queue.pop(0)
        if url in seen_urls or _ledlife_skip_price_url(job, url):
            continue
        seen_urls.add(url)
        if url.rstrip("/") == prices_url:
            detail = primary
        else:
            detail = await fetch_http_text_optional(url)
        if not detail or is_by_origin_blocked_snapshot(detail):
            continue
        if _ledlife_prices_from_stoimost(detail, job):
            return detail
        for child in _ledlife_discover_price_page_urls(detail):
            if child not in seen_urls and child not in queue and not _ledlife_skip_price_url(job, child):
                queue.append(child)
    return primary


def _ledlife_prices_from_stoimost(html: str, job: ParserJob | None = None) -> dict[str, dict[str, int]]:
    """Day vs evening 45-minute MK bands (adult/child in minor units)."""
    tables = parse_tables(html)
    book = _ledlife_prices_from_stoimost_tables(tables) if tables else {}
    if not book:
        book = _ledlife_prices_from_stoimost_plain(strip_tags(html))
    if not book:
        book = _ledlife_prices_from_mk_amount_run(html)
    if not book and job is not None:
        book = _ledlife_prices_from_preiskurant_page(html, job)
    return book


def _parse_junost_day(day: str, month_word: str, *, pivot_year: int) -> date | None:
    month = _JUNOST_MONTHS.get(month_word.lower())
    if month is None:
        return None
    try:
        return date(pivot_year, month, int(day))
    except ValueError:
        return None


def _norm_junost_hhmm(raw: str) -> str:
    parts = raw.strip().split(":")
    hour, minute = int(parts[0]), int(parts[1])
    return _fmt(hour, minute)


def _parse_junost_paragraph_schedule(
    html: str,
    *,
    pivot_year: int | None = None,
) -> list[ExtractedSlot]:
    """Weekend MK blocks on junost.by news-style pages (no schedule table)."""
    anchor = pivot_year or date.today().year
    focus = html
    title = re.search(r"Сеансы\s+массовых\s+катаний", html, re.I)
    if title:
        focus = html[title.start() : title.start() + 12_000]
    slots: list[ExtractedSlot] = []
    current_date: date | None = None
    for raw_p in re.findall(r"<p[^>]*>(.*?)</p>", focus, flags=re.I | re.S):
        if "closed_notice" in raw_p.lower():
            continue
        text = re.sub(r"\s+", " ", strip_tags(raw_p)).strip()
        if not text:
            continue
        day_match = _JUNOST_DAY_LINE.search(text)
        if day_match:
            current_date = _parse_junost_day(day_match.group(1), day_match.group(2), pivot_year=anchor)
            continue
        time_match = _JUNOST_TIME_RANGE.search(text)
        if time_match and current_date is not None:
            slots.append(
                ExtractedSlot(
                    local_date=current_date.isoformat(),
                    starts_at_local=_norm_junost_hhmm(time_match.group(1)),
                    ends_at_local=_norm_junost_hhmm(time_match.group(2)),
                    kind_raw="Массовое катание",
                    session_label="Главная",
                )
            )
    return slots


def _junost_prices_from_origin(html: str) -> tuple[int | None, int | None, int | None]:
    plain = html_lib.unescape(strip_tags(html))
    adult = child = rental = None
    m_adult = re.search(r"(\d+[,.]\d+)\s*рубл[ьяей]*\s*\(взросл", plain, re.I)
    m_child = re.search(r"(\d+[,.]\d+)\s*рубл[ьяей]*\s*\(дет", plain, re.I)
    if not m_adult:
        m_adult = re.search(r"взросл\S*\s*[—\-–:]?\s*(\d+(?:[,.]\d+)?)\s*р", plain, re.I)
    if not m_child:
        m_child = re.search(r"детск\S*\s*[—\-–:]?\s*(\d+(?:[,.]\d+)?)\s*р", plain, re.I)
    m_rental = re.search(r"Прокат коньков\s*[—\-–:]?\s*(\d+(?:[,.]\d+)?)", plain, re.I)
    if m_adult:
        adult = parse_price_to_minor(m_adult.group(1).replace(",", ".") + " BYN", already_minor=False)
    if m_child:
        child = parse_price_to_minor(m_child.group(1).replace(",", ".") + " BYN", already_minor=False)
    if m_rental:
        rental = parse_price_to_minor(m_rental.group(1).replace(",", ".") + " BYN", already_minor=False)
    return adult, child, rental


def _mk_age_note_when_tiered(adult_minor: int | None, child_minor: int | None) -> str | None:
    if adult_minor is None or child_minor is None or adult_minor == child_minor:
        return None
    return "детский до 16 лет"


def _minor_to_major(value: int | None) -> float | None:
    if value is None:
        return None
    return round(value / 100.0, 2)


def _ledlife_price_band_key(slot: ExtractedSlot) -> str:
    local = date.fromisoformat(slot.local_date)
    hour = int(slot.starts_at_local.split(":")[0]) if slot.starts_at_local else 0
    if local.weekday() >= 5 or hour >= 17:
        return "evening_45"
    return "day_45"


def _ledlife_mk_rental_minor(job: ParserJob, *, price_book: dict[str, dict[str, int]]) -> int | None:
    if not price_book:
        return None
    raw = job.config.get("mk_rental_minor")
    if raw is None:
        return None
    return int(raw)


def _apply_ledlife_prices(
    slots: list[ExtractedSlot],
    price_book: dict[str, dict[str, int]],
    job: ParserJob,
) -> None:
    rental_minor = _ledlife_mk_rental_minor(job, price_book=price_book)
    rental_major = _minor_to_major(rental_minor)
    for slot in slots:
        band_key = _ledlife_price_band_key(slot)
        band = price_book.get(band_key) or price_book.get("evening_45") or price_book.get("day_45")
        if not band:
            continue
        adult_minor = band.get("adult")
        child_minor = band.get("child")
        slot.price_adult = _minor_to_major(adult_minor)
        slot.price_child = _minor_to_major(child_minor)
        slot.age_note = _mk_age_note_when_tiered(adult_minor, child_minor)
        if rental_major is not None:
            slot.price_rental = rental_major


class LedlifeOriginHtmlParser(IceParser):
    parser_key = "ledlife_origin_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        schedule = await load_source_text(job, filename="massovye_kataniya.html", url_keys=("url",))
        blocked = is_by_origin_blocked_snapshot(schedule)
        slots: list[ExtractedSlot] = []
        if not blocked:
            slots = _parse_ledlife_style_table(schedule)
            if slots:
                try:
                    prices_html = await _load_ledlife_prices_html(job)
                except Exception:  # noqa: BLE001 — optional prices page
                    prices_html = ""
                if prices_html and not is_by_origin_blocked_snapshot(prices_html):
                    book = _ledlife_prices_from_stoimost(prices_html, job)
                    _apply_ledlife_prices(slots, book, job)
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={
                "schedule": schedule,
                "blocked_without_by_egress": blocked or not slots,
            },
            slots=slots,
        )


class JunostHtmlParser(IceParser):
    parser_key = "junost_origin_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        schedule_file = str(job.config.get("schedule_fixture") or "junost-origin.html")
        html = await load_source_text(job, filename=schedule_file, url_keys=("url",))
        blocked = is_by_origin_blocked_snapshot(html)
        slots: list[ExtractedSlot] = []
        if not blocked:
            slots = _parse_ledlife_style_table(html)
            if not slots:
                slots = _parse_junost_paragraph_schedule(html)
            if slots:
                adult, child, rental = _junost_prices_from_origin(html)
                for slot in slots:
                    slot.price_adult = _minor_to_major(adult)
                    slot.price_child = _minor_to_major(child)
                    slot.price_rental = _minor_to_major(rental)
                    slot.age_note = _mk_age_note_when_tiered(adult, child)
            elif not _schedule_table_present(html) and not _junost_paragraph_schedule_present(html):
                blocked = True
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"origin": html, "blocked_without_by_egress": blocked or not slots},
            slots=slots,
        )


def _schedule_table_present(html: str) -> bool:
    for table in parse_tables(html):
        if table and table[0] and "дата" in table[0][0].lower():
            return True
    return False


def _junost_paragraph_schedule_present(html: str) -> bool:
    if not re.search(r"Сеансы\s+массовых\s+катаний", html, re.I):
        return False
    return bool(_JUNOST_DAY_LINE.search(strip_tags(html)))


# Backwards-compatible alias used in tests/docs.
is_junost_blocked_snapshot = is_by_origin_blocked_snapshot
