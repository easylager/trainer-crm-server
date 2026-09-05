"""
Arena catalog media (TASK-049).

Trainer photos stay in ``trainer_photos`` (unchanged readers).
Arena hero and gallery live in ``media`` with ``owner_type='arena'``.
``license`` is required; non-``own`` rows need ``source_url`` or ``attribution``.
Do not scrape search-engine images.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.photo_cdn import public_photo_url
from src.application.trainer_use_cases import MAX_TRAINER_PHOTO_BYTES, trainer_photo_bytes_look_like_image
from src.infrastructure import s3
from src.shared.config import Settings

MEDIA_OWNER_ARENA = "arena"
MEDIA_OWNER_COACH = "coach"
MEDIA_OWNER_COLLECTIVE = "collective"
MEDIA_OWNER_TYPES = (MEDIA_OWNER_ARENA, MEDIA_OWNER_COACH, MEDIA_OWNER_COLLECTIVE)

MEDIA_LICENSE_OWN = "own"
MEDIA_LICENSES = frozenset({"own", "operator", "user", "permitted"})

MEDIA_STATUS_PENDING = "pending"
MEDIA_STATUS_PUBLISHED = "published"
MEDIA_STATUS_REJECTED = "rejected"
MEDIA_STATUSES = (MEDIA_STATUS_PENDING, MEDIA_STATUS_PUBLISHED, MEDIA_STATUS_REJECTED)

ARENA_MEDIA_MAX = 6
VARIANT_KEYS = ("thumb", "card", "hero")


class InvalidMediaLicenseError(ValueError):
    """License missing, unknown, or non-own without source/attribution."""


class ArenaMediaLimitError(ValueError):
    """Arena already has the maximum number of photos."""


class InvalidArenaMediaOrderError(ValueError):
    """Reorder payload does not match this arena's media ids."""


def validate_media_license(
    license_key: str | None,
    *,
    source_url: str | None = None,
    attribution: str | None = None,
) -> str:
    value = (license_key or "").strip()
    if value not in MEDIA_LICENSES:
        raise InvalidMediaLicenseError("license must be own|operator|user|permitted")
    if value != MEDIA_LICENSE_OWN:
        src = (source_url or "").strip()
        attr = (attribution or "").strip()
        if not src and not attr:
            raise InvalidMediaLicenseError("non-own license requires source_url or attribution")
    return value


def assert_can_add_arena_media(current_count: int) -> None:
    if int(current_count) >= ARENA_MEDIA_MAX:
        raise ArenaMediaLimitError(f"arena may have at most {ARENA_MEDIA_MAX} photos")


