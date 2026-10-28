"""
User-submitted places (PDEC-028): the raw suggestion lives in ``place_suggestions`` and
never touches the catalog until an admin approves it.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_consumer_events import _hmac_actor
from src.application.place_suggestion_notify import notify_admins_new_place_suggestion
from src.application.trainer_city_create_use_cases import find_city_by_name_insensitive
from src.shared.place_suggestion import (
    PlaceSuggestionError,
    classify_contact,
    normalize_details,
    validate_core,
)

logger = logging.getLogger(__name__)

SOURCES = ("site", "miniapp")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _clean(value: Any, limit: int) -> str | None:
    s = re.sub(r"\s+", " ", str(value or "")).strip()[:limit]
    return s or None


def _coord(value: Any, bound: float) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if -bound <= v <= bound else None


def client_ip_hash(client_ip: str | None) -> str | None:
    """HMAC(IP) на ``CATALOG_ACTOR_HMAC_SECRET``; без секрета — ``None`` (сам IP не храним)."""
    ip = (client_ip or "").strip()
    if not ip:
        return None
    return _hmac_actor("suggest-ip", ip)


async def create_place_suggestion(
    session: AsyncSession,
    *,
    source: str,
    kind: str,
    city_id: int | None,
    new_city: Mapping[str, Any] | None,
    name: str,
    address: str | None,
    details: Mapping[str, Any] | None,
    contact: str | None,
    author_telegram_id: int | None,
    client_ip: str | None,
) -> dict[str, Any]:
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")
    new_city = new_city or {}
    new_city_name, nm = validate_core(
        kind=kind, city_id=city_id, new_city_name=new_city.get("name"), name=name
    )
    clean_details = normalize_details(kind, dict(details or {}))
    contact_value, contact_kind = classify_contact(contact)

    new_country = new_region = None
    new_lat = new_lon = None
    if city_id is not None:
        ok = (await session.execute(text("SELECT 1 FROM cities WHERE id = :id"), {"id": int(city_id)})).fetchone()
        if not ok:
            raise PlaceSuggestionError("Город не найден.")
        new_city_name = None
    else:
        existing = await find_city_by_name_insensitive(session, new_city_name or "")
        if existing:
            city_id = int(existing["id"])
            new_city_name = None
        else:
            new_country = (_clean(new_city.get("country"), 2) or "").upper()
            if not _COUNTRY_RE.match(new_country):
                raise PlaceSuggestionError("Укажите страну города.")
            new_region = _clean(new_city.get("region"), 160)
            new_lat = _coord(new_city.get("lat"), 90)
            new_lon = _coord(new_city.get("lon"), 180)

    bind_token = secrets.token_urlsafe(12) if author_telegram_id is None else None

    r = await session.execute(
        text(
            """
            INSERT INTO place_suggestions (
                kind, source, city_id, new_city_name, new_city_country, new_city_region,
                new_city_lat, new_city_lon, name, address, details, contact, contact_kind,
                author_telegram_id, bind_token, client_ip_hash
            ) VALUES (
                :kind, :source, :city_id, :new_city_name, :new_city_country, :new_city_region,
                :new_city_lat, :new_city_lon, :name, :address, CAST(:details AS jsonb), :contact,
                :contact_kind, :author, :bind_token, :ip_hash
            )
            RETURNING id
            """
        ),
        {
            "kind": kind,
            "source": source,
            "city_id": city_id,
            "new_city_name": new_city_name,
            "new_city_country": new_country,
            "new_city_region": new_region,
            "new_city_lat": new_lat,
            "new_city_lon": new_lon,
            "name": nm,
            "address": _clean(address, 300),
            "details": json.dumps(clean_details, ensure_ascii=False),
            "contact": contact_value,
            "contact_kind": contact_kind,
            "author": int(author_telegram_id) if author_telegram_id is not None else None,
            "bind_token": bind_token,
            "ip_hash": client_ip_hash(client_ip),
        },
    )
    sid = int(r.scalar_one())
    await session.commit()

    try:
        await notify_admins_new_place_suggestion(sid)
    except Exception:  # noqa: BLE001
        logger.exception("notify admins after place suggestion failed suggestion_id=%s", sid)

    return {"id": sid, "bind_token": bind_token}
