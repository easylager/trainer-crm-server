"""Ledokat (ledokat.ru) booking-widget parsers.

Ledokat is a booking SaaS for rinks. A rink embeds
``<div class="ledokat-widget-3-schedule" data-id="<widget id>">`` plus
``ledokat.ru/js/widget/3/main.js``; the script reads the week from the public API
``https://api.ledokat.ru/rink-widget/seances/<widget id>?dateFrom=YYYY-MM-DD&dateTo=YYYY-MM-DD``
(one Monday–Sunday week per call). Every seance carries ``seanceId``, ``service``
(the rink's own service name: «Массовое катание», «Час хоккея»…), ``seanceName``
(free text for rentals and teams), ``startedAt`` / ``finishedAt`` in rink-local
time and ``tickets`` (often empty: prices live on the rink's own site).

The shared parser is strict on purpose:

- the payload must name the expected ``rinkId`` — a widget id copied from another
  rink's page would otherwise publish someone else's ice;
- only exact service names listed per rink become slots; rentals, teams and
  unknown services are dropped, never guessed into public skating;
- a seance whose end is not after its start, or that crosses midnight, is dropped.

- ``RaketaLedokatParser`` (spb-arena-raketa.md, arena_id=171) — Арена Ракета, Шушары.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any

from src.ingestion.dates import parser_reference_date
from src.ingestion.parsers import IceParser
from src.ingestion.source_io import fetch_http_text, fetch_http_text_optional, load_source_text
from src.ingestion.types import (
    PARSER_KIND_HOCKEY_PRACTICE,
    PARSER_KIND_PUBLIC_SKATE,
    ExtractedSlot,
    Extraction,
    ParserJob,
)

LEDOKAT_API = "https://api.ledokat.ru"
_LOCAL_DT = "%Y-%m-%d %H:%M:%S"
_WEEKS = 2


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def ledokat_week_url(widget_id: str, monday: date) -> str:
    sunday = monday + timedelta(days=6)
    return f"{LEDOKAT_API}/rink-widget/seances/{widget_id}?dateFrom={monday.isoformat()}&dateTo={sunday.isoformat()}"


def ledokat_seances(payload: Any, *, rink_id: int) -> list[dict[str, Any]]:
    """Validated ``payload.seances``; raises when the answer is not this rink's schedule."""
    if not isinstance(payload, dict) or payload.get("error") is not False:
        raise ValueError("ledokat: error or malformed answer")
    body = payload.get("payload")
    if not isinstance(body, dict) or not isinstance(body.get("seances"), list):
        raise ValueError("ledokat: payload.seances missing")
    widget = body.get("widget") or {}
    if widget.get("rinkId") != rink_id:
        raise ValueError(f"ledokat: widget belongs to rink {widget.get('rinkId')!r}, expected {rink_id}")
    return [s for s in body["seances"] if isinstance(s, dict)]


class LedokatWidgetParser(IceParser):
    """Base: one rink's Ledokat widget. Subclasses set the ids and the service map."""

    parser_key = ""
    #: Exact ``service`` value → parser kind. Anything else is not published.
    services: dict[str, str] = {}

    async def _weeks(self, job: ParserJob) -> list[Any]:
        if job.config.get("fixture_dir"):
            pages = []
            for index in range(_WEEKS):
                try:
                    pages.append(json.loads(await load_source_text(job, filename=f"seances-{index}.json")))
                except FileNotFoundError:
                    break
            return pages
        first = _monday(parser_reference_date(job.config))
        widget_id = str(job.config["widget_id"])
        return [
            json.loads(await fetch_http_text(ledokat_week_url(widget_id, first + timedelta(days=7 * index))))
            for index in range(_WEEKS)
        ]

    def prices(self, kind: str, price_page: str | None) -> dict[str, Any]:
        return {}

    async def extract(self, job: ParserJob) -> Extraction:
        rink_id = int(job.config["rink_id"])
        pages = await self._weeks(job)
        if not pages:
            raise ValueError("ledokat: no schedule pages")
        price_page = await self._price_page(job)
        seen: set[int] = set()
        slots: list[ExtractedSlot] = []
        for page in pages:
            for seance in ledokat_seances(page, rink_id=rink_id):
                kind = self.services.get(str(seance.get("service") or "").strip())
                seance_id = seance.get("seanceId")
                if kind is None or not isinstance(seance_id, int) or seance_id in seen:
                    continue
                try:
                    start = datetime.strptime(str(seance.get("startedAt")), _LOCAL_DT)
                    end = datetime.strptime(str(seance.get("finishedAt")), _LOCAL_DT)
                except ValueError:
                    continue
                if end <= start or end.date() != start.date():
                    continue
                seen.add(seance_id)
                slots.append(
                    ExtractedSlot(
                        local_date=start.date().isoformat(),
                        starts_at_local=start.strftime("%H:%M"),
                        ends_at_local=end.strftime("%H:%M"),
                        kind_raw=kind,
                        source_id=f"ledokat:{seance_id}",
                        **self.prices(kind, price_page),
                    )
                )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot=json.dumps(pages, ensure_ascii=False),
            slots=slots,
        )

    async def _price_page(self, job: ParserJob) -> str | None:
        if job.config.get("fixture_dir"):
            try:
                return await load_source_text(job, filename="price.html")
            except FileNotFoundError:
                return None
        url = job.config.get("price_url")
        return await fetch_http_text_optional(str(url)) if url else None


def _price_row(text: str, label: str) -> int | None:
    """Tilda price table row «Массовое катание взрослые;60 минут;450 р/час»."""
    match = re.search(re.escape(label) + r"\s*;\s*60\s*минут\s*;\s*(\d{2,5})\s*р\s*/\s*час", text, re.I)
    return int(match.group(1)) if match else None


def raketa_prices(html: str | None) -> dict[str, int | None]:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).replace("&nbsp;", " ")
    return {
        "adult": _price_row(text, "Массовое катание взрослые"),
        "child": _price_row(text, "Массовое катание дети до 16 лет"),
        "rental": _price_row(text, "Прокат коньков"),
        "hockey": _price_row(text, "Час хоккея 1 человек"),
    }


class RaketaLedokatParser(LedokatWidgetParser):
    """Арена Ракета, Шушары (spb-arena-raketa.md, arena_id=171, Ledokat rink 1929).

    «Массовое катание FREE» is left out: the site never says what FREE means
    (free entry? a closed group?), so neither its price nor its audience is known.
    """

    parser_key = "raketa_ledokat_v1"
    services = {
        "Массовое катание": PARSER_KIND_PUBLIC_SKATE,
        "Час хоккея": PARSER_KIND_HOCKEY_PRACTICE,
    }

    def prices(self, kind: str, price_page: str | None) -> dict[str, Any]:
        table = raketa_prices(price_page)
        if kind == PARSER_KIND_HOCKEY_PRACTICE:
            return {"price_adult": table["hockey"]}
        return {
            "price_adult": table["adult"],
            "price_child": table["child"],
            "price_rental": table["rental"],
            "age_note": "Детский — до 16 лет" if table["child"] else None,
        }
