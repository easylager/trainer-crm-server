"""
Trainer self-service arena creation (TASK-046).

Unlike the old `pending_request` flow (a text message to support, no real row — see
`trainer_arena_setup_use_cases.py`), this creates a real `arenas` row synchronously so
the trainer can use it immediately. Moderation happens post-hoc: `is_confirmed=false`
keeps it hidden from the public client catalog (`GET /api/public/arenas`) until an
admin confirms it, while trainers of the same city already see and can select it.
"""
from __future__ import annotations

import logging
import math
import os
import re
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.repositories.trainer_repository import TrainerRepository

logger = logging.getLogger(__name__)

NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
GEOCODE_TIMEOUT_SEC = 4.0
DUPLICATE_RADIUS_METERS = 150.0
_EARTH_RADIUS_M = 6371000.0

ARENA_NAME_MAX_LEN = 128
ARENA_ADDRESS_MAX_LEN = 512


def _normalize_arena_name(name: str) -> str:
    """Lowercase, strip punctuation/extra spaces — loose match for duplicate detection."""
    s = (name or "").strip().lower()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


async def _geocode_address(address: str, city_name: str) -> tuple[float, float] | None:
    """
    Best-effort synchronous geocode via Nominatim (same provider/policy as
    ``scripts/geocode_arena_addresses.py``). One request per trainer submission —
    not a batch loop, so within Nominatim's fair-use policy. Never raises: a failed
    or missing geocode must not block arena creation (EDGE-002); an admin can fix
    coordinates during moderation.
    """
    addr = (address or "").strip()
    if not addr:
        return None
    city = (city_name or "").strip()
    query = addr if (city and city.lower() in addr.lower()) else (f"{addr}, {city}" if city else addr)
    contact = os.environ.get("GEOCODE_CONTACT_EMAIL", "").strip() or "ops@local.invalid"
    user_agent = f"TrainerCRM-ArenaGeocode/1.0 ({contact})"
    try:
        async with httpx.AsyncClient(timeout=GEOCODE_TIMEOUT_SEC) as client:
            r = await client.get(
                NOMINATIM_SEARCH,
                params={
                    "q": query,
                    "format": "json",
                    "limit": "1",
                    "countrycodes": "by",
                    "addressdetails": "0",
                },
                headers={"User-Agent": user_agent, "Accept-Language": "ru,be,en"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        logger.info("trainer_arena_create: geocoding failed for address=%r", address, exc_info=True)
        return None
    if not data:
        return None
    try:
        return float(data[0]["lat"]), float(data[0]["lon"])
    except (KeyError, ValueError, TypeError, IndexError):
        return None


async def find_possible_duplicate_arenas(
    session: AsyncSession,
    city_id: int,
    *,
    name: str,
    latitude: float | None,
    longitude: float | None,
) -> list[dict[str, Any]]:
    """
    Soft duplicate check (AC-005): active arenas in the same city that match by
    normalized name or fall within ~150m. Returns candidates for a non-blocking
    warning — the caller decides whether to proceed anyway (``confirm_duplicate``).
    """
    r = await session.execute(
        text("SELECT id, name, address, latitude, longitude FROM arenas WHERE city_id = :cid AND is_active"),
        {"cid": city_id},
    )
    rows = r.fetchall()
    norm_target = _normalize_arena_name(name)
    out: list[dict[str, Any]] = []
    for aid, aname, aaddress, alat, alon in rows:
        distance_m: float | None = None
        matched = bool(norm_target) and _normalize_arena_name(aname) == norm_target
        if latitude is not None and longitude is not None and alat is not None and alon is not None:
            distance_m = _haversine_meters(latitude, longitude, float(alat), float(alon))
            if distance_m <= DUPLICATE_RADIUS_METERS:
                matched = True
        if matched:
            out.append(
                {
                    "arena_id": aid,
                    "name": aname,
                    "address": aaddress,
                    "distance_m": round(distance_m, 1) if distance_m is not None else None,
                }
            )
    return out


async def create_trainer_arena(
    session: AsyncSession,
    trainer_id: int,
    *,
    name: str,
    address: str,
    confirm_duplicate: bool = False,
    city_id: int | None = None,
) -> dict[str, Any]:
    """
    Create a real, unconfirmed arena from the trainer profile screen (AC-002/AC-003).
    Auto-attaches the creator (``trainer_arenas``) so it's usable without an extra click.

    ``city_id`` may be passed explicitly when the trainer selected a city in the form but
    has not pressed Save yet (draft profile). In that case we persist ``profile.city_id``
    before creating the arena so list/create stay consistent.

    Returns ``{"status": "duplicate_warning", "duplicates": [...]}`` without writing
    when a likely duplicate is found and not overridden (AC-005), else
    ``{"status": "created", "arena_id": int, "trainer": {...}}``.
    """
    nm = (name or "").strip()
    if not nm:
        raise ValueError("Укажите название арены.")
    if len(nm) > ARENA_NAME_MAX_LEN:
        raise ValueError(f"Название арены — не длиннее {ARENA_NAME_MAX_LEN} символов.")
    addr = (address or "").strip()
    if not addr:
        raise ValueError("Укажите адрес арены.")
    if len(addr) > ARENA_ADDRESS_MAX_LEN:
        raise ValueError(f"Адрес — не длиннее {ARENA_ADDRESS_MAX_LEN} символов.")

    repo = TrainerRepository(session)
    trainer = await repo.get_by_id(trainer_id)
    if not trainer:
        raise LookupError("trainer not found")
    profile = trainer.get("profile") if isinstance(trainer.get("profile"), dict) else {}
    profile_city = profile.get("city_id")
    if city_id is not None:
        resolved_city_id = int(city_id)
    elif profile_city:
        resolved_city_id = int(profile_city)
    else:
        raise ValueError("Сначала укажите город в профиле.")

    if profile_city is None or int(profile_city) != resolved_city_id:
        await repo.ensure_trainer_profile_row(trainer_id)
        await repo.update_profile(trainer_id, city_id=resolved_city_id)
        await session.flush()

    city_id = resolved_city_id

    city_row = (
        await session.execute(text("SELECT name FROM cities WHERE id = :cid"), {"cid": city_id})
    ).fetchone()
    city_name = str(city_row[0]).strip() if city_row and city_row[0] else ""

    coords = await _geocode_address(addr, city_name)
    lat, lon = coords if coords else (None, None)

    if not confirm_duplicate:
        duplicates = await find_possible_duplicate_arenas(session, city_id, name=nm, latitude=lat, longitude=lon)
        if duplicates:
            return {"status": "duplicate_warning", "duplicates": duplicates}

    ins = await session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, latitude, longitude, is_active,
                                 is_confirmed, created_by_trainer_id)
            VALUES (:city_id, :name, :address, :lat, :lon, true, false, :trainer_id)
            RETURNING id
            """
        ),
        {
            "city_id": city_id,
            "name": nm,
            "address": addr,
            "lat": lat,
            "lon": lon,
            "trainer_id": trainer_id,
        },
    )
    arena_id = ins.scalar_one()
    await session.execute(
        text(
            """
            INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:trainer_id, :arena_id)
            ON CONFLICT (trainer_id, arena_id) DO NOTHING
            """
        ),
        {"trainer_id": trainer_id, "arena_id": arena_id},
    )
    from src.application.arena_profile import ensure_arena_profile

    await ensure_arena_profile(session, int(arena_id), city_id=city_id, name=nm)
    await session.commit()
    updated_trainer = await repo.get_by_id(trainer_id)
    return {"status": "created", "arena_id": arena_id, "trainer": updated_trainer}
