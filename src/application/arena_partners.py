"""Партнёры рядом с катком: блок «После катка» на странице места и в карточке Mini App.

Источник — ``data/catalog/arena-partners.json``. Партнёр — ответ на «куда пойти после
катания», а не реклама, поэтому правила жёсткие:

- только на странице своего катка, после чипов «На месте»; на главной, в списке города
  и на карте его нет;
- без предложения для наших людей (``offer``) партнёра не показываем;
- не больше трёх на каток; по ``valid_to`` исчезает сам.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "catalog" / "arena-partners.json"
_STATIC_PREFIX = "/static/webapp/"
MAX_PARTNERS_PER_ARENA = 3
PARTNER_KINDS = frozenset({"food", "coffee", "shop", "service"})


def _parse_date(raw: Any) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return None


def _asset(path: Any) -> str | None:
    rel = str(path or "").strip().lstrip("/")
    if not rel or ".." in rel or not rel.startswith("partners/"):
        return None
    return _STATIC_PREFIX + rel


def _public(entry: dict[str, Any]) -> dict[str, Any] | None:
    slug = str(entry.get("slug") or "").strip()
    name = str(entry.get("name") or "").strip()
    offer = str(entry.get("offer") or "").strip()
    if not slug or not name or not offer:
        return None
    kind = str(entry.get("kind") or "").strip()
    photos = [u for u in (_asset(p) for p in entry.get("photos") or []) if u]
    return {
        "slug": slug,
        "kind": kind if kind in PARTNER_KINDS else "service",
        "name": name,
        "line": str(entry.get("line") or "").strip(),
        "where": str(entry.get("where") or "").strip(),
        "hours": str(entry.get("hours") or "").strip(),
        "offer": offer,
        "offer_note": str(entry.get("offer_note") or "").strip(),
        "code": str(entry.get("code") or "").strip(),
        "maps_url": str(entry.get("maps_url") or "").strip() or None,
        "logo": _asset(entry.get("logo")),
        "photos": photos[:3],
    }


@lru_cache(maxsize=1)
def _registry() -> tuple[tuple[frozenset[int], date | None, date | None, dict[str, Any]], ...]:
    try:
        raw = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    out = []
    for entry in raw.get("partners") or []:
        if not isinstance(entry, dict):
            continue
        public = _public(entry)
        if public is None:
            continue
        arenas = frozenset(int(a) for a in entry.get("arena_ids") or [] if str(a).isdigit())
        if not arenas:
            continue
        out.append((arenas, _parse_date(entry.get("valid_from")), _parse_date(entry.get("valid_to")), public))
    return tuple(out)


def partners_for_arena(arena_id: int, *, today: date) -> list[dict[str, Any]]:
    """Действующие партнёры катка в порядке реестра, не больше трёх."""
    result: list[dict[str, Any]] = []
    for arenas, start, end, public in _registry():
        if int(arena_id) not in arenas:
            continue
        if start is not None and today < start:
            continue
        if end is not None and today > end:
            continue
        result.append(dict(public))
        if len(result) >= MAX_PARTNERS_PER_ARENA:
            break
    return result
