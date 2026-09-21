"""SPb batch B IceParser strategies. Extract only.

One arena reverse-engineered this pass, spec + fixture under
``data/parsers/spb-kupchino-arena.md`` / ``data/fixtures/spb-kupchino-arena/``:

- ``KupchinoArenaHtmlParser`` (spb-kupchino-arena.md, arena_id=110) — static
  Tilda page, a single hand-maintained "next session(s)" text block rather
  than a weekly grid.

Currency is RUB, timezone Europe/Moscow — never fall back to the BYN/
Europe/Minsk defaults ``IceSessionNormalizer`` uses for BY arenas.
"""
from __future__ import annotations

import re
from datetime import date

from src.ingestion.normalize import parse_price_to_minor
from src.ingestion.parsers import IceParser
from src.ingestion.source_io import load_source_text
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob

# --- spb-kupchino-arena ------------------------------------------------

# Matches "DD.MM.YY <с|c> HH:MM до HH:MM". The preposition before the start
# time is a real source quirk: the first printed session uses Cyrillic "с"
# (U+0441), the second uses a plain Latin "c" (U+0063) — a copy-paste typo
# in the site's own hand-edited text, confirmed byte-for-byte in the
# 2026-09-22 fixture. The character class below accepts either.
_KUPCHINO_SESSION = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{2})\s*[сc]\s*(\d{1,2}):(\d{2})\s*до\s*(\d{1,2}):(\d{2})"
)


def _text_after_label(html: str, label_html: str) -> str | None:
    """Return the contents of the next ``<h3>`` following a literal label
    substring (matched by its own ``<h2>...</h2>`` HTML, ``<br>`` included).
    Tilda repeats the same ``<h2 label/><h3 value/>`` shape dozens of times
    on this page for unrelated feature blurbs, so anchoring on the unique
    label text (rather than a positional/structural regex) is what keeps
    this from picking up the wrong pair.
    """
    idx = html.find(label_html)
    if idx == -1:
        return None
    start = html.find("<h3", idx)
    if start == -1:
        return None
    start = html.find(">", start) + 1
    end = html.find("</h3>", start)
    return html[start:end] if end != -1 else None


class KupchinoArenaHtmlParser(IceParser):
    """Ледовая арена «Купчино», СПб, ул. Димитрова 3А (spb-kupchino-arena.md, arena_id=110).

    Static server-rendered Tilda page (``/massskating``), no bot-block. Unlike
    every weekly-grid RU-pilot adapter, this page is not a recurring
    schedule table — it's a single hand-maintained text block ("Время
    сеанса:") that the operator updates with just the next upcoming
    session(s) as explicit ``DD.MM.YY`` dates. The 2026-09-22 snapshot
    carries exactly two upcoming sessions, both on the same date
    (``26.09.26``), each a printed ``HH:MM до HH:MM`` pair — so both start
    and end are always present in the source; no ``default_duration_minutes``
    fallback is needed here.

    Price is genuinely scraped, not config-driven: the same page prints an
    "входного билета" (entry ticket) figure and a separate "проката
    коньков" (skate rental) figure, each its own flat ``<h3>500 ₽</h3>``
    value applied to every extracted slot. No child price is published
    anywhere on the page — ``price_child`` stays ``None``.

    Because the page shows only whatever the operator has currently typed
    in (sometimes a single date, sometimes none), an empty match is a valid
    "nothing scheduled yet" state, not a parse failure — same convention as
    ``SokolnikiHtmlParser``'s empty ``.schedule-list``.
    """

    parser_key = "kupchinoarena_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="massskating.html", url_keys=("url",))

        times_raw = _text_after_label(html, "Время<br>сеанса:") or ""
        adult_raw = _text_after_label(html, "Стоимость<br>входного билета")
        rental_raw = _text_after_label(html, "Стоимость<br>проката коньков")
        adult = parse_price_to_minor(adult_raw, already_minor=False) if adult_raw else None
        rental = parse_price_to_minor(rental_raw, already_minor=False) if rental_raw else None

        slots: list[ExtractedSlot] = []
        for yy, mm, dd, sh, sm, eh, em in _KUPCHINO_SESSION.findall(times_raw):
            local_date = date(2000 + int(yy), int(mm), int(dd)).isoformat()
            slots.append(
                ExtractedSlot(
                    local_date=local_date,
                    starts_at_local=f"{int(sh):02d}:{sm}",
                    ends_at_local=f"{int(eh):02d}:{em}",
                    kind_raw="public_skate",
                    price_adult=adult,
                    price_child=None,
                    price_rental=rental,
                )
            )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)
