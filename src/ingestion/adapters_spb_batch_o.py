"""SPb batch O IceParser strategy. Extract only.

One arena reverse-engineered this pass, spec + fixture under
``data/parsers/spb-shuvalovsky-led.md`` / ``data/fixtures/spb-shuvalovsky-led/``:

- ``ShuvalovskyLedHtmlParser`` (spb-shuvalovsky-led.md, arena_id=196) —
  static WordPress-rendered weekly schedule grid, two "Массовое катание"
  rows (Большой лед / Малый лед), each with 7 day columns for the current
  displayed week (no historical or future-week navigation on the page).

Currency is RUB, timezone Europe/Moscow — never fall back to the BYN/
Europe/Minsk defaults ``IceSessionNormalizer`` uses for BY arenas.

Feasibility note (per the Ice Discovery agent lane's mandatory feasibility
gate): primary candidate, Шуваловский лёд (arena_id=196, ул. Лидии Зверевой,
8), was feasible on the first pass — its own site, shuvalov-ice.ru, has a
static server-rendered ``/shedule/`` page with a real weekly grid, no
bot-block, no third-party booking widget. Note the site's shared address
with arena_id=182 "Ленинградский кёрлинг-клуб" — that curling club runs out
of the same physical complex (its own site, lencurl.ru, is the curling club's
separate booking surface, not investigated here) but shuvalov-ice.ru itself
is unambiguously the public ice-skating side of that complex, with a
dedicated "Массовое катание" (public skating) product distinct from "Игра в
кёрлинг" (curling) in its own nav — so backup candidates were not needed.

Direct ``curl``/WebFetch to shuvalov-ice.ru both hung/failed from this
research sandbox (TLS handshake timeout on port 443, not a clean HTTP
error) — same documented sandbox-egress phenomenon as
``LedovyyDvoretsHtmlParser`` in ``adapters_ru_pilot.py``. A third path,
the ``r.jina.ai`` reader-proxy (with ``X-Return-Format: html`` to get raw
markup rather than markdown), succeeded and returned genuine static
WordPress HTML: real ``<meta>`` tags, a LiteSpeed cache asset manifest, and
a ``.shedule__table`` grid with the *current* real week's dates baked into
the markup (confirmed against the capture date) — not a bot-challenge body
and not a client-rendered SPA shell with an empty DOM. A production worker
with normal egress should reach the origin directly and does not need the
proxy.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from src.ingestion.parsers import IceParser
from src.ingestion.source_io import load_source_text
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob

# --- spb-shuvalovsky-led --------------------------------------------------

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

_MASS_SKATE_LABEL = "Массовое катание"

# One schedule row: a ``.shedule__programm`` label + parenthetical arena
# descriptor (e.g. "Большой лед - 60*28"), followed by exactly 7
# ``.shedule__time`` day cells (Mon..Sun, matching the 7 ``.shedule__date``
# header cells found separately). The desktop table is matched here; the
# page repeats the identical data a second time lower down in a
# ``.shedule__table--mobile`` carousel variant for small screens — the
# fixture/regex window is bounded to stop before that marker so rows aren't
# double-counted.
_ROW = re.compile(
    r'<div class="shedule__programm"><span>([^<]+)</span>\(([^)]*)\)</div>'
    r'((?:<div class="shedule__time">.*?</div>){7})',
    re.S,
)
_DAY_CELL = re.compile(r'<div class="shedule__time">(.*?)</div>')
_DATE_HEADER = re.compile(r'<div class="shedule__date[^"]*">(\d{1,2})\s+([а-яё]+)</div>')

# Matches "HH:MM <dash> HH:MM" inside a day cell. Cells join multiple
# sessions with "<br>"; some end times carry a trailing marker with no
# legend anywhere on the page — a plain "*"/"**" (2026-09-22 snapshot, 26
# occurrences) and, once, a single stray Cyrillic "Ю" glued directly onto an
# end time ("14:00 – 15:00Ю") that reads as a one-off typo, not a
# structural marker (found nowhere else on the page). None of them are
# captured or interpreted — the regex only requires the digit groups, so
# anything appended straight after the end time is silently ignored, same
# "don't invent meaning for an unexplained marker" convention as
# ``IzhoretsHtmlParser``'s comma-vs-semicolon note.
_TIME_PAIR = re.compile(r"(\d{1,2}):(\d{2})\s*[–—-]\s*(\d{1,2}):(\d{2})")

_RINK_LABEL = re.compile(r"([А-Яа-яё]+\s+лед)")


def _rink_label(arena_desc: str) -> str | None:
    match = _RINK_LABEL.search(arena_desc)
    return match.group(1) if match else None


class ShuvalovskyLedHtmlParser(IceParser):
    """Шуваловский лёд, СПб, ул. Лидии Зверевой, 8 (spb-shuvalovsky-led.md, arena_id=196).

    Static server-rendered WordPress page (``/shedule/``), no bot-block. The
    page is a genuine current-week grid (7 explicit ``DD месяц`` date
    columns, no year printed — ``run_year`` in job.config controls it, same
    convention as ``LedovyyDvoretsHtmlParser``), not a day-of-week recurring
    template — so unlike the sliding-window BY adapters, dates come straight
    off the page rather than being projected forward from a weekday pattern.
    The page has no next/previous-week navigation at all (only a same-week
    mobile-carousel duplicate of the identical 7 days) — there is nothing to
    page through, hence ``cadence: daily`` to avoid missing sessions between
    scrapes of this rolling 7-day window.

    Two independent "Массовое катание" rows exist — one for the "Большой
    лед" (60×28 m) rink, one for "Малый лед" (30×21 m) — both are public
    skating and both are extracted, tagged via ``session_label`` so they
    aren't silently merged into one indistinguishable slot when they land on
    the same start time (not observed in the 2026-09-22 fixture, but the two
    rinks are physically independent and could overlap on other weeks).

    Price is not printed on the schedule page itself — the operator's
    separate ``/services/massovoye-kataniye/`` page publishes a flat price
    *matrix* instead of a per-session figure: one price for a 60-minute
    session and a higher one for a 75-minute session, each split further
    into a "будние дни" (weekday) and "выходные и праздники" (weekend) rate,
    identical for adults and children ("взрослые и дети" — a single combined
    row, not two). Every session on the schedule grid is measurable this
    way, since both the duration (from the printed start/end times) and the
    weekday are already known once a slot is extracted, so this adapter
    computes each slot's duration and looks up the matching tier from
    job.config rather than leaving price fields unset — cross-checked
    against all 32 sessions in the 2026-09-22 fixture, every single one is
    exactly 60 or 75 minutes, matching the matrix's only two published
    tiers. A duration that doesn't match either tier (not observed, but
    possible on a future capture) intentionally falls through with no price
    rather than guessing. "Праздники" (public holidays) are not modeled —
    the weekday/weekend split uses the calendar day-of-week only, same
    limitation as every other adapter in this codebase (no holiday
    calendar integration exists here).

    Skate rental is a separate flat rate, 600 ₽/hour, published on
    ``/services/prokat-konkov/`` with no duration/weekday split — applied to
    every slot unconditionally via job.config's ``price_rental_minor``.
    """

    parser_key = "shuvalovskyled_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="shedule.html", url_keys=("url",))
        section = html
        mobile_marker = html.find("shedule__table shedule__table--mobile")
        if mobile_marker != -1:
            section = html[:mobile_marker]

        year = int(job.config.get("run_year") or date.today().year)
        rental = job.config.get("price_rental_minor")
        tiers = {
            (60, False): job.config.get("price_60min_weekday_minor"),
            (60, True): job.config.get("price_60min_weekend_minor"),
            (75, False): job.config.get("price_75min_weekday_minor"),
            (75, True): job.config.get("price_75min_weekend_minor"),
        }

        dates: list[str] = []
        for day, month_name in _DATE_HEADER.findall(section):
            month = _MONTHS_RU.get(month_name)
            if month is None:
                continue
            dates.append(date(year, month, int(day)).isoformat())

        slots: list[ExtractedSlot] = []
        for label, arena_desc, days_block in _ROW.findall(section):
            if label.strip() != _MASS_SKATE_LABEL:
                continue
            rink = _rink_label(arena_desc)
            day_cells = _DAY_CELL.findall(days_block)
            for idx, cell in enumerate(day_cells):
                if idx >= len(dates):
                    break
                local_date = dates[idx]
                is_weekend = date.fromisoformat(local_date).weekday() >= 5
                for sh, sm, eh, em in _TIME_PAIR.findall(cell):
                    start = f"{int(sh):02d}:{sm}"
                    end = f"{int(eh):02d}:{em}"
                    duration = (int(eh) * 60 + int(em)) - (int(sh) * 60 + int(sm))
                    price = tiers.get((duration, is_weekend))
                    slots.append(
                        ExtractedSlot(
                            local_date=local_date,
                            starts_at_local=start,
                            ends_at_local=end,
                            kind_raw="public_skate",
                            price_adult=price,
                            price_child=price,
                            price_rental=rental,
                            session_label=rink,
                        )
                    )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)
