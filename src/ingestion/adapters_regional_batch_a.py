"""Regional BY IceParser strategies — batch A (Брест, Барановичи, Кобрин, Пинск).

Extract only — these classes never INSERT into ice_sessions (see
``src/ingestion/parsers.py`` / ``IceSessionPublisher`` for that boundary).

Sources are plain HTML for three of the four arenas. The fourth
(``brest-lds``) publishes its weekly time grid only as a JPEG photo — this
project's ingestion layer is deterministic (no OCR / no LLM-in-the-loop at
runtime, see ``.ai/parsers/brest-lds.md``), so the fixed 21:15–22:15 slot
observed on the 2026-08-31..09-06 photo is carried as a ``job.config``
constant and only the *prices* (which are real HTML) are parsed live each
run. ``baranovichi-lds`` has the same problem in miniature: its price list
is a scanned PDF with no text layer (verified with pymupdf — zero
extractable characters on either page), so its BYN amounts are also a
``job.config`` constant, transcribed by a human from the SPEC dossier,
the same pattern this repo already uses for ``DiamondHtmlParser``'s
hardcoded weekday/weekend prices in ``adapters.py``. Both constants need a
human to re-check them if the operator changes prices/photo — there is no
live signal that would catch drift automatically.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from src.ingestion.htmlutil import parse_tables, strip_tags
from src.ingestion.normalize import parse_price_to_minor
from src.ingestion.parsers import IceParser
from src.ingestion.source_io import load_source_text
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob

# ---------------------------------------------------------------------------
# Shared tiny helpers
# ---------------------------------------------------------------------------

_TIME_TOKEN_DOT_OR_COLON = re.compile(r"(\d{1,2})[.:](\d{2})")


def _fmt(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _add_minutes(hour: int, minute: int, duration_minutes: int) -> tuple[int, int]:
    end_dt = datetime(2000, 1, 1, hour, minute) + timedelta(minutes=duration_minutes)
    return end_dt.hour, end_dt.minute


# ---------------------------------------------------------------------------
# Брест — arena_id 22 — parser_key brest_lds_v1
# ---------------------------------------------------------------------------

_BREST_CHILD = re.compile(r"[Дд]етей до \d+ лет\s*[–\-]\s*([\d.,]+)")
_BREST_ADULT = re.compile(r"[Вв]зрослых\s*[–\-]\s*([\d.,]+)")


def _brest_prices(html: str) -> tuple[int | None, int | None]:
    """Adult/child «Со своими коньками» prices from the live prices page.

    The block is bounded by «Со своими коньками:» and the next heading
    («Детский абонемент» / «С арендой коньков») so the abonement and
    rental-bundle amounts further down the same page are never picked up.
    """
    text = strip_tags(html)
    match = re.search(r"Со своими коньками:(.*?)(?:Детский абонемент|С арендой коньков)", text, re.S)
    block = match.group(1) if match else text
    child_match = _BREST_CHILD.search(block)
    adult_match = _BREST_ADULT.search(block)
    child = parse_price_to_minor(child_match.group(1) + " руб.", already_minor=False) if child_match else None
    adult = parse_price_to_minor(adult_match.group(1) + " руб.", already_minor=False) if adult_match else None
    return adult, child


class BrestLdsParser(IceParser):
    """«СВ кат» (свободное катание) — Брестский ЛДС.

    The weekly grid lives only in a JPEG (``IMG_8523.JPG``); per the SPEC
    dossier the observed week has one fixed daily slot, 21:15–22:15. That
    window is a ``job.config`` constant (``fixed_start`` / ``fixed_end``),
    repeated over ``horizon_days`` starting at ``run_date`` — the same
    horizon-from-a-fixed-start shape as ``ZamokHtmlParser``. Prices are
    parsed live from the real prices HTML every run.
    """

    parser_key = "brest_lds_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        prices_html = await load_source_text(job, filename="prices.html", url_keys=("prices_url",))
        adult, child = _brest_prices(prices_html)
        fixed_start = str(job.config.get("fixed_start") or "21:15")
        fixed_end = str(job.config.get("fixed_end") or "22:15")
        horizon = int(job.config.get("horizon_days") or 7)
        run_date = date.fromisoformat(str(job.config.get("run_date") or date.today().isoformat()))
        session_label = str(job.config.get("session_label") or "СВ кат")
        age_note = str(job.config.get("age_note") or "детям до 12 лет")
        slots: list[ExtractedSlot] = []
        for offset in range(horizon):
            local_date = run_date + timedelta(days=offset)
            slots.append(
                ExtractedSlot(
                    local_date=local_date.isoformat(),
                    starts_at_local=fixed_start,
                    ends_at_local=fixed_end,
                    kind_raw="open_ice",
                    price_adult=adult,
                    price_child=child,
                    price_rental=None,
                    session_label=session_label,
                    age_note=age_note,
                )
            )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=prices_html, slots=slots)


# ---------------------------------------------------------------------------
# Барановичи — arena_id 23 — parser_key baranovichi_lds_v1
# ---------------------------------------------------------------------------

_BARANOVICHI_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


class BaranovichiLdsParser(IceParser):
    """Ледовый дворец спорта (Барановичи) — WordPress date|weekday|times table.

    Prices live only in a scanned PDF (no extractable text layer — verified
    with pymupdf) so ``price_adult_minor`` / ``price_child_minor`` /
    ``price_rental_minor`` come from ``job.config`` (human-transcribed from
    the SPEC dossier), not from parsing ``prices.pdf``/``prices-page1-sm.jpg``
    at runtime.
    """

    parser_key = "baranovichi_lds_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        schedule_html = await load_source_text(job, filename="schedule.html", url_keys=("schedule_url",))
        duration = int(job.config.get("duration_minutes") or 45)
        adult = job.config.get("price_adult_minor")
        child = job.config.get("price_child_minor")
        rental = job.config.get("price_rental_minor")
        age_note = str(job.config.get("age_note") or "дети до 14 лет")
        slots: list[ExtractedSlot] = []
        for table in parse_tables(schedule_html):
            for row in table:
                if len(row) < 3:
                    continue
                date_match = _BARANOVICHI_DATE.search(row[0])
                if not date_match:
                    continue
                local_date = date(int(date_match.group(3)), int(date_match.group(2)), int(date_match.group(1)))
                for token in _TIME_TOKEN_DOT_OR_COLON.finditer(row[2]):
                    hour, minute = int(token.group(1)), int(token.group(2))
                    end_hour, end_minute = _add_minutes(hour, minute, duration)
                    slots.append(
                        ExtractedSlot(
                            local_date=local_date.isoformat(),
                            starts_at_local=_fmt(hour, minute),
                            ends_at_local=_fmt(end_hour, end_minute),
                            kind_raw="public_skate",
                            price_adult=adult,
                            price_child=child,
                            price_rental=rental,
                            age_note=age_note,
                        )
                    )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=schedule_html, slots=slots)


# ---------------------------------------------------------------------------
# Кобрин — arena_id 25 — parser_key kobrin_lds_v1
# ---------------------------------------------------------------------------

_KOBRIN_WEEK_RANGE = re.compile(r"(\d{2})\.(\d{2})\.(\d{2})\s*по\s*(\d{2})\.(\d{2})\.(\d{2})")
_KOBRIN_WEEKDAYS = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)
_KOBRIN_RUB_KOP = re.compile(r"(\d+)\s*руб\.?\s*(\d+)\s*коп", re.IGNORECASE)


def _kobrin_rub_kop_to_minor(text: str) -> int | None:
    match = _KOBRIN_RUB_KOP.search(text)
    if not match:
        return None
    return int(match.group(1)) * 100 + int(match.group(2))


def _kobrin_split_with_without(block: str) -> tuple[int | None, int | None]:
    with_match = re.search(r"(\d+\s*руб\.?\s*\d+\s*коп\.?)\s*—\s*с прокатом", block, re.IGNORECASE)
    without_match = re.search(r"(\d+\s*руб\.?\s*\d+\s*коп\.?)\s*—\s*без проката", block, re.IGNORECASE)
    with_rental = _kobrin_rub_kop_to_minor(with_match.group(1)) if with_match else None
    without_rental = _kobrin_rub_kop_to_minor(without_match.group(1)) if without_match else None
    return with_rental, without_rental


def _kobrin_prices(html: str) -> tuple[int | None, int | None, int | None]:
    """adult_minor, child_minor, rental_minor from «Стоимость сеансов массового катания»."""
    text = strip_tags(html)
    idx = text.lower().find("стоимость сеансов массового катания")
    window = text[idx : idx + 400] if idx >= 0 else text
    child_match = re.search(r"до 16 лет:(.*?)от 16 лет", window, re.S | re.IGNORECASE)
    adult_match = re.search(r"от 16 лет:(.*?)(?:скидки|$)", window, re.S | re.IGNORECASE)
    _child_with, child_without = _kobrin_split_with_without(child_match.group(1)) if child_match else (None, None)
    adult_with, adult_without = _kobrin_split_with_without(adult_match.group(1)) if adult_match else (None, None)
    rental = adult_with - adult_without if adult_with is not None and adult_without is not None else None
    return adult_without, child_without, rental


def _kobrin_monday(html: str) -> date | None:
    text = strip_tags(html)
    match = _KOBRIN_WEEK_RANGE.search(text)
    if not match:
        return None
    return date(2000 + int(match.group(3)), int(match.group(2)), int(match.group(1)))


class KobrinLdsParser(IceParser):
    """Расписание физкультурно-оздоровительного катания (ЛДС Кобрин).

    ``kobrininform.by`` gives weekday names (no calendar date) plus a
    «c DD.MM.YY по DD.MM.YY» header; Monday of that header anchors the
    dates. Prices are parsed live from ``kobrincity.by`` (rub/kop text, not
    a table) — the bundled «с прокатом» amount minus the own-skates amount
    gives ``price_rental_minor`` (there is no standalone rental line), per
    the SPEC dossier.
    """

    parser_key = "kobrin_lds_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        schedule_html = await load_source_text(job, filename="schedule.html", url_keys=("schedule_url",))
        prices_html = await load_source_text(job, filename="prices.html", url_keys=("prices_url",))
        duration = int(job.config.get("duration_minutes") or 45)
        age_note = str(job.config.get("age_note") or "до 16 лет")
        adult, child, rental = _kobrin_prices(prices_html)
        monday = _kobrin_monday(schedule_html)
        target_table: list[list[str]] | None = None
        for table in parse_tables(schedule_html):
            if table and table[0] and "дата" in table[0][0].strip().lower():
                target_table = table
                break
        slots: list[ExtractedSlot] = []
        if target_table and monday:
            for row in target_table[1:]:
                if not row:
                    continue
                weekday_name = row[0].strip().lower()
                if weekday_name not in _KOBRIN_WEEKDAYS:
                    continue
                local_date = monday + timedelta(days=_KOBRIN_WEEKDAYS.index(weekday_name))
                cell = row[1] if len(row) > 1 else ""
                for token in cell.split(";"):
                    token = token.strip()
                    match = re.fullmatch(r"(\d{1,2}):(\d{2})", token)
                    if not match:
                        continue
                    hour, minute = int(match.group(1)), int(match.group(2))
                    end_hour, end_minute = _add_minutes(hour, minute, duration)
                    slots.append(
                        ExtractedSlot(
                            local_date=local_date.isoformat(),
                            starts_at_local=_fmt(hour, minute),
                            ends_at_local=_fmt(end_hour, end_minute),
                            kind_raw="public_skate",
                            price_adult=adult,
                            price_child=child,
                            price_rental=rental,
                            age_note=age_note,
                        )
                    )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"schedule": schedule_html, "prices": prices_html},
            slots=slots,
        )


# ---------------------------------------------------------------------------
# Пинск — arena_id 24 — parser_key pinsk_volna_v1
# ---------------------------------------------------------------------------

_PINSK_DAY_DATE = re.compile(
    r"(Понедельник|Вторник|Среда|Четверг|Пятница|Суббота|Воскресенье)\s+(\d{2})\.(\d{2})\.(\d{4})",
    re.IGNORECASE,
)
_PINSK_TIME_RANGE = re.compile(r"(\d{1,2})[.:](\d{2})\s*[-–—]+\s*(\d{1,2})[.:](\d{2})")


def _pinsk_prices(html: str) -> tuple[int | None, int | None, int | None]:
    """adult_minor, child_minor, rental_minor from the ЕРИП tariff table."""
    adult = child = rental = None
    for table in parse_tables(html):
        if not table or not table[0]:
            continue
        header = " ".join(table[0]).lower()
        if "наименование услуги" not in header:
            continue
        for row in table[1:]:
            if len(row) < 3:
                continue
            name = row[0]
            unit = row[1]
            if "абонемент" in unit.lower():
                continue
            lname = name.lower()
            price = parse_price_to_minor(row[2], already_minor=False)
            if price is None:
                continue
            if "без предоставления коньков" in lname:
                if "дошкольн" in lname or "школьник" in lname:
                    child = price
                else:
                    adult = price
            elif lname.strip() == "пользование коньками":
                rental = price
        break
    return adult, child, rental


class PinskVolnaParser(IceParser):
    """УСК «Волна» / Ледовая арена ПолесГУ (Пинск).

    ``polessu.by`` writes the week as free-text «День DD.MM.YYYY» headers
    followed by ``HH.MM – HH.MM`` intervals inside the block between
    «Расписание массового катания» and «В расписании возможны изменения».
    Prices are a real HTML tariff table on a separate page.
    """

    parser_key = "pinsk_volna_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        schedule_html = await load_source_text(job, filename="schedule.html", url_keys=("schedule_url",))
        tariff_html = await load_source_text(job, filename="tariff.html", url_keys=("prices_url",))
        age_note = str(
            job.config.get("age_note") or "дошкольники, школьники и студенты дневной формы при предъявлении билета"
        )
        adult, child, rental = _pinsk_prices(tariff_html)
        text = strip_tags(schedule_html)
        lower = text.lower()
        start_idx = lower.find("расписание массового катания")
        end_idx = lower.find("в расписании возможны изменения")
        block = text[start_idx:end_idx] if start_idx >= 0 and end_idx > start_idx else text
        matches = list(_PINSK_DAY_DATE.finditer(block))
        slots: list[ExtractedSlot] = []
        for idx, day_match in enumerate(matches):
            local_date = date(int(day_match.group(4)), int(day_match.group(3)), int(day_match.group(2)))
            segment_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(block)
            segment = block[day_match.end() : segment_end]
            for time_match in _PINSK_TIME_RANGE.finditer(segment):
                start_hour, start_minute = int(time_match.group(1)), int(time_match.group(2))
                end_hour, end_minute = int(time_match.group(3)), int(time_match.group(4))
                slots.append(
                    ExtractedSlot(
                        local_date=local_date.isoformat(),
                        starts_at_local=_fmt(start_hour, start_minute),
                        ends_at_local=_fmt(end_hour, end_minute),
                        kind_raw="public_skate",
                        price_adult=adult,
                        price_child=child,
                        price_rental=rental,
                        age_note=age_note,
                    )
                )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"schedule": schedule_html, "tariff": tariff_html},
            slots=slots,
        )
