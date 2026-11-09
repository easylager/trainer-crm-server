"""SPb batch P IceParser strategy. Extract only.

- ``GololedHtmlParser`` (spb-gololed.md, arena_id=178) — СК «Гололёд»,
  Красное Село. Server-rendered schedule widget with one ``schedule_td`` cell
  per session carrying machine-readable ``data-*`` attributes.

Currency is RUB, timezone Europe/Moscow.
"""

from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from zoneinfo import ZoneInfo

from src.ingestion.htmlutil import strip_tags
from src.ingestion.parsers import IceParser
from src.ingestion.source_io import fetch_http_text_optional, load_source_text
from src.ingestion.types import (
    PARSER_KIND_FIGURE_FREE,
    PARSER_KIND_HOCKEY_PRACTICE,
    PARSER_KIND_PUBLIC_SKATE,
    ExtractedSlot,
    Extraction,
    ParserJob,
)

# --- spb-gololed ----------------------------------------------------------

_GOLOLED_SCHEDULE_MARKER = 'id="schedule_for_all_component"'
_GOLOLED_CELL = re.compile(r"<div\b(?=[^>]*\bclass=\"schedule_td\b)([^>]*)>", re.S)
_GOLOLED_ATTR = re.compile(r'data-([a-z_]+)="([^"]*)"')
_GOLOLED_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_GOLOLED_START_LABEL = re.compile(r"(\d{1,2}):(\d{2})\s*$")
_GOLOLED_KINDS = {
    "massovoe_katanie": PARSER_KIND_PUBLIC_SKATE,
    "chas_hokkeya": PARSER_KIND_HOCKEY_PRACTICE,
}
_GOLOLED_FIGURE_PREFIX = "chas_figurnogo"
# "650 руб/сеанс 1 час", "800 руб/сеанс 1 час 15 минут" (massovye-kataniya page).
_GOLOLED_PRICE_BY_DURATION = re.compile(r"(\d[\d ]{1,5})\s*руб\.?\s*/\s*сеанс\s+1\s*час(?:\s+(\d{1,2})\s*мин)?")
# "Стоимость 650 руб/сеанс" (chas-hokkeya page).
_GOLOLED_FLAT_PRICE = re.compile(r"Стоимость:?\s*(\d[\d ]{1,5})\s*руб\.?\s*/\s*сеанс")


def _gololed_kind(slug: str) -> str | None:
    if slug in _GOLOLED_KINDS:
        return _GOLOLED_KINDS[slug]
    if slug.startswith(_GOLOLED_FIGURE_PREFIX):
        return PARSER_KIND_FIGURE_FREE
    return None


def _gololed_text(html: str | None) -> str:
    return re.sub(r"\s+", " ", strip_tags(html or "")).replace("\xa0", " ")


def _rub(raw: str) -> int:
    return int(raw.replace(" ", ""))


def gololed_public_prices(html: str | None) -> dict[int, int]:
    """Session duration in minutes → adult ticket, RUB."""
    prices: dict[int, int] = {}
    for amount, extra_minutes in _GOLOLED_PRICE_BY_DURATION.findall(_gololed_text(html)):
        prices.setdefault(60 + int(extra_minutes or 0), _rub(amount))
    return prices


def gololed_flat_price(html: str | None) -> int | None:
    match = _GOLOLED_FLAT_PRICE.search(_gololed_text(html))
    return _rub(match.group(1)) if match else None


async def _optional_page(job: ParserJob, *, filename: str, url_key: str) -> str | None:
    if job.config.get("fixture_dir"):
        try:
            return await load_source_text(job, filename=filename)
        except FileNotFoundError:
            return None
    url = job.config.get(url_key)
    return await fetch_http_text_optional(str(url)) if url else None


class GololedHtmlParser(IceParser):
    """СК «Гололёд» (spb-gololed.md, arena_id=178).

    The home page renders an 8-day schedule widget (``#schedule_for_all_component``);
    every session cell carries ``data-activity_slug``, ``data-start_ts`` (unix
    seconds), ``data-start_date`` ("09 ноября 10:15"), ``data-end_date`` ("11:15")
    and ``data-session_id``. The calendar date comes from ``data-start_ts`` and the
    human label must agree with it, otherwise the cell is dropped — a mismatch
    means the widget changed meaning, and guessing would publish wrong times.

    A page without the widget marker raises: that is a layout change, not an
    empty schedule. Unknown activity slugs are skipped (not coerced to public
    skating). Prices come from the two service pages and are optional: a failed
    fetch leaves them ``None`` instead of failing the run.
    """

    parser_key = "gololed_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="index.html", url_keys=("url",))
        if _GOLOLED_SCHEDULE_MARKER not in html:
            raise ValueError("gololed: schedule widget #schedule_for_all_component not found")
        tz = ZoneInfo(str(job.config.get("timezone") or "Europe/Moscow"))
        public_prices = gololed_public_prices(
            await _optional_page(job, filename="massovye-kataniya.html", url_key="public_skate_url")
        )
        hockey_price = gololed_flat_price(await _optional_page(job, filename="chas-hokkeya.html", url_key="hockey_url"))

        slots: list[ExtractedSlot] = []
        seen: set[str] = set()
        for match in _GOLOLED_CELL.finditer(html):
            attrs = {key: unescape(value).strip() for key, value in _GOLOLED_ATTR.findall(match.group(1))}
            kind = _gololed_kind(attrs.get("activity_slug", ""))
            if kind is None:
                continue
            session_id = attrs.get("session_id", "")
            if session_id and session_id in seen:
                continue
            try:
                starts = datetime.fromtimestamp(int(attrs["start_ts"]), tz)
            except (KeyError, ValueError, OverflowError):
                continue
            label = _GOLOLED_START_LABEL.search(attrs.get("start_date", ""))
            if not label or (int(label.group(1)), int(label.group(2))) != (starts.hour, starts.minute):
                continue
            end = _GOLOLED_HHMM.match(attrs.get("end_date", ""))
            if not end:
                continue
            end_hhmm = f"{int(end.group(1)):02d}:{end.group(2)}"
            duration = (int(end.group(1)) * 60 + int(end.group(2))) - (starts.hour * 60 + starts.minute)
            if duration <= 0:
                duration += 24 * 60
            if kind == PARSER_KIND_PUBLIC_SKATE:
                price = public_prices.get(duration)
            elif kind == PARSER_KIND_HOCKEY_PRACTICE:
                price = hockey_price
            else:
                price = None
            seen.add(session_id)
            slots.append(
                ExtractedSlot(
                    local_date=starts.date().isoformat(),
                    starts_at_local=starts.strftime("%H:%M"),
                    ends_at_local=end_hhmm,
                    kind_raw=kind,
                    price_adult=price,
                    source_id=f"gololed:{session_id}" if session_id else None,
                    session_label=attrs.get("title") or None,
                    external_url=attrs.get("service_url") or None,
                )
            )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)
