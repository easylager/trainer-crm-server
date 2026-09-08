"""Where a catalog URL should land after Ice swallowed browse (TASK-084).

Trainer cards stay on ``/webapp/catalog``. Browse (city → service → list) opens Ice.
Collective studio landings keep catalog until that surface moves.
"""
from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlencode

ICE_COACH_PATH = "/webapp/ice"
CATALOG_PATH = "/webapp/catalog"


def catalog_browse_redirect(query: Mapping[str, str] | None) -> str | None:
    """Return Ice URL when this catalog request is a funnel browse; else None (serve catalog)."""
    q = query or {}
    trainer_id = str(q.get("trainer_id") or "").strip()
    if trainer_id:
        return None
    if str(q.get("collective") or "").strip():
        return None
    params: dict[str, str] = {"intent": "coach"}
    city_id = str(q.get("city_id") or "").strip()
    if city_id:
        params["city_id"] = city_id
    return ICE_COACH_PATH + "?" + urlencode(params)


def client_discovery_webapp_url(
    base: str,
    *,
    trainer_id: int | None = None,
    service_id: int | None = None,
    city_id: int | None = None,
    arena_id: int | None = None,
) -> str:
    """HTTPS Mini App URL: Ice coaches list, or catalog trainer card when trainer_id is set."""
    origin = (base or "").rstrip("/")
    tid = int(trainer_id) if trainer_id is not None else 0
    if tid > 0:
        q: dict[str, str] = {"trainer_id": str(tid)}
        if city_id is not None:
            q["city_id"] = str(int(city_id))
        if service_id is not None and int(service_id) > 0:
            q["service_id"] = str(int(service_id))
        if arena_id is not None:
            q["arena_id"] = str(int(arena_id))
        return origin + CATALOG_PATH + "?" + urlencode(q)
    params: dict[str, str] = {"intent": "coach"}
    if city_id is not None:
        params["city_id"] = str(int(city_id))
    return origin + ICE_COACH_PATH + "?" + urlencode(params)
