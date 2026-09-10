"""
Arena catalog profile (TASK-048): slug, amenities, season, district helpers.

``arenas`` stays the trainer-workplace dictionary (name, address, coords, ``is_confirmed``).
Vitrine fields live on ``arena_profiles`` (1:1). ``status`` (draft|published|archived) is
publication of the Ice Discovery card — not the same as ``arenas.is_confirmed`` (moderation
of trainer-created workplaces, TASK-046).
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ARENA_PROFILE_STATUS_DRAFT = "draft"
ARENA_PROFILE_STATUS_PUBLISHED = "published"
ARENA_PROFILE_STATUS_ARCHIVED = "archived"
ARENA_PROFILE_STATUSES = (
    ARENA_PROFILE_STATUS_DRAFT,
    ARENA_PROFILE_STATUS_PUBLISHED,
    ARENA_PROFILE_STATUS_ARCHIVED,
)

# Canonical amenity keys (prototype chips + accessibility). Values are bool.
AMENITY_KEYS = frozenset(
    {
        "skate_rental",  # прокат
        "skate_sharpening",  # заточка
        "parking",  # парковка
        "locker_rooms",  # раздевалки
        "cafe",  # кафе
        "accessibility",  # доступность
    }
)

AMENITY_LABELS_RU = {
    "skate_rental": "Прокат",
    "skate_sharpening": "Заточка",
    "parking": "Парковка",
    "locker_rooms": "Раздевалки",
    "cafe": "Кафе",
    "accessibility": "Доступность",
}

_CYRILLIC_TO_LATIN = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


class InvalidAmenitiesError(ValueError):
    """Unknown amenity key or non-bool value — reject on write, do not store silently."""


class InvalidArenaProfileStatusError(ValueError):
    """status must be draft | published | archived."""


def slugify_arena_name(name: str) -> str:
    """Transliterate a venue name to a URL-safe slug. Stable for the same input."""
    raw = (name or "").strip().lower()
    chars: list[str] = []
    for ch in raw:
        if ch in _CYRILLIC_TO_LATIN:
            chars.append(_CYRILLIC_TO_LATIN[ch])
        elif ch.isascii() and (ch.isalnum() or ch in "-_"):
            chars.append(ch)
        else:
            chars.append("-")
    slug = re.sub(r"-+", "-", "".join(chars)).strip("-")
    return slug or "arena"


def choose_arena_slug(
    base: str,
    *,
    taken: set[str],
    district: str | None,
    arena_id: int,
) -> str:
    """
    Pick a city-unique slug. Prefer the name slug; on collision append district, then id.

    Existing values in ``taken`` are never reused. Callers that already have a slug
    must not call this — backfill is idempotent only if it skips assigned slugs.
    """
    if base not in taken:
        return base
    if district:
        with_district = f"{base}-{slugify_arena_name(district)}"
        if with_district not in taken:
            return with_district
    return f"{base}-{int(arena_id)}"


def validate_amenities(value: Mapping[str, Any] | None) -> dict[str, bool]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise InvalidAmenitiesError("amenities must be an object")
    out: dict[str, bool] = {}
    for key, raw in value.items():
        if key not in AMENITY_KEYS:
            raise InvalidAmenitiesError(f"unknown amenity key: {key}")
        if not isinstance(raw, bool):
            raise InvalidAmenitiesError(f"amenity {key} must be a boolean")
        out[str(key)] = raw
    return out


def public_http_url(raw: Any) -> str | None:
    """http(s) only. Empty, javascript:, or whitespace in the value → None."""
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    lower = value.lower()
    if not (lower.startswith("https://") or lower.startswith("http://")):
        return None
    if any(ch.isspace() or ch in "<>\"'" for ch in value):
        return None
    if len(value) > 512:
        return None
    return value


def validate_profile_status(status: str | None) -> str:
    value = (status or ARENA_PROFILE_STATUS_PUBLISHED).strip()
    if value not in ARENA_PROFILE_STATUSES:
        raise InvalidArenaProfileStatusError(f"invalid arena profile status: {value}")
    return value


def is_in_season(start_month: int | None, end_month: int | None, month: int) -> bool:
    """True when ``month`` (1–12) falls in the season, including ranges that wrap New Year."""
    if start_month is None or end_month is None:
        return True
    start, end = int(start_month), int(end_month)
    m = int(month)
    if start <= end:
        return start <= m <= end
    return m >= start or m <= end


def district_from_nominatim_address(address: Mapping[str, Any] | None) -> str | None:
    """Prefer administrative district over micro-area labels (EDGE-002: report leftovers)."""
    if not address:
        return None
    for key in ("city_district", "suburb", "quarter", "neighbourhood"):
        val = str(address.get(key) or "").strip()
        if val:
            return val
    return None


def nominatim_result_matches_city(address: Mapping[str, Any] | None, city_name: str) -> bool:
    """True when reverse geocode looks like the arena's city, or when Nominatim omitted city."""
    expected = (city_name or "").strip().lower()
    if not address or not expected:
        return True
    candidates = [
        str(address.get(key) or "").strip().lower()
        for key in ("city", "town", "village", "municipality")
    ]
    candidates = [c for c in candidates if c]
    if not candidates:
        return True
    return any(expected in c or c in expected for c in candidates)


