"""SPb batch P IceParser strategy. Extract only.

- ``GololedHtmlParser`` (spb-gololed.md, arena_id=178) — СК «Гололёд»,
  Красное Село. Server-rendered schedule widget with one ``schedule_td`` cell
  per session carrying machine-readable ``data-*`` attributes.
- ``AysGradHtmlParser`` (spb-ays-grad.md, arena_id=188) — Айс Град, парк
  Бабушкина. LPgenerator page, one text block per day; mass skating is an open
  window with an hourly ticket.

Currency is RUB, timezone Europe/Moscow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from src.ingestion.dates import infer_date_from_day_month, parser_reference_date
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


# --- spb-ays-grad -----------------------------------------------------------

_MONTHS_GEN = {
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
_WEEKDAYS = {
    "понедельник": 0,
    "вторник": 1,
    "среда": 2,
    "четверг": 3,
    "пятница": 4,
    "суббота": 5,
    "воскресенье": 6,
}
_VOID_TAGS = frozenset(
    {"br", "img", "input", "meta", "link", "hr", "source", "area", "base", "col", "embed", "param", "track", "wbr"}
)
_TOP_PX = re.compile(r"(?:^|;)\s*top:\s*(-?\d+)px")
_AYS_DAY = re.compile(
    r"^(\d{1,2})\s+(" + "|".join(_MONTHS_GEN) + r")\s+(" + "|".join(_WEEKDAYS) + r")\b(.*)$",
    re.I | re.S,
)
_AYS_RANGE = re.compile(r"(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})")
_AYS_NIGHT = re.compile(r"ночн\w*\s+катани\w*", re.I)
_AYS_PUBLIC_HEADING = re.compile(r"расписание\s+массовых\s+катаний", re.I)
_AYS_HOCKEY_HEADING = re.compile(r"час\s+хоккея\s*[-–—]\s*расписание", re.I)
# Day blocks sit in one row right under their heading (≈60px on the 2026-11 layout).
_AYS_SECTION_BAND_PX = 400


class _LpBlocks(HTMLParser):
    """LPgenerator page → text of every ``div.block`` with its ``top`` in px (None if unset)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, str | None, int | None]] = []
        self.blocks: dict[str, list[str]] = {}
        self.tops: dict[str, int | None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID_TAGS:
            return
        attr = dict(attrs)
        block_id = attr.get("id") if "block" in (attr.get("class") or "").split() else None
        top = _TOP_PX.search(attr.get("style") or "")
        top_px = int(top.group(1)) if top else None
        if block_id:
            self.tops.setdefault(block_id, top_px)
        self._stack.append((tag, block_id, top_px))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if not data.strip() or any(tag in ("script", "style") for tag, _, _ in self._stack):
            return
        for _, block_id, _ in reversed(self._stack):
            if block_id:
                self.blocks.setdefault(block_id, []).append(data.strip())
                return


def lp_text_blocks(html: str) -> list[tuple[int | None, str]]:
    parser = _LpBlocks()
    parser.feed(html)
    return [
        (parser.tops.get(block_id), re.sub(r"\s+", " ", " ".join(parts)).replace("\xa0", " ").strip())
        for block_id, parts in parser.blocks.items()
    ]


def _block_with(blocks: list[tuple[int | None, str]], *needles: str) -> str | None:
    for _, text in blocks:
        low = text.lower()
        if all(needle in low for needle in needles):
            return text
    return None


def _first_rub(pattern: str, text: str | None) -> int | None:
    match = re.search(pattern, text or "", re.I)
    return _rub(match.group(1)) if match else None


@dataclass(frozen=True)
class AysGradPrices:
    adult_hour: int | None
    child_hour: int | None
    adult_rental_hour: int | None
    child_rental_hour: int | None
    child_age_note: str | None
    night_own: int | None
    night_rental: int | None
    night_cash_only: bool
    hockey: int | None


def ays_grad_prices(blocks: list[tuple[int | None, str]]) -> AysGradPrices:
    own = _block_with(blocks, "со своими коньками", "р./час")
    rental = _block_with(blocks, "с прокатом коньков", "р./час")
    night = _block_with(blocks, "за всю ночь")
    hockey = _block_with(blocks, "час хоккея", "руб")
    age = next((text for _, text in blocks if re.fullmatch(r"\*\s*до\s+\d{1,2}\s+лет", text, re.I)), None)
    return AysGradPrices(
        adult_hour=_first_rub(r"(\d[\d ]{1,5})\s*р\./час\s+за\s+взрослый", own),
        child_hour=_first_rub(r"(\d[\d ]{1,5})\s*р\./час\s+за\s+детский", own),
        adult_rental_hour=_first_rub(r"(\d[\d ]{1,5})\s*р\./час\s+за\s+взрослый", rental),
        child_rental_hour=_first_rub(r"(\d[\d ]{1,5})\s*р\./час\s+за\s+детский", rental),
        child_age_note=f"Детский — {age.lstrip('* ').lower()}" if age else None,
        night_own=_first_rub(r"(\d[\d ]{1,5})\s*руб\.?\s*[-–—]\s*со\s+своими", night),
        night_rental=_first_rub(r"(\d[\d ]{1,5})\s*руб\.?\s*[-–—]\s*с\s+прокатом", night),
        night_cash_only=bool(night and re.search(r"только\s+в\s+кассе", night, re.I)),
        hockey=_first_rub(r"час\s+хоккея\s*[-–—]\s*(\d[\d ]{1,5})\s*руб", hockey),
    )


def _tiers(*pairs: tuple[str, int | None]) -> list[dict] | None:
    tiers = [{"label": label, "minor": amount * 100} for label, amount in pairs if amount]
    return tiers or None


class AysGradHtmlParser(IceParser):
    """Айс Град, каток в парке Бабушкина (spb-ays-grad.md, arena_id=188).

    LPgenerator page: every day is its own absolutely positioned text block
    («09 НОЯБРЯ ПОНЕДЕЛЬНИК 11:45-16:30»). Mass-skating and hockey-hour days look
    identical and are interleaved in the DOM, so the section is decided by the
    nearest heading above the block («РАСПИСАНИЕ МАССОВЫХ КАТАНИЙ» / «ЧАС ХОККЕЯ -
    расписание»), within a short band. Guards that make a wrong slot impossible
    rather than unlikely:

    - either heading missing → raise (layout changed);
    - the printed weekday must match the inferred date, else the day is skipped;
    - the same date twice in one section → raise (ambiguous);
    - mass skating is an *open window* with an hourly ticket: the slot carries
      ``price_note`` only when the page still says «р./час»; night windows only
      when it still says «за всю ночь». Without the note the validator drops a
      long window instead of showing «600 ₽» for five hours.
    """

    parser_key = "aysgrad_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="index.html", url_keys=("url",))
        blocks = lp_text_blocks(html)
        headings: list[tuple[int, str]] = []
        for top, text in blocks:
            if top is None:
                continue
            if _AYS_PUBLIC_HEADING.search(text):
                headings.append((top, PARSER_KIND_PUBLIC_SKATE))
            elif _AYS_HOCKEY_HEADING.search(text):
                headings.append((top, PARSER_KIND_HOCKEY_PRACTICE))
        kinds_found = {kind for _, kind in headings}
        if kinds_found != {PARSER_KIND_PUBLIC_SKATE, PARSER_KIND_HOCKEY_PRACTICE}:
            raise ValueError(f"ays-grad: schedule headings not found ({sorted(kinds_found)})")
        headings.sort()
        prices = ays_grad_prices(blocks)
        reference = parser_reference_date(job.config)

        slots: list[ExtractedSlot] = []
        seen_days: set[tuple[str, date]] = set()
        for top, text in blocks:
            day = _AYS_DAY.match(text)
            if day is None or top is None:
                continue
            above = [(h_top, kind) for h_top, kind in headings if h_top <= top]
            if not above or top - above[-1][0] > _AYS_SECTION_BAND_PX:
                continue
            kind = above[-1][1]
            local = infer_date_from_day_month(int(day.group(1)), _MONTHS_GEN[day.group(2).lower()], reference)
            if local is None or local.weekday() != _WEEKDAYS[day.group(3).lower()]:
                continue
            if (kind, local) in seen_days:
                raise ValueError(f"ays-grad: {local.isoformat()} listed twice in {kind}")
            seen_days.add((kind, local))
            slots.extend(self._day_slots(kind, local, day.group(4), prices))
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)

    @staticmethod
    def _day_slots(kind: str, local: date, tail: str, prices: AysGradPrices) -> list[ExtractedSlot]:
        out: list[ExtractedSlot] = []
        cursor = 0
        for match in _AYS_RANGE.finditer(tail):
            night = bool(_AYS_NIGHT.search(tail[cursor : match.start()]))
            cursor = match.end()
            start = f"{int(match.group(1)):02d}:{match.group(2)}"
            end = f"{int(match.group(3)):02d}:{match.group(4)}"
            common = {"local_date": local.isoformat(), "starts_at_local": start, "ends_at_local": end}
            if kind == PARSER_KIND_HOCKEY_PRACTICE:
                out.append(ExtractedSlot(kind_raw=kind, price_adult=prices.hockey, **common))
            elif night:
                note = None
                if prices.night_own:
                    note = "Билет на всю ночь катаний"
                    if prices.night_cash_only:
                        note += ", только в кассе катка"
                out.append(
                    ExtractedSlot(
                        kind_raw=kind,
                        session_label="Ночное катание",
                        price_adult=prices.night_own,
                        price_tiers=_tiers(("С прокатом", prices.night_rental)),
                        price_note=note,
                        **common,
                    )
                )
            else:
                hourly = prices.adult_hour is not None
                out.append(
                    ExtractedSlot(
                        kind_raw=kind,
                        price_adult=prices.adult_hour,
                        price_child=prices.child_hour,
                        price_tiers=_tiers(
                            ("Взрослый с прокатом", prices.adult_rental_hour),
                            ("Детский с прокатом", prices.child_rental_hour),
                        ),
                        age_note=prices.child_age_note,
                        price_note=f"Билет на 1 час, вход в любое время с {start} до {end}" if hourly else None,
                        **common,
                    )
                )
        return out
