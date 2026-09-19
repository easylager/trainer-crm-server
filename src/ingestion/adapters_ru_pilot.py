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
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.ingestion.normalize import parse_price_to_minor
from src.ingestion.parsers import IceParser
from src.ingestion.source_io import fetch_http_json, fetch_http_text, load_source_json, load_source_text
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


# --- spb-baltic-arena -------------------------------------------------------

_BALTIC_TIME = re.compile(r"(\d{1,2}):(\d{2})[-:](\d{1,2}):(\d{2})")
_BALTIC_DURATION_PRICE_MINOR = {60: 70000, 75: 85000}


class BalticArenaHtmlParser(IceParser):
    """Балтик Арена, СПб, Василеостровский намыв (spb-baltic-arena.md, arena_id=192).

    Tilda ``t431`` table widget: the visible table is JS-rendered from two
    hidden ``display:none`` divs shipped in the raw HTML — ``t431__data-part1``
    (weekday names, then a semicolon-separated ``DD.MM`` date row) and
    ``t431__data-part2`` (one line per time-slot row, semicolon-separated,
    positionally aligned with the date row; a day with no session that row
    is an empty field, and trailing empty days are simply omitted from the
    line rather than kept as trailing semicolons). Verified against the
    live-rendered ``<table>`` via a real browser — position-to-day mapping
    is exact, including that trailing-omission behavior.

    No year printed (only ``DD.MM``) — ``run_year`` in job.config, same
    convention as ``LedovyyDvoretsHtmlParser``. Price is derived from session
    duration via the page's own legend (60 мин → 700 ₽, 75 мин → 850 ₽ at
    the time of the research snapshot) rather than printed per-slot; both
    figures live in job.config so a price change doesn't need a code
    deploy. One observed typo in the source (``22:15:23:15`` — colon instead
    of dash before the end time) — ``_BALTIC_TIME`` accepts either separator.
    No child or rental price is published for mass skating specifically
    (the 6 000–8 000 ₽ figures on the page are private hockey-hour ice
    rental, a different product) — both stay ``None``.
    """

    parser_key = "balticarena_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        text = await load_source_text(job, filename="mass-skating.html", url_keys=("url",))
        year = int(job.config.get("run_year") or date.today().year)
        duration_prices = {
            int(k): int(v)
            for k, v in (job.config.get("duration_price_minor") or _BALTIC_DURATION_PRICE_MINOR).items()
        }

        part1 = _tilda_hidden_div(text, "t431__data-part1")
        part2 = _tilda_hidden_div(text, "t431__data-part2")
        date_line = part1.splitlines()[1] if len(part1.splitlines()) > 1 else ""
        day_tokens = [tok.strip() for tok in date_line.split(";") if tok.strip()]
        local_dates: list[str] = []
        for tok in day_tokens:
            day_str, month_str = tok.split(".")
            local_dates.append(date(year, int(month_str), int(day_str)).isoformat())

        slots: list[ExtractedSlot] = []
        for line in part2.splitlines():
            cells = line.split(";")
            for i, cell in enumerate(cells):
                cell = cell.strip()
                if not cell or i >= len(local_dates):
                    continue
                match = _BALTIC_TIME.match(cell)
                if not match:
                    continue
                sh, sm, eh, em = match.groups()
                start = f"{int(sh):02d}:{sm}"
                end = f"{int(eh):02d}:{em}"
                duration = (int(eh) * 60 + int(em)) - (int(sh) * 60 + int(sm))
                slots.append(
                    ExtractedSlot(
                        local_date=local_dates[i],
                        starts_at_local=start,
                        ends_at_local=end,
                        kind_raw="public_skate",
                        price_adult=duration_prices.get(duration),
                        price_child=None,
                        price_rental=None,
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=text, slots=slots)


def _tilda_hidden_div(text: str, class_name: str) -> str:
    marker = f'class="{class_name}"'
    idx = text.find(marker)
    if idx == -1:
        return ""
    start = text.find(">", idx) + 1
    end = text.find("</div>", start)
    return text[start:end] if end != -1 else text[start:]


# --- spb-iceburg-arena -------------------------------------------------------

_MK_SERVICE_TITLE = "Массовое катание"


class IceburgArenaJsonParser(IceParser):
    """Айсбург Арена, СПб, Парашютная ул. 11 (spb-iceburg-arena.md, arena_id=193).

    Unlike every other RU-pilot adapter, this one is a genuine public JSON API,
    not HTML scraping: yclients' `client.booking` widget calls
    ``GET https://api.yclients.ru/api/v1/activity/{company_id}/search
    ?from=YYYY-MM-DD&weekly_schedule=1&page=1&count=50`` with a fixed,
    non-company-specific ``Authorization: Bearer`` app token (confirmed working
    from a plain curl with no cookies/session — this is the widget's public
    client token, not a per-company secret). ``count=50`` covers a full
    7-day window from ``from``.

    The endpoint returns every bookable activity at the venue (private hour
    rentals, figure-skating hours, group fitness, ...), not just public
    skating — filtered here to ``service.title == "Массовое катание"`` only,
    matching the project convention that private/training bookings never
    become ``ice_sessions`` rows (see ``test_minsk_adapters.py`` AC-003 for
    the same rule on the BY side). ``Ночное катание`` (night skating) looks
    like it might also be public-facing but wasn't in scope for this pass —
    flagged as a follow-up, not guessed into ``public_skate``.

    Price is in whole currency units in the API (``price_min``/``price_max``
    on the nested `service`, `900` not `90000`) — multiplied by 100 here,
    unlike the HTML adapters which read already-minor job.config constants.
    No child or rental price is exposed by this endpoint for mass skating.

    Unlike every other adapter's ``url``, this one takes a ``?from=YYYY-MM-DD``
    query param that must advance every run — a static job.config URL would
    fetch the same stale week forever. ``extract()`` builds the URL itself
    from ``company_id`` + "today" in Europe/Moscow (the venue's own
    timezone, not server-local) at fetch time; ``job.config["url"]`` is only
    a fallback base for local/manual runs and is never dated.
    """

    parser_key = "iceburgarena_yclients_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        if job.config.get("fixture_dir"):
            raw = await load_source_json(job, filename="activity-search.json", url_keys=("url",))
        else:
            company_id = job.config.get("company_id")
            today = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
            url = (
                f"https://api.yclients.ru/api/v1/activity/{company_id}/search"
                f"?from={today}&weekly_schedule=1&page=1&count=50"
            )
            raw = await fetch_http_json(
                url, headers={"Authorization": f"Bearer {job.config.get('bearer_token')}"}
            )
        activities = raw.get("data") or []
        slots: list[ExtractedSlot] = []
        for item in activities:
            service = item.get("service") or {}
            if service.get("title") != _MK_SERVICE_TITLE:
                continue
            date_str = str(item.get("date") or "")
            if not date_str:
                continue
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            length_seconds = int(item.get("length") or 0)
            end_dt = dt + timedelta(seconds=length_seconds)
            price = service.get("price_min")
            slots.append(
                ExtractedSlot(
                    local_date=dt.date().isoformat(),
                    starts_at_local=dt.strftime("%H:%M"),
                    ends_at_local=end_dt.strftime("%H:%M"),
                    kind_raw="public_skate",
                    price_adult=parse_price_to_minor(price, already_minor=False) if price is not None else None,
                    price_child=None,
                    price_rental=None,
                    source_id=str(item.get("id")) if item.get("id") is not None else None,
                )
            )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=raw, slots=slots)


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