def serialize_arena_list_item(
    arena: Mapping[str, Any],
    *,
    district: str | None = None,
    slug: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Public/admin list row. ``district=None`` is a present field, not a reason to drop the row."""
    out = dict(arena)
    out["district"] = district
    if slug is not None:
        out["slug"] = slug
    if status is not None:
        out["status"] = status
    return out


async def slugs_taken_in_city(
    session: AsyncSession, city_id: int, *, exclude_arena_id: int | None = None
) -> set[str]:
    r = await session.execute(
        text(
            """
            SELECT slug FROM arena_profiles
            WHERE city_id = :cid
              AND (CAST(:exclude_id AS INTEGER) IS NULL OR arena_id <> CAST(:exclude_id AS INTEGER))
            """
        ),
        {"cid": city_id, "exclude_id": exclude_arena_id},
    )
    return {str(row[0]) for row in r.fetchall() if row[0]}


async def allocate_arena_slug(
    session: AsyncSession,
    *,
    city_id: int,
    name: str,
    arena_id: int,
    district: str | None = None,
    existing_slug: str | None = None,
) -> str:
    """Return the already-issued slug, or a new unique-in-city slug. Never rewrites existing."""
    current = (existing_slug or "").strip()
    if current:
        return current
    taken = await slugs_taken_in_city(session, city_id, exclude_arena_id=arena_id)
    return choose_arena_slug(
        slugify_arena_name(name), taken=taken, district=district, arena_id=arena_id
    )


async def ensure_arena_profile(
    session: AsyncSession,
    arena_id: int,
    *,
    city_id: int,
    name: str,
    district: str | None = None,
    status: str = ARENA_PROFILE_STATUS_PUBLISHED,
) -> str:
    """Insert a profile if missing; return the (stable) slug. Does not overwrite an existing slug."""
    existing = (
        await session.execute(
            text("SELECT slug FROM arena_profiles WHERE arena_id = :id"),
            {"id": arena_id},
        )
    ).fetchone()
    if existing and existing[0]:
        return str(existing[0])
    slug = await allocate_arena_slug(
        session,
        city_id=city_id,
        name=name,
        arena_id=arena_id,
        district=district,
        existing_slug=None,
    )
    await session.execute(
        text(
            """
            INSERT INTO arena_profiles (arena_id, city_id, slug, district, status, amenities, social_urls)
            VALUES (:arena_id, :city_id, :slug, :district, :status, '{}'::jsonb, '{}'::jsonb)
            ON CONFLICT (arena_id) DO NOTHING
            """
        ),
        {
            "arena_id": arena_id,
            "city_id": city_id,
            "slug": slug,
            "district": (district or "").strip() or None,
            "status": validate_profile_status(status),
        },
    )
    return slug


async def backfill_arena_profiles(session: AsyncSession) -> dict[str, int]:
    """
    Create missing profiles and fill empty slugs for active arenas.
    Already-issued slugs are left untouched (AC-001 idempotent).
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT a.id, a.city_id, a.name, a.is_active, p.slug, p.district
                FROM arenas a
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                WHERE a.is_active
                ORDER BY a.id
                """
            )
        )
    ).fetchall()
    created = 0
    filled = 0
    for arena_id, city_id, name, _is_active, slug, district in rows:
        if slug:
            continue
        before = (
            await session.execute(
                text("SELECT 1 FROM arena_profiles WHERE arena_id = :id"),
                {"id": arena_id},
            )
        ).fetchone()
        await ensure_arena_profile(
            session,
            int(arena_id),
            city_id=int(city_id),
            name=str(name or ""),
            district=str(district) if district else None,
        )
        if before:
            filled += 1
        else:
            created += 1
    return {"created": created, "filled": filled, "active": len(rows)}


def _optional_month(value: Any) -> int | None:
    if value is None or value == "":
        return None
    month = int(value)
    if month < 1 or month > 12:
        raise ValueError("season month must be 1–12")
    return month


_PROFILE_STRING_FIELDS = (
    "phone",
    "website_url",
    "short_description",
    "district",
    "timezone",
)


async def apply_admin_arena_profile_patch(
    session: AsyncSession,
    arena_id: int,
    fields: Mapping[str, Any],
) -> None:
    """Upsert vitrine fields. Unknown amenity keys raise InvalidAmenitiesError."""
    arena = (
        await session.execute(
            text("SELECT id, city_id, name FROM arenas WHERE id = :id"),
            {"id": arena_id},
        )
    ).fetchone()
    if arena is None:
        raise LookupError("Arena not found")
    _arena_id, city_id, name = int(arena[0]), int(arena[1]), str(arena[2] or "")
    await ensure_arena_profile(session, _arena_id, city_id=city_id, name=name)

    assignments: list[str] = []
    params: dict[str, Any] = {"id": _arena_id}
    if "city_id" in fields and fields["city_id"] is not None:
        assignments.append("city_id = :city_id")
        params["city_id"] = int(fields["city_id"])
    for key in _PROFILE_STRING_FIELDS:
        if key not in fields:
            continue
        raw = fields[key]
        assignments.append(f"{key} = :{key}")
        params[key] = (str(raw).strip() or None) if raw is not None else None
    if "social_urls" in fields:
        val = fields["social_urls"]
        if val is not None and not isinstance(val, dict):
            raise ValueError("social_urls must be an object")
        assignments.append("social_urls = CAST(:social_urls AS jsonb)")
        params["social_urls"] = json.dumps(val if isinstance(val, dict) else {})
    if "opening_hours" in fields:
        val = fields["opening_hours"]
        if val is not None and not isinstance(val, dict):
            raise ValueError("opening_hours must be an object")
        assignments.append("opening_hours = CAST(:opening_hours AS jsonb)")
        params["opening_hours"] = json.dumps(val) if val is not None else None
    if "season_start_month" in fields:
        assignments.append("season_start_month = :season_start_month")
        params["season_start_month"] = _optional_month(fields["season_start_month"])
    if "season_end_month" in fields:
        assignments.append("season_end_month = :season_end_month")
        params["season_end_month"] = _optional_month(fields["season_end_month"])
    if "amenities" in fields:
        amenities = validate_amenities(fields["amenities"])
        assignments.append("amenities = CAST(:amenities AS jsonb)")
        params["amenities"] = json.dumps(amenities)
    if "status" in fields and fields["status"] is not None:
        assignments.append("status = :status")
        params["status"] = validate_profile_status(str(fields["status"]))
    if "tickets_url" in fields:
        raw = fields["tickets_url"]
        if raw is None or str(raw).strip() == "":
            assignments.append("tickets_url = :tickets_url")
            params["tickets_url"] = None
        else:
            url = public_http_url(raw)
            if not url:
                raise ValueError("tickets_url must be an http(s) URL")
            assignments.append("tickets_url = :tickets_url")
            params["tickets_url"] = url
    if not assignments:
        return
    await session.execute(
        text("UPDATE arena_profiles SET " + ", ".join(assignments) + " WHERE arena_id = :id"),
        params,
    )
