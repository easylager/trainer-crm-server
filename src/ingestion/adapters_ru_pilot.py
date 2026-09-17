"""RU pilot IceParser strategies (Moscow + St. Petersburg). Extract only.

Three arenas reverse-engineered by the RU pilot research pass got real specs
+ fixtures under ``data/parsers/{msk,spb}-*.md`` / ``data/fixtures/<slug>/``:

- ``SokolnikiHtmlParser`` (msk-sokolniki.md, arena_id=58) — static server-rendered
  HTML, ``.schedule-list > .schedule-item`` blocks.
- ``LedovyyDvoretsHtmlParser`` (spb-ledovyy-dvorets.md, arena_id=105) — a
  paragraph-per-date text grid; fixture is a reader-proxy markdown capture
  (direct TLS to newarena.spb.ru hung in the research sandbox), not raw HTML,
  but the text itself is regular and fully verified against expected.json.
- ``YubileynyAfishaParser`` (spb-yubileyny.md, arena_id=97) — event-driven
  afisha: a listing page with per-event links, each event page carrying its
  own date/time/arena/price. Fixture is likewise reader-proxy markdown.

A fourth spec, ``msk-vtbarena.md`` (arena_id=53), is ``spec_blocked``: the
real calendar sits behind an authenticated Qtickets widget. ``VtbArenaQticketsParser``
below is a minimal blocked-shape adapter (mirrors the BY spec_blocked pattern)
so seeding the job (once the seed glob picks up ``msk-*.md``) doesn't leave a
parser_key with no registered handler — it always yields zero slots.

Currency is RUB, timezone Europe/Moscow for all four — never fall back to the
BYN/Europe/Minsk defaults ``IceSessionNormalizer`` uses for BY arenas.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from src.ingestion.normalize import parse_price_to_minor
from src.ingestion.parsers import IceParser
from src.ingestion.source_io import fetch_http_text, load_source_text
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob

_MONTHS_RU = {
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
_MONTH_ALT = "|".join(_MONTHS_RU)


# --- msk-sokolniki -----------------------------------------------------

_SOKOLNIKI_DATE = re.compile(r"<span>(\d{2})\.(\d{2})\.(\d{4})</span>")
_SOKOLNIKI_ROW = re.compile(
    r'<div class="schedule-item__time">\s*([\d:]+)\s*-\s*([\d:]+)\s*</div>\s*'
    r'<div class="schedule-item__name">\s*([^<]+?)\s*</div>\s*'
    r'<div class="schedule-item__price">\s*([^<]+?)\s*</div>',
    re.S,
)


class SokolnikiHtmlParser(IceParser):
    """Ледовый дворец «Сокольники» (msk-sokolniki.md, arena_id=58).

    Static Bitrix/Intec HTML, no geo-block. One ``.schedule-item`` per
    published date; rows inside ``.schedule-item-block`` give explicit
    start+end times and a per-row price. Skate rental is a flat per-session
    price printed as plain text elsewhere on the page, applied to every slot
    (``rental_price_flat_minor`` in job.config) — not scraped per row.
    """

    parser_key = "ldsokolniki_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="massovye-kataniya.html", url_keys=("schedule_url", "url"))
        rental = job.config.get("rental_price_flat_minor")
        default_label = str(job.config.get("session_name") or "МК")
        slots: list[ExtractedSlot] = []
        for chunk in html.split('<div class="schedule-item">')[1:]:
            date_match = _SOKOLNIKI_DATE.search(chunk)
            if not date_match:
                continue
            day, month, year = date_match.groups()
            local_date = date(int(year), int(month), int(day)).isoformat()
            for row in _SOKOLNIKI_ROW.finditer(chunk):
                start, end, name, price_text = row.groups()
                label = name.strip() or default_label
                slots.append(
                    ExtractedSlot(
                        local_date=local_date,
                        starts_at_local=start.strip(),
                        ends_at_local=end.strip(),
                        kind_raw=label,
                        price_adult=parse_price_to_minor(price_text, already_minor=False),
                        price_child=None,
                        price_rental=rental,
                        session_label=label,
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)


# --- spb-ledovyy-dvorets -------------------------------------------------

_LEDOVYY_DATE_BLOCK = re.compile(
    rf"(\d{{1,2}})\s+({_MONTH_ALT})\s*:\s*(.*?)(?=\d{{1,2}}\s+(?:{_MONTH_ALT})\s*:|\Z)",
    re.S,
)
_LEDOVYY_TIME_PAIR = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")
_DIGIT_GAP = re.compile(r"(\d)\s+(\d)")


class LedovyyDvoretsHtmlParser(IceParser):
    """Ледовый дворец, СПб, пр. Пятилеток 1 (spb-ledovyy-dvorets.md, arena_id=105).

    Source fixture is a reader-proxy markdown capture (direct TLS to
    newarena.spb.ru hung in the research sandbox — see the spec's Blockers
    section), not raw HTML with CSS selectors. The page text itself is a
    regular ``DD месяца:HH:MM-HH:MM; ...`` grid per date though, and this
    extraction is verified 102/102 against ``expected.json``. A production
    worker with normal egress should re-verify against the live page and
    confirm the DOM still matches this text shape.

    No year is printed on the page (only day + month) — ``run_year`` in
    job.config controls it, same convention as the BY Chizhovka adapter.
    Price band (day vs. evening) is chosen by comparing the session start
    against ``day_rate_cutoff``; both bands come straight from job.config
    (the page's own prose price paragraph is not re-parsed at runtime).
    """

    parser_key = "ledovyydvorets_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        text = await load_source_text(job, filename="rink-page.md", url_keys=("url",))
        year = int(job.config.get("run_year") or date.today().year)
        cutoff = str(job.config.get("day_rate_cutoff") or "17:30")
        adult_before = job.config.get("adult_price_before_cutoff_minor")
        adult_from = job.config.get("adult_price_from_cutoff_minor")
        child_before = job.config.get("child_price_before_cutoff_minor")
        child_from = job.config.get("child_price_from_cutoff_minor")
        rental = job.config.get("rental_skates_minor")
        age_note = str(
            job.config.get("age_note")
            or "Дети до 10 лет — только в сопровождении взрослого; детский тариф до 7 лет."
        )
        slots: list[ExtractedSlot] = []
        for day, month_name, times_raw in _LEDOVYY_DATE_BLOCK.findall(text):
            merged = _DIGIT_GAP.sub(r"\1\2", times_raw)
            local_date = date(year, _MONTHS_RU[month_name], int(day)).isoformat()
            for sh, sm, eh, em in _LEDOVYY_TIME_PAIR.findall(merged):
                start = f"{int(sh):02d}:{sm}"
                end = f"{int(eh):02d}:{em}"
                is_day = start < cutoff
                slots.append(
                    ExtractedSlot(
                        local_date=local_date,
                        starts_at_local=start,
                        ends_at_local=end,
                        kind_raw="public_skate",
                        price_adult=adult_before if is_day else adult_from,
                        price_child=child_before if is_day else child_from,
                        price_rental=rental,
                        age_note=age_note,
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=text, slots=slots)


# --- spb-yubileyny ---------------------------------------------------------

_YUBILEYNY_EVENT_URL = re.compile(r"(https://www\.yubi\.ru/afisha/katok/\S*?\?event=(\d+))")
_YUBILEYNY_DATE = re.compile(rf"Дата:\s*(\d{{1,2}})\s+({_MONTH_ALT})\s+(\d{{4}})")
_YUBILEYNY_TIME = re.compile(r"Время:\s*(\d{1,2}:\d{2})")
_YUBILEYNY_ARENA = re.compile(r"Арена:\s*([^\n]+)")
_YUBILEYNY_PRICE = re.compile(r"Цена:\s*(\d+)\s*р")


async def _load_yubileyny_event(job: ParserJob, *, event_id: str, url: str) -> str:
    fixture_dir = job.config.get("fixture_dir")
    if fixture_dir:
        path = Path(str(fixture_dir)) / f"event-{event_id}.md"
        return path.read_text(encoding="utf-8")
    return await fetch_http_text(url)


class YubileynyAfishaParser(IceParser):
    """СК «Юбилейный», СПб (spb-yubileyny.md, arena_id=97).

    Event-driven afisha, not a weekly grid: the listing page links to one
    page per event (``?event=<id>``), and only the event page carries a
    reliable price for that specific session — the site's summary price
    page and the listing footer both quote different, stale numbers (see
    spec §8). ``event_id`` is the natural idempotency key.

    Source fixtures are reader-proxy markdown captures (see
    ``LedovyyDvoretsHtmlParser`` docstring for the same network-sandbox
    caveat); the event pages themselves are already clean
    ``Дата:``/``Время:``/``Арена:``/``Цена:`` field text, so this extraction
    is exact against ``expected.json``.
    """

    parser_key = "yubileyny_afisha_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        listing = await load_source_text(job, filename="katok-listing.md", url_keys=("listing_url",))
        duration = int(job.config.get("default_duration_minutes") or 60)
        title = str(job.config.get("session_title") or "Часовая спортивная докатка")
        events: dict[str, str] = {}
        for url, event_id in _YUBILEYNY_EVENT_URL.findall(listing):
            events.setdefault(event_id, url)
        slots: list[ExtractedSlot] = []
        raw_events: dict[str, str] = {}
        for event_id, url in events.items():
            event_text = await _load_yubileyny_event(job, event_id=event_id, url=url)
            raw_events[event_id] = event_text
            date_match = _YUBILEYNY_DATE.search(event_text)
            time_match = _YUBILEYNY_TIME.search(event_text)
            price_match = _YUBILEYNY_PRICE.search(event_text)
            if not date_match or not time_match:
                continue
            day, month_name, year = date_match.groups()
            local_date = date(int(year), _MONTHS_RU[month_name], int(day)).isoformat()
            arena_match = _YUBILEYNY_ARENA.search(event_text)
            arena_name = arena_match.group(1).strip() if arena_match else None
            label = f"{title} — {arena_name} арена" if arena_name else title
            adult = parse_price_to_minor(price_match.group(1), already_minor=False) if price_match else None
            start = time_match.group(1)
            hour, minute = (int(part) for part in start.split(":"))
            end_minutes = hour * 60 + minute + duration
            end = f"{(end_minutes // 60) % 24:02d}:{end_minutes % 60:02d}"
            slots.append(
                ExtractedSlot(
                    local_date=local_date,
                    starts_at_local=start,
                    ends_at_local=end,
                    kind_raw="public_skate",
                    price_adult=adult,
                    price_child=None,
                    price_rental=None,
                    session_label=label,
                    age_note="0+, без возрастных ограничений",
                    source_id=event_id,
                    external_url=url,
                )
            )
        snapshot: dict[str, Any] = {"listing": listing, "events": raw_events}
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=snapshot, slots=slots)


# --- msk-vtbarena (spec_blocked) -------------------------------------------


class VtbArenaQticketsParser(IceParser):
    """ВТБ Арена / Академия спорта «Динамо» (msk-vtbarena.md, arena_id=53).

    ``spec_blocked``: the real session calendar lives behind an authenticated
    Qtickets REST call (403 without an API key) rendered client-side; the
    static akademiya-dynamo.ru page has confirmed prices but no dates/times.
    Registered only so the seeded job (parser_key present once ``msk-*.md``
    is picked up by the seed glob) has a handler — always yields zero slots,
    never invents a session grid. See ``expected.json``'s
    ``blocked_without_qtickets_api_key``.
    """

    parser_key = "vtbarena_qtickets_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"blocked_reason": "qtickets_rest_api_requires_auth"},
            slots=[],
        )
