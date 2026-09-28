"""SPb batch M IceParser strategy. Extract only.

One arena reverse-engineered this pass, spec + fixture under
``data/parsers/spb-dinamo-yunior.md`` / ``data/fixtures/spb-dinamo-yunior/``:

- ``DinamoYuniorHtmlParser`` (spb-dinamo-yunior.md, arena_id=173) — static
  HLNet CMS page, a single hand-maintained "every <weekday> at HH:MM-HH:MM"
  text block, not a weekly calendar grid or per-date list.

Currency is RUB, timezone Europe/Moscow — never fall back to the BYN/
Europe/Minsk defaults ``IceSessionNormalizer`` uses for BY arenas.

Feasibility note (primary/backup candidates tried this round, per the Ice
Discovery agent lane's mandatory feasibility gate):

- Primary candidate, Крытый каток при академии ледовых видов спорта «Динамо»
  СПб (arena_id=176, ул. Мебельная, д. 33А): infeasible. This is a genuinely
  different physical venue from arena_id=175 (ул. Маршала Новикова, 14,
  ruled infeasible in a prior round — see ``IzhoretsHtmlParser``'s docstring
  in ``adapters_spb_batch_j.py``) but shares the same parent organization
  and the same outcome. The academy's own domain, ``school-internat576.ru``,
  sits fully behind DDoS-Guard (clean HTTP 403 bot-challenge body,
  confirmed independently this round). Its youth-hockey subdomain,
  ``kids.dynamo-spb.com``, is live and reachable, but is the
  roster/match-calendar portal for a *third*, wholly separate Dynamo rink
  (пер. Каховского, д. 2Б/2К) — its own "Инфраструктура" page never
  mentions Мебельная anywhere. The hockey club's own site,
  ``hcdynamopiter.orgs.biz``, mentions Мебельная only inside VK-sourced
  player-tryout announcement images, no schedule text. The only
  public-facing schedule/booking surface actually tied to this address is a
  third-party booking SaaS widget, ``ledovyy-mebelnaya.ledokat.ru``
  ("Олимпийские надежды" hall) — explicitly out of scope for this lane
  (needs a real API integration, not a static-HTML scrape).

- Backup 1, «Динамо-Юниор» (arena_id=181, ул. Бутлерова, д. 36): the
  operator's own site, ``shorspb.ru``, is live and has a dedicated
  ``/Skating`` page — but that page's own text names a *different* street
  address for the actual sessions ("на ледовой арене школы по хоккею
  «Динамо-юниор» по адресу г. Санкт-Петербург, ул. Фаворского, д.7"),
  matching backup 2 below, not this venue. Бутлерова, 36 (on the grounds of
  SK «Спартак») is the school's administrative/training address only — no
  public-skating schedule is published for it specifically. Treated as
  infeasible for *this* arena row; backup 2 was built instead.

- Backup 2, «Ледовая арена Динамо-Юниор» (arena_id=173, ул. Фаворского, 7):
  feasible — this spec/adapter. Same ``shorspb.ru`` site, same ``/Skating``
  page; its schedule text is explicitly about this address.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from src.ingestion.htmlutil import strip_tags
from src.ingestion.parsers import IceParser
from src.ingestion.source_io import load_source_text
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob

# --- spb-dinamo-yunior ----------------------------------------------------

_WEEKDAY_STEMS = {
    "понедельник": 0,
    "вторник": 1,
    "сред": 2,
    "четверг": 3,
    "пятниц": 4,
    "суббот": 5,
    "воскресень": 6,
}
_WEEKDAY_ALT = "|".join(_WEEKDAY_STEMS)

# Matches "<weekday word, any grammatical ending> ... в HH:MM-HH:MM" — e.g.
# "Каждую субботу в 21:00-22:00". Anchored on the weekday *stem* rather than
# a full word because the source uses the accusative case ("субботу"), and
# if the operator ever moves the session to another day the printed word
# would use a different case ("каждый понедельник", "каждое воскресенье")
# — matching the stem keeps this robust without hardcoding every ending.
_SESSION_RE = re.compile(
    rf"(?i)({_WEEKDAY_ALT})\w*[^\d]{{0,20}}?(\d{{1,2}}):(\d{{2}})\s*[-–—]\s*(\d{{1,2}}):(\d{{2}})"
)

# Matches the first "<digits> руб[.]" or "<digits> р." after a label —
# anchoring only on the currency suffix (not just "first digits after the
# label") matters here: the source's own prose prints an unrelated "1 час
# (60 минут)" duration *before* the actual price on the very same line
# ("Стоимость входного билета ... 1 час (60 минут) – 500 руб."), so a naive
# "first number in the window" read would wrongly capture "1" as the price.
_PRICE_RE = re.compile(r"(\d+)\s*(?:руб\.?|р\.)")


def _price_after_label(text: str, label: str) -> str | None:
    idx = text.find(label)
    if idx == -1:
        return None
    window = text[idx : idx + 200]
    match = _PRICE_RE.search(window)
    return match.group(1) if match else None


class DinamoYuniorHtmlParser(IceParser):
    """«Ледовая арена Динамо-Юниор», СПб, ул. Фаворского, 7 (spb-dinamo-yunior.md, arena_id=173).

    Static server-rendered HLNet CMS page (``/Skating``), no bot-block. Like
    ``KupchinoArenaHtmlParser`` and ``IzhoretsHtmlParser``, this is not a
    weekly calendar grid — it's a single hand-maintained paragraph (sitting
    inside a stray ``<h1>`` tag on the source page; not semantically a
    heading, just how the operator's rich-text editor happened to save it)
    naming one fixed weekly session: "Каждую субботу в 21:00-22:00" (every
    Saturday, 21:00-22:00) as of the 2026-09-22 snapshot. Unlike Izhorets,
    both start *and* end times are printed, so no
    ``default_duration_minutes`` fallback is needed.

    The schedule is re-derived from live text on every run (not hardcoded)
    — the weekday name and time range are parsed out of the page each
    fetch, then projected forward over a sliding ``horizon_days``-day
    window starting at ``week_start`` (both job.config, defaulting to
    "today" / 7 days — same sliding-window convention as
    ``IzhoretsHtmlParser``/``LidaLdsParser``). A schedule with zero matched
    weekday/time pairs is a valid "nothing scheduled" state (same
    convention as ``KupchinoArenaHtmlParser``'s empty block), not a parse
    failure.

    Price is genuinely scraped: the same paragraph prints an entry-ticket
    figure ("Стоимость входного билета ... 500 руб.") and a skate-rental
    figure ("Стоимость проката коньков ... 300 р.") applied to every
    extracted slot. No child price is published anywhere on the page —
    ``price_child`` stays ``None``.
    """

    parser_key = "dinamoyunior_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="skating.html", url_keys=("url",))
        text = strip_tags(html)

        schedule: dict[int, list[tuple[str, str]]] = {}
        for weekday_stem, sh, sm, eh, em in _SESSION_RE.findall(text):
            weekday_idx = _WEEKDAY_STEMS[weekday_stem.lower()]
            start = f"{int(sh):02d}:{sm}"
            end = f"{int(eh):02d}:{em}"
            pairs = schedule.setdefault(weekday_idx, [])
            if (start, end) not in pairs:
                pairs.append((start, end))

        # Raw digit strings, not already-minor ints: left for
        # ``IceSessionNormalizer.normalize`` to convert via
        # ``parse_price_to_minor(..., already_minor=already_minor)`` — same
        # convention as ``IzhoretsHtmlParser`` (contrast
        # ``KupchinoArenaHtmlParser``, which converts at extract time and
        # therefore needs ``"prices_already_minor": true`` in job.config).
        adult = _price_after_label(text, "входного билета")
        rental = _price_after_label(text, "проката коньков")

        week_start = date.fromisoformat(str(job.config.get("week_start") or date.today().isoformat()))
        horizon = int(job.config.get("horizon_days") or 7)

        slots: list[ExtractedSlot] = []
        for offset in range(horizon):
            local_date = week_start + timedelta(days=offset)
            for start, end in schedule.get(local_date.weekday(), []):
                slots.append(
                    ExtractedSlot(
                        local_date=local_date.isoformat(),
                        starts_at_local=start,
                        ends_at_local=end,
                        kind_raw="public_skate",
                        price_adult=adult,
                        price_child=None,
                        price_rental=rental,
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)