def pick_hero_media(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """First published row by sort_order, then id. Pending/rejected never become hero."""
    published = [
        dict(row)
        for row in rows
        if (row.get("status") or "") == MEDIA_STATUS_PUBLISHED
    ]
    published.sort(key=lambda r: (int(r.get("sort_order") or 0), int(r.get("id") or 0)))
    return published[0] if published else None


def serialize_arena_media_payload(
    rows: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Public/admin media block. Missing photos → hero None and empty gallery, never omit keys."""
    items = list(rows or [])
    hero = pick_hero_media(items)
    gallery = [
        dict(row)
        for row in items
        if (row.get("status") or "") == MEDIA_STATUS_PUBLISHED
    ]
    gallery.sort(key=lambda r: (int(r.get("sort_order") or 0), int(r.get("id") or 0)))
    return {"hero": hero, "gallery": gallery}


def _publicize_item(row: Mapping[str, Any], cdn_base: str | None) -> dict[str, Any]:
    variants_in = row.get("variants") or {}
    variants: dict[str, str] = {}
    if isinstance(variants_in, Mapping):
        for key in VARIANT_KEYS:
            raw = variants_in.get(key)
            url = public_photo_url(str(raw) if raw else None, cdn_base=cdn_base)
            if url:
                variants[key] = url
    return {
        "id": row.get("id"),
        "sort_order": row.get("sort_order"),
        "status": row.get("status"),
        "license": row.get("license"),
        "attribution": row.get("attribution"),
        "source_url": row.get("source_url"),
        "blurhash": row.get("blurhash"),
        "width": row.get("width"),
        "height": row.get("height"),
        "variants": variants,
    }


def publicize_arena_media_payload(
    payload: Mapping[str, Any],
    *,
    cdn_base: str | None = None,
) -> dict[str, Any]:
    """Map storage keys in variants to public URLs. Never leak storage_key."""
    hero = payload.get("hero")
    gallery = payload.get("gallery") or []
    return {
        "hero": _publicize_item(hero, cdn_base) if isinstance(hero, Mapping) else None,
        "gallery": [
            _publicize_item(item, cdn_base) for item in gallery if isinstance(item, Mapping)
        ],
    }


def _media_row_dict(row: Any) -> dict[str, Any]:
    variants = row[4]
    if isinstance(variants, str):
        variants = json.loads(variants)
    return {
        "id": int(row[0]),
        "owner_type": row[1],
        "owner_id": int(row[2]),
        "storage_key": row[3],
        "variants": variants or {},
        "width": row[5],
        "height": row[6],
        "blurhash": row[7],
        "license": row[8],
        "attribution": row[9],
        "source_url": row[10],
        "sort_order": int(row[11] or 0),
        "status": row[12],
    }


async def load_media_for_owners(
    session: AsyncSession,
    owner_type: str,
    owner_ids: Sequence[int],
) -> dict[int, list[dict[str, Any]]]:
    ids = [int(x) for x in owner_ids]
    out: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
    if not ids:
        return out
    placeholders = ", ".join(f":oid{i}" for i in range(len(ids)))
    params: dict[str, Any] = {"owner_type": owner_type}
    params.update({f"oid{i}": v for i, v in enumerate(ids)})
    result = await session.execute(
        text(
            f"""
            SELECT id, owner_type, owner_id, storage_key, variants, width, height, blurhash,
                   license, attribution, source_url, sort_order, status
            FROM media
            WHERE owner_type = :owner_type AND owner_id IN ({placeholders})
            ORDER BY owner_id, sort_order, id
            """
        ),
        params,
    )
    for row in result.fetchall():
        item = _media_row_dict(row)
        out.setdefault(item["owner_id"], []).append(item)
    return out


async def attach_arena_media_payloads(
    session: AsyncSession,
    items: list[dict[str, Any]],
    *,
    cdn_base: str | None = None,
) -> None:
    """Mutate arena dicts in place with public hero/gallery (empty-safe)."""
    if cdn_base is None:
        cdn_base = Settings().photo_cdn_base_url
    ids = [int(item["id"]) for item in items if item.get("id") is not None]
    by_owner = await load_media_for_owners(session, MEDIA_OWNER_ARENA, ids)
    for item in items:
        aid = item.get("id")
        raw = serialize_arena_media_payload(by_owner.get(int(aid), []) if aid is not None else [])
        pub = publicize_arena_media_payload(raw, cdn_base=cdn_base)
        item["hero"] = pub["hero"]
        item["gallery"] = pub["gallery"]


async def upload_arena_media_from_bytes(
    session: AsyncSession,
    arena_id: int,
    body: bytes,
    content_type: str,
    *,
    license_key: str | None,
    source_url: str | None = None,
    attribution: str | None = None,
) -> dict[str, Any]:
    """Resize to thumb/card/hero, persist ``media`` row as published. Does not commit."""
    license_value = validate_media_license(
        license_key, source_url=source_url, attribution=attribution
    )
    exists = await session.execute(text("SELECT 1 FROM arenas WHERE id = :id"), {"id": arena_id})
    if not exists.fetchone():
        raise LookupError("arena not found")
    if len(body) > MAX_TRAINER_PHOTO_BYTES:
        raise ValueError("too_large")
    if not trainer_photo_bytes_look_like_image(body):
        raise ValueError("not_image")
    count_r = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM media
            WHERE owner_type = :ot AND owner_id = :oid
            """
        ),
        {"ot": MEDIA_OWNER_ARENA, "oid": arena_id},
    )
    assert_can_add_arena_media(int(count_r.scalar_one() or 0))
    uploaded = s3.upload_arena_photo(arena_id, body, content_type)
    sort_r = await session.execute(
        text(
            """
            SELECT COALESCE(MAX(sort_order), -1) FROM media
            WHERE owner_type = :ot AND owner_id = :oid
            """
        ),
        {"ot": MEDIA_OWNER_ARENA, "oid": arena_id},
    )
    next_sort = int(sort_r.scalar_one() or -1) + 1
    src = (source_url or "").strip() or None
    attr = (attribution or "").strip() or None
    ins = await session.execute(
        text(
            """
            INSERT INTO media (
                owner_type, owner_id, storage_key, variants, width, height, blurhash,
                license, attribution, source_url, sort_order, status
            ) VALUES (
                :owner_type, :owner_id, :storage_key, CAST(:variants AS jsonb),
                :width, :height, NULL, :license, :attribution, :source_url,
                :sort_order, :status
            )
            RETURNING id, owner_type, owner_id, storage_key, variants, width, height, blurhash,
                      license, attribution, source_url, sort_order, status
            """
        ),
        {
            "owner_type": MEDIA_OWNER_ARENA,
            "owner_id": arena_id,
            "storage_key": uploaded["storage_key"],
            "variants": json.dumps(uploaded["variants"]),
            "width": uploaded.get("width"),
            "height": uploaded.get("height"),
            "license": license_value,
            "attribution": attr,
            "source_url": src,
            "sort_order": next_sort,
            "status": MEDIA_STATUS_PUBLISHED,
        },
    )
    row = ins.fetchone()
    if row is None:
        raise RuntimeError("media insert returned no row")
    raw = serialize_arena_media_payload([_media_row_dict(row)])
    published = publicize_arena_media_payload(raw, cdn_base=Settings().photo_cdn_base_url)
    hero = published["hero"]
    if not isinstance(hero, dict):
        raise RuntimeError("published media insert produced no hero")
    return hero


async def reorder_arena_media(
    session: AsyncSession,
    arena_id: int,
    ids: Sequence[int],
) -> None:
    by_owner = await load_media_for_owners(session, MEDIA_OWNER_ARENA, [arena_id])
    have = {int(row["id"]) for row in by_owner.get(arena_id, [])}
    want = [int(x) for x in ids]
    if set(want) != have or len(want) != len(have):
        raise InvalidArenaMediaOrderError("ids must list every photo of this arena exactly once")
    for sort_order, media_id in enumerate(want):
        await session.execute(
            text(
                """
                UPDATE media SET sort_order = :so
                WHERE id = :id AND owner_type = :ot AND owner_id = :oid
                """
            ),
            {
                "so": sort_order,
                "id": media_id,
                "ot": MEDIA_OWNER_ARENA,
                "oid": arena_id,
            },
        )


async def delete_arena_media(session: AsyncSession, arena_id: int, media_id: int) -> None:
    """Drop the DB row. Storage objects are left in place (EDGE-002)."""
    result = await session.execute(
        text(
            """
            DELETE FROM media
            WHERE id = :id AND owner_type = :ot AND owner_id = :oid
            """
        ),
        {"id": media_id, "ot": MEDIA_OWNER_ARENA, "oid": arena_id},
    )
    if result.rowcount == 0:
        raise LookupError("media not found")
