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

import html as html_lib
import json
import re
import urllib.parse
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


# --- spb-grand-canyon-ice ---------------------------------------------------

_GRANDICE_FREE_SKATE_TYPE = "Свободное катание"


class GrandCanyonIceJsonParser(IceParser):
    """ЛД «Гранд Каньон Айс», СПб (spb-grand-canyon-ice.md, arena_id=99).

    A genuine public JSON API, no auth: ``GET https://cp.grand-ice.ru/api/schedules``
    returns every published schedule entry — mixing ``"Свободное катание"``
    with ``"Секция"``/``"Мероприятие"`` entries that carry no price and an
    explicit ``"Свободного катания нет"`` note in ``schedule_time[].notes`` —
    filtered here to ``schedule_type.name == "Свободное катание"`` only, same
    rule as every other RU-pilot adapter never turning a non-public-skate
    activity into a catalog session. One entry per date; ``price`` is a
    single flat decimal-string figure for that whole date (e.g. ``"750.00"``,
    whole rubles not minor units) applied to every nested ``schedule_time``
    row for that date — there's no per-slot price in the source.

    The endpoint takes no query params and just returns whatever the admin
    has currently published (a rolling few weeks, mixing already-past and
    future dates in the 2026-09-19 snapshot) — ``IceSessionNormalizer``'s own
    ``ends_at_utc <= now`` filter naturally drops the past ones, so no date
    filtering is needed in ``extract()`` itself.
    """

    parser_key = "grandice_json_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        raw = await load_source_json(job, filename="schedules.json", url_keys=("url",))
        schedules = (raw.get("data") or {}).get("schedules") or []
        slots: list[ExtractedSlot] = []
        for entry in schedules:
            schedule_type = (entry.get("schedule_type") or {}).get("name")
            if schedule_type != _GRANDICE_FREE_SKATE_TYPE:
                continue
            local_date = str(entry.get("date") or "")
            if not local_date:
                continue
            price = parse_price_to_minor(entry.get("price"), already_minor=False)
            for row in entry.get("schedule_time") or []:
                start = str(row.get("time_start") or "")[:5]
                end = str(row.get("time_end") or "")[:5]
                if not start or not end:
                    continue
                slots.append(
                    ExtractedSlot(
                        local_date=local_date,
                        starts_at_local=start,
                        ends_at_local=end,
                        kind_raw="public_skate",
                        price_adult=price,
                        price_child=None,
                        price_rental=None,
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=raw, slots=slots)


# --- spb-ozerki ---------------------------------------------------------

_OZERKI_FREE_SKATE = "Свободное катание"


class OzerkiCalendarParser(IceParser):
    """Ледовая арена «Озерки», СПб (spb-ozerki.md, arena_id=101).

    Two independent ice rinks (Большая/Малая арена), each with its own public
    Google Calendar — API key and calendar id are both shipped in the site's
    own page JS (a FullCalendar ``googleCalendarApiKey``/``googleCalendarId``
    config), not secret. Each rink's calendar is actually two merged event
    sources in the widget: a default, unlabeled one (the site's own hourly
    *rental* booking form marking busy/occupied time — no ``summary``) and a
    second, explicitly-colored one carrying the real public schedule with
    ``summary`` set to either ``"Свободное катание"`` or ``"Час хоккея"``.
    Only ``summary.strip() == "Свободное катание"`` becomes a slot — same
    "public skate only" rule as every other RU-pilot adapter (see
    ``IceburgArenaJsonParser``); ``"Час хоккея"`` is a different product.

    Prices aren't in the calendar at all — they're flat, one per rink, read
    from ``job.config["rinks"][i]["price_adult_minor"]`` (the page's own
    static prose price paragraph, 500 ₽ / 400 ₽ at capture time).

    Known limitation: ``IceSessionNormalizer`` dedupes slots by
    ``(local_date, starts_at_local)`` only, not per-rink — if both rinks ever
    publish a "Свободное катание" session at the exact same clock time on the
    same date, one would silently be dropped in favor of the other. Not
    observed in the 2026-09-19 snapshot (see spec's Verification section)
    but not structurally impossible; flagged rather than silently risked.
    """

    parser_key = "ozerki_gcal_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        rinks = job.config.get("rinks") or []
        fixture_dir = job.config.get("fixture_dir")
        api_key = job.config.get("google_api_key")
        horizon_days = int(job.config.get("horizon_days") or 7)
        tz = ZoneInfo(str(job.config.get("timezone") or "Europe/Moscow"))
        today = datetime.now(tz).date()
        time_min = datetime.combine(today, datetime.min.time(), tzinfo=tz).isoformat()
        time_max = datetime.combine(today + timedelta(days=horizon_days), datetime.min.time(), tzinfo=tz).isoformat()

        slots: list[ExtractedSlot] = []
        raw_by_rink: dict[str, Any] = {}
        for rink in rinks:
            code = str(rink.get("code") or rink.get("label") or "")
            if fixture_dir:
                path = Path(str(fixture_dir)) / str(rink["fixture_file"])
                raw = json.loads(path.read_text(encoding="utf-8"))
            else:
                calendar_id = urllib.parse.quote(str(rink["calendar_id"]), safe="")
                url = (
                    f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
                    f"?key={api_key}&timeMin={time_min}&timeMax={time_max}"
                    f"&singleEvents=true&orderBy=startTime&maxResults=250"
                )
                raw = await fetch_http_json(url)
            raw_by_rink[code] = raw
            price = rink.get("price_adult_minor")
            label = rink.get("label")
            for item in raw.get("items") or []:
                summary = str(item.get("summary") or "").strip()
                if summary != _OZERKI_FREE_SKATE:
                    continue
                start = (item.get("start") or {}).get("dateTime")
                end = (item.get("end") or {}).get("dateTime")
                if not start or not end:
                    continue
                event_id = item.get("id")
                slots.append(
                    ExtractedSlot(
                        local_date=start[:10],
                        starts_at_local=start[11:16],
                        ends_at_local=end[11:16],
                        kind_raw="public_skate",
                        price_adult=price,
                        price_child=None,
                        price_rental=None,
                        session_label=label,
                        source_id=f"{code}:{event_id}" if event_id else None,
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=raw_by_rink, slots=slots)


# --- spb-magnit-arena ---------------------------------------------------

_MAGNIT_SLOT = re.compile(r"(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})(?:\s*/\s*(\d+)\s*р)?")
_MAGNIT_DAY_TITLE = re.compile(r'\d+">(\d{1,2})\.(\d{1,2})')
_MAGNIT_DESCR = re.compile(r'li_descr__\d+"[^>]*>(.*?)</div>\s*</div>\s*</div>\s*</div>', re.S)


class MagnitArenaHtmlParser(IceParser):
    """Ледовая арена «Магнит», СПб, Магнитогорская ул. 51В
    (spb-magnit-arena.md, arena_id=187).

    Static Tilda accordion — the ``hidden`` attribute on the content div only
    hides it visually, the data is present in the raw HTML with no JS fetch
    needed. The site publishes TWO ice-rink weekly schedules on one page:
    "Ледовая Арена 1" is genuinely "массовое катание"; "Ледовая Арена 2" is
    "Час хоккея" (hockey-hour) — a different product, confirmed by its own
    per-day price line ("Час хоккея - 600 р. за сеанс") — never scraped here,
    same "public skate only" rule as ``IceburgArenaJsonParser``.

    Within Arena 1's day blocks, nearly every listed time is a flat
    ``base_price_adult_minor`` session (600 ₽ at capture time) except a
    subset individually marked inline ``/ NNN р.*`` (a 150 ₽ off-peak promo)
    — that marked price, when present, overrides the flat base. Rental is a
    flat per-session price printed as prose elsewhere on the page
    (``rental_price_flat_minor`` in job.config), same convention as
    ``SokolnikiHtmlParser``.

    No year is printed on the page (only ``DD.MM``) — ``run_year`` in
    job.config, same convention as ``LedovyyDvoretsHtmlParser``/
    ``BalticArenaHtmlParser``.
    """

    parser_key = "magnitarena_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        page_html = await load_source_text(job, filename="index.html", url_keys=("url",))
        year = int(job.config.get("run_year") or date.today().year)
        base_price = job.config.get("base_price_adult_minor")
        rental = job.config.get("rental_price_flat_minor")

        start_idx = page_html.find("Ледовая Арена 1")
        end_idx = page_html.find("Ледовая Арена 2", start_idx) if start_idx != -1 else -1
        chunk = page_html[start_idx:end_idx] if start_idx != -1 and end_idx != -1 else ""

        slots: list[ExtractedSlot] = []
        for day_block in chunk.split("li_title__")[1:]:
            title_match = _MAGNIT_DAY_TITLE.match(day_block)
            if not title_match:
                continue
            day, month = title_match.groups()
            local_date = date(year, int(month), int(day)).isoformat()
            descr_match = _MAGNIT_DESCR.search(day_block)
            if not descr_match:
                continue
            text = html_lib.unescape(re.sub(r"<[^>]+>", "", descr_match.group(1)))
            for slot_match in _MAGNIT_SLOT.finditer(text):
                start, end, discount = slot_match.groups()
                price = int(discount) * 100 if discount else base_price
                slots.append(
                    ExtractedSlot(
                        local_date=local_date,
                        starts_at_local=start,
                        ends_at_local=end,
                        kind_raw="public_skate",
                        price_adult=price,
                        price_child=None,
                        price_rental=rental,
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=page_html, slots=slots)


# --- spb-shans-arena ---------------------------------------------------

_SHANS_DAY = re.compile(
    r'<h3>([^<]+)<br>\s*(\d{2})\.(\d{2})\.(\d{4})</h3>(.*?)(?=<div class="scheduletableitem|\Z)', re.S
)
_SHANS_ITEM = re.compile(
    r'<div class="schitem\s+(\w+)">.*?<p>\s*(\d{2}:\d{2})\s*</p>.*?<p>\s*(\d{2}:\d{2})\s*</p>', re.S
)
_SHANS_MASS_KIND = "mass"


class ShansArenaHtmlParser(IceParser):
    """Ледовый комплекс «Шанс Арена», СПб (spb-shans-arena.md, arena_id=100).

    Static server-rendered HTML — a 14-day rolling schedule (``h3`` per day,
    full ``DD.MM.YYYY``) with each session tagged by an explicit CSS class:
    ``schitem mass`` (массовое катание), ``schitem hockey`` (час хоккея),
    ``schitem figure`` (час фигурного катания). **Filtered to ``mass`` only**
    — same "public skate only" rule as every other RU-pilot adapter. Unlike
    every other adapter here, the type discrimination is a real CSS class,
    not fragile text matching.

    Real source quirk: the first week's time cells print
    ``<p>start</p> - <p>end</p>`` (a literal dash between the two
    ``<p>`` tags); the second week omits the dash entirely
    (``<p>start</p><p>end</p>``, and ``schitemtime`` also loses its trailing
    class-name space) — the item regex uses two independent non-greedy
    ``.*?`` gaps rather than requiring the dash, so it matches both weeks.
    Not caught until a raw grep of "31 mass items on page" vs "15 matched"
    exposed the silent under-count — a reminder to verify counts, not just
    that a regex compiles.

    Price isn't printed inline on the schedule page — flat
    ``price_adult_minor``/``price_child_minor`` (900 ₽ each, identical) and
    ``price_rental_minor`` (600 ₽) come from job.config, read off the site's
    separate ``/services/ledovaya-arena/massovoe-katanie/`` price page.
    """

    parser_key = "shansarena_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="index.html", url_keys=("url",))
        adult = job.config.get("price_adult_minor")
        child = job.config.get("price_child_minor")
        rental = job.config.get("price_rental_minor")
        slots: list[ExtractedSlot] = []
        for _weekday, day, month, year, chunk in _SHANS_DAY.findall(html):
            local_date = date(int(year), int(month), int(day)).isoformat()
            for kind, start, end in _SHANS_ITEM.findall(chunk):
                if kind != _SHANS_MASS_KIND:
                    continue
                slots.append(
                    ExtractedSlot(
                        local_date=local_date,
                        starts_at_local=start,
                        ends_at_local=end,
                        kind_raw="public_skate",
                        price_adult=adult,
                        price_child=child,
                        price_rental=rental,
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)


# --- spb-parnas-arena ----------------------------------------------------

_PARNAS_DAY = re.compile(rf"([А-Яа-я]+),?\s*(\d{{1,2}})\s+({_MONTH_ALT})\n([^\n]*)")
_PARNAS_SLOT = re.compile(r"(\d{1,2})[.:](\d{2})\s*-\s*(\d{1,2})[.:](\d{2})(?:\((\d+)\s*р)?")


class ParnasArenaTextParser(IceParser):
    """Центр ледовых видов спорта «Парнас», СПб (spb-parnas-arena.md, arena_id=174).

    The homepage's own "Массовые катания" tab widget is broken — its
    ``aria-controls`` points at a ``rec850565068`` element id that doesn't
    exist anywhere in the DOM (confirmed via `page.evaluate`, not a
    hidden/lazy-load timing issue — waited and re-checked). The real content
    lives on a separate dedicated page, ``/massovie-kataniya``, which is also
    behind DDoS-Guard's bot challenge (plain `curl`/`aiohttp` get a 403 body
    inside a 200-wrapped response) — this fixture is a reader-proxy plain-text
    capture (`page.evaluate(() => document.body.innerText)` via a real
    browser), same convention as `LedovyyDvoretsHtmlParser`/
    `YubileynyAfishaParser`, not raw HTML with CSS selectors.

    Only ONE week is published at a time (no rolling horizon like
    `ShansArenaHtmlParser`) — ``run_year`` in job.config, same convention as
    `BalticArenaHtmlParser`. One real data quirk: the Saturday slot uses a
    dot separator for its start time (``20.30-22:30``) while every other slot
    uses a colon — the time regex accepts either. That same Saturday slot is
    inline-priced ``(900 р.дискотека на льду)`` — a themed "ice disco" event,
    still public and still "Массовые катания" per the page's own section
    heading, so it's kept, at its own price overriding the flat
    ``base_price_adult_minor``. That inline 900 ₽ **disagrees with** the
    page's separate "ЛЕДОВАЯ ДИСКОТЕКА" price-list entry (800 ₽) — the
    inline, date-specific figure is trusted over the generic price-list one,
    same precedence rule as `IceburgArenaJsonParser`'s docstring on stale
    summary numbers; flagged here rather than silently picking one.
    """

    parser_key = "parnasarena_text_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        text = await load_source_text(job, filename="schedule.md", url_keys=("url",))
        year = int(job.config.get("run_year") or date.today().year)
        base_price = job.config.get("base_price_adult_minor")
        rental = job.config.get("rental_price_flat_minor")
        slots: list[ExtractedSlot] = []
        for _weekday, day, month_name, line in _PARNAS_DAY.findall(text):
            local_date = date(year, _MONTHS_RU[month_name], int(day)).isoformat()
            for sh, sm, eh, em, discount in _PARNAS_SLOT.findall(line):
                price = int(discount) * 100 if discount else base_price
                slots.append(
                    ExtractedSlot(
                        local_date=local_date,
                        starts_at_local=f"{int(sh):02d}:{sm}",
                        ends_at_local=f"{int(eh):02d}:{em}",
                        kind_raw="public_skate",
                        price_adult=price,
                        price_child=None,
                        price_rental=rental,
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=text, slots=slots)


# --- spb-bugry-arena -------------------------------------------------------

_BUGRY_ROW = re.compile(
    r"<tr>\s*<td>\s*[А-Я]{2}\s*\((\d{2})\.(\d{2})\)\s*</td>\s*<td>\s*([^<]*)</td>\s*<td>\s*([^<]*)</td>\s*</tr>",
    re.S,
)
_BUGRY_TIME = re.compile(r"(\d{2})-(\d{2})")


class BugryArenaHtmlParser(IceParser):
    """Ледовая арена «Бугры», СПб (spb-bugry-arena.md, arena_id=111).

    Plain static HTML table, no JS widget: one row per date, two columns
    (Большая/Малая арена), each holding a semicolon-separated list of
    **start times only** — ``HH-MM`` (dash, not colon — a real source quirk)
    — no end time and no duration printed anywhere on the page. Every slot
    uses ``IceSessionNormalizer``'s own ``default_duration_minutes`` fallback
    (``ends_at_local`` left unset here) rather than a guessed literal end
    time; 45 minutes in job.config, a typical St. Petersburg rink session
    length, not confirmed against the source — flagged, not asserted as fact
    (see spec's Known limitation).

    Both rinks are parsed structurally (not hardcoded to "Большая only") even
    though "Малая" is empty in every row of the 2026-09-19 snapshot — if the
    operator ever publishes Малая sessions, this adapter picks them up
    without a code change. Price is flat per rink from job.config (same
    convention as `OzerkiCalendarParser`); both currently read 600 ₽, but the
    config keeps them independent since rental price already differs (500 ₽
    Большая vs 400 ₽ Малая on the page's own price table).
    """

    parser_key = "bugryarena_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="index.html", url_keys=("url",))
        rinks = job.config.get("rinks") or {}
        year = int(job.config.get("run_year") or date.today().year)
        slots: list[ExtractedSlot] = []
        for day, month, big_cell, small_cell in _BUGRY_ROW.findall(html):
            local_date = date(year, int(month), int(day)).isoformat()
            for code, cell in (("big", big_cell), ("small", small_cell)):
                rink_cfg = rinks.get(code) or {}
                for hh, mm in _BUGRY_TIME.findall(cell):
                    slots.append(
                        ExtractedSlot(
                            local_date=local_date,
                            starts_at_local=f"{hh}:{mm}",
                            kind_raw="public_skate",
                            price_adult=rink_cfg.get("price_adult_minor"),
                            price_child=None,
                            price_rental=rink_cfg.get("price_rental_minor"),
                            session_label=rink_cfg.get("label"),
                        )
                    )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)


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
