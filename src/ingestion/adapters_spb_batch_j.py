"""SPb batch J IceParser strategy. Extract only.

One arena reverse-engineered this pass, spec + fixture under
``data/parsers/spb-izhorets.md`` / ``data/fixtures/spb-izhorets/``:

- ``IzhoretsHtmlParser`` (spb-izhorets.md, arena_id=185) — static Joomla page,
  a hand-maintained day-of-week schedule ("Расписание сеансов:"), not a
  weekly calendar grid with explicit dates.

Currency is RUB, timezone Europe/Moscow — never fall back to the BYN/
Europe/Minsk defaults ``IceSessionNormalizer`` uses for BY arenas.

Feasibility note (primary/backup candidates tried this round, per the
Ice Discovery agent lane's mandatory feasibility gate):

- Primary candidate, Академия ледовых видов спорта «Динамо» СПб
  (arena_id=175, possible duplicate row id=176): infeasible. The academy's
  own domain, ``school-internat576.ru``, sits fully behind DDoS-Guard bot
  protection (HTTP 403 on both http:// — which 301-redirects to https:// —
  and https://, real bot-challenge body, not a TLS-layer failure). The
  academy's sports-school subdomain, ``kids.dynamo-spb.com``, is a live,
  reachable site but is the youth hockey school's match/tournament/roster
  portal (HLNet CMS) — it has no public/mass-skating schedule page at all.
  The only other public-facing page for this venue's public skating,
  ``novikova.ledokat.ru``, is a third-party booking SaaS widget (Ledokat) —
  explicitly out of scope per the Ice Discovery lane rules (needs a real API
  integration, not a static-HTML scrape). Backup 1 (Ижорец) was tried next.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from src.ingestion.htmlutil import strip_tags
from src.ingestion.parsers import IceParser
from src.ingestion.source_io import load_source_text
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob

# --- spb-izhorets -------------------------------------------------------

_IZHORETS_WEEKDAYS = {
    "понедельник": 0,
    "вторник": 1,
    "среда": 2,
    "четверг": 3,
    "пятница": 4,
    "суббота": 5,
    "воскресенье": 6,
}
_IZHORETS_WEEKDAY_ALT = "|".join(_IZHORETS_WEEKDAYS)

# Matches "<Weekday> <HH.MM or HH:MM>[, <HH:MM>]..." — the source prints one
# weekday label per line (``<br />``-separated, collapsed to spaces by
# ``strip_tags``) followed by one or more session start times. The site
# mixes "." and ":" as the hour/minute separator on the very same line
# ("Суббота 20.00" ... "Воскресенье 13.00, 14:15") — a real, confirmed source
# quirk, not a parsing artifact — so both separators are accepted.
_IZHORETS_DAY_BLOCK = re.compile(rf"(?i)({_IZHORETS_WEEKDAY_ALT})\s*((?:\d{{1,2}}[.:]\d{{2}}\s*,?\s*)+)")
_IZHORETS_HHMM = re.compile(r"(\d{1,2})[.:](\d{2})")


def _izhorets_schedule_window(text: str) -> str:
    """Bound the regex search to the "Расписание сеансов:" block only.

    The page is a long Joomla content dump with lots of unrelated prose
    (visitor rules, contacts, other venues in the operator's nav menu) — none
    of it currently contains a Russian weekday word followed by digits, but
    anchoring on the label (mirrors ``KupchinoArenaHtmlParser``'s
    ``_text_after_label`` convention in ``adapters_spb_batch_b.py``) keeps
    this robust if that ever changes.
    """
    start = text.find("Расписание сеансов")
    if start == -1:
        return ""
    end = text.find("Возможны изменения", start)
    return text[start : end if end != -1 else start + 500]


class IzhoretsHtmlParser(IceParser):
    """СПб ГБУ СОК «Ижорец», ФОК «Ижорец» (пос. Металлострой) (spb-izhorets.md, arena_id=185).

    Static server-rendered Joomla page (``/massovoe-katanie-fok-izhorets``),
    no bot-block. Unlike every weekly-grid RU-pilot adapter, this page isn't
    a calendar of explicit dates — it's a single hand-maintained paragraph
    ("Расписание сеансов: Платно:") naming the day(s) of the week the rink
    runs public skating and the start time(s) on each: the 2026-09-22
    snapshot reads "Суббота 20.00" and "Воскресенье 13.00, 14:15". Two
    numbers on the same weekday with no "до"/dash between them (contrast
    ``KupchinoArenaHtmlParser``'s explicit "с HH:MM до HH:MM" ranges) are two
    separate session start times, not a start/end pair — same convention as
    ``BugryArenaHtmlParser``'s comma/semicolon-separated start-time lists —
    flagged here, not asserted as fact, since the source itself never spells
    out which reading is intended.

    No end time or session duration is printed anywhere on the page, so
    every slot relies on ``IceSessionNormalizer``'s own
    ``default_duration_minutes`` fallback (``ends_at_local`` left unset
    here) — 60 minutes in job.config, a typical St. Petersburg mass-skating
    session length, not confirmed against the source.

    Price is genuinely not scraped: the schedule page has no price text at
    all. The only price list is a PDF linked from a separate
    ``/platnye-uslugi-2/...`` page (``FOK_price_katok_<date>.pdf``) whose
    filename changes on every update and 404s intermittently even when
    linked live from the site — parsing that reliably is out of scope for
    this pass. ``price_adult`` / ``price_child`` / ``price_rental`` are
    always ``None``; see spec's Known limitation.

    The schedule is re-derived from live text on every run (not hardcoded,
    unlike ``LidaLdsParser``'s transcribed-JPG dict) — day names and times
    are parsed out of the ``Расписание сеансов:`` block each fetch, then
    projected forward over a sliding ``horizon_days``-day window starting at
    ``week_start`` (both job.config, defaulting to "today" / 7 days — same
    sliding-window convention as ``LidaLdsParser``).
    """

    parser_key = "izhorets_html_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        html = await load_source_text(job, filename="massovoe-katanie.html", url_keys=("url",))
        text = strip_tags(html)
        window = _izhorets_schedule_window(text)

        schedule: dict[int, list[str]] = {}
        for weekday_name, times_raw in _IZHORETS_DAY_BLOCK.findall(window):
            weekday_idx = _IZHORETS_WEEKDAYS[weekday_name.lower()]
            times = sorted({f"{int(h):02d}:{m}" for h, m in _IZHORETS_HHMM.findall(times_raw)})
            schedule.setdefault(weekday_idx, []).extend(t for t in times if t not in schedule.get(weekday_idx, []))

        week_start = date.fromisoformat(str(job.config.get("week_start") or date.today().isoformat()))
        horizon = int(job.config.get("horizon_days") or 7)

        slots: list[ExtractedSlot] = []
        for offset in range(horizon):
            local_date = week_start + timedelta(days=offset)
            for start in schedule.get(local_date.weekday(), []):
                slots.append(
                    ExtractedSlot(
                        local_date=local_date.isoformat(),
                        starts_at_local=start,
                        kind_raw="public_skate",
                        price_adult=None,
                        price_child=None,
                        price_rental=None,
                    )
                )
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot=html, slots=slots)
