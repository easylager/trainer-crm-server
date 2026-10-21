"""Подборка «Для вас»: до трёх мест города.

Закреп админа на позицию 1–3 сильнее алгоритма. Свободные позиции заполняет
``choose_candidates`` — популярность места за 30 дней. Это точка расширения:
личный сигнал подставляется сюда, когда он появится. Пустую позицию ничем не добиваем.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_city_day import DEFAULT_TIMEZONE
from src.application.place_links import place_path
from src.application.style_b import b_photo_url
from src.shared.catalog_sharpening import row_in_sharpening_section
from src.shared.config import Settings
from src.shared.copy_ru import t
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
from src.shared.public_display import format_public_name
from src.shared.venue_types import VENUE_TYPE_SHOP, has_public_skating, normalize_venue_type, venue_type_noun

_CACHE_TTL_SEC = 300.0
_CACHE: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_SCORE_WINDOW = timedelta(days=30)
_CONTACT_WEIGHT = 5

_PLACES_SQL = text(
    f"""
    SELECT a.id, a.name, COALESCE(a.venue_type, 'ice') AS venue_type,
           a.is_active, a.is_confirmed, a.created_by_trainer_id,
           c.name AS city_name, c.country, c.is_active AS city_is_active,
           p.slug, p.amenities, p.season_start_month, p.season_end_month,
           p.status AS profile_status,
           pk.position AS pin_position,
           EXISTS (
               SELECT 1 FROM media m
               WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
           ) AS has_photo,
           (
               SELECT m.variants
               FROM media m
               WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
               ORDER BY m.sort_order, m.id
               LIMIT 1
           ) AS photo_variants
    FROM arenas a
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    LEFT JOIN city_picks pk ON pk.city_id = a.city_id AND pk.arena_id = a.id
    WHERE a.city_id = :city_id AND {PUBLIC_ARENA_VISIBLE_SQL}
    """
)

_SCORES_SQL = text(
    """
    SELECT e.arena_id,
           COUNT(*) FILTER (WHERE e.kind = 'public_page_view')::int AS views,
           -- Партнёр рядом (partner_*) — не интерес к катку: в счёт подборки не идёт.
           COUNT(*) FILTER (
               WHERE e.kind = 'public_contact_click'
                 AND COALESCE(e.payload->>'action', '') NOT IN ('partner_open', 'partner_show', 'coach_open', 'coach_join')
           )::int AS clicks
    FROM catalog_consumer_events e
    JOIN arenas a ON a.id = e.arena_id
    WHERE a.city_id = :city_id
      AND e.arena_id IS NOT NULL
      AND e.occurred_at >= :since
      AND e.kind IN ('public_page_view', 'public_contact_click')
    GROUP BY e.arena_id
    """
)


def enabled_city_ids(settings: Settings | None = None) -> set[int]:
    raw = (settings or Settings()).for_you_city_ids or ""
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit() and int(part) > 0:
            out.add(int(part))
    return out


def city_enabled(city_id: int | None, settings: Settings | None = None) -> bool:
    if city_id is None or int(city_id) <= 0:
        return False
    return int(city_id) in enabled_city_ids(settings)


def clear_for_you_cache(city_id: int | None = None) -> None:
    if city_id is None:
        _CACHE.clear()
        return
    _CACHE.pop(int(city_id), None)


def section_kind(row: Mapping[str, Any], *, month: int) -> tuple[str, str]:
    """Вид места — тот же, что раздел Mini App «Заточка» / «Магазины».

    Заточка проверяется ``row_in_sharpening_section``. Остальные — тип площадки,
    подпись как в карточке каталога (``venue_type_noun``).
    """
    venue = normalize_venue_type(row.get("venue_type"))
    # Каток с услугой заточки — всё равно каток: подпись «Заточка» у Ледового дворца врала.
    if has_public_skating(venue):
        return venue, venue_type_noun(venue)
    if row_in_sharpening_section(row, month=month):
        return "service", t("route.service")
    if venue == VENUE_TYPE_SHOP:
        return "shop", venue_type_noun(venue)
    return venue, venue_type_noun(venue)


def choose_candidates(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Кого алгоритм ставит на свободные позиции, по убыванию.

    Точка расширения под личный сигнал. Сейчас: публичные места города кроме
    катков, с фото раньше, счёт уже посчитан на строке, при равенстве — имя.
    """
    # Катки — крытые и уличные — и так идут списком «Покататься» под подборкой.
    eligible = [dict(row) for row in rows if not has_public_skating(row.get("venue_type"))]
    eligible = [row for row in eligible if str(row.get("slug") or "").strip()]
    eligible.sort(
        key=lambda row: (
            0 if row.get("has_photo") else 1,
            -int(row.get("score") or 0),
            str(row.get("sort_name") or "").casefold(),
            int(row["id"]),
        )
    )
    return eligible


def fill_slots(
    ranked: list[Mapping[str, Any]],
    pins: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any] | None]:
    """Три позиции. Закреп остаётся на своём месте. Третий подряд одного вида не ставим."""
    slots: list[dict[str, Any] | None] = [None, None, None]
    used: set[int] = set()
    for position, pin in pins.items():
        index = int(position) - 1
        arena_id = int(pin["arena_id"])
        if index < 0 or index > 2 or arena_id in used:
            continue
        slots[index] = dict(pin)
        used.add(arena_id)
    for index in range(3):
        if slots[index] is not None:
            continue
        chosen: Mapping[str, Any] | None = None
        for candidate in ranked:
            arena_id = int(candidate["arena_id"])
            if arena_id in used:
                continue
            if _three_of_a_kind(slots, index, str(candidate.get("kind") or "")):
                continue
            chosen = candidate
            break
        if chosen is None:
            continue
        slots[index] = dict(chosen)
        used.add(int(chosen["arena_id"]))
    return slots


def _three_of_a_kind(slots: list[dict[str, Any] | None], index: int, kind: str) -> bool:
    kinds: list[str | None] = []
    for i, slot in enumerate(slots):
        if i == index:
            kinds.append(kind)
        elif slot is None:
            kinds.append(None)
        else:
            kinds.append(str(slot.get("kind") or ""))
    return kinds[0] is not None and kinds[0] == kinds[1] == kinds[2]


async def for_you(
    session: AsyncSession,
    city_id: int,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """До трёх мест по позициям. Город вне ``FOR_YOU_CITY_IDS`` — пусто."""
    if not city_enabled(city_id):
        return []
    cid = int(city_id)
    cached = _CACHE.get(cid)
    now_mono = time.monotonic()
    if cached is not None and now_mono - cached[0] < _CACHE_TTL_SEC:
        return [dict(item) for item in cached[1]]
    slots = await compose_slots(session, cid, now=now)
    items = [_public_item(slot) for slot in slots if slot is not None]
    _CACHE[cid] = (now_mono, items)
    return [dict(item) for item in items]


async def compose_slots(
    session: AsyncSession,
    city_id: int,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any] | None]:
    """Три слота с дырками. Нужны админке, чтобы сказать «по алгоритму» на свободной позиции."""
    rows, month = await _load_rows(session, int(city_id), now=now)
    pins: dict[int, dict[str, Any]] = {}
    for row in rows:
        position = row.get("pin_position")
        if position is None:
            continue
        item = _item_from_row(row, month=month, pinned=True)
        if item is None:
            continue
        pins[int(position)] = item
    ranked = []
    for row in choose_candidates(rows):
        item = _item_from_row(row, month=month, pinned=False)
        if item is not None:
            ranked.append(item)
    return fill_slots(ranked, pins)


def _public_item(slot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "arena_id": int(slot["arena_id"]),
        "slug": slot["slug"],
        "name": slot["name"],
        "kind_label": slot["kind_label"],
        "photo_url": slot.get("photo_url"),
        "path": slot["path"],
        "pinned": bool(slot.get("pinned")),
    }


def _item_from_row(row: Mapping[str, Any], *, month: int, pinned: bool) -> dict[str, Any] | None:
    slug = str(row.get("slug") or "").strip()
    city_name = str(row.get("city_name") or "").strip()
    if not slug or not city_name:
        return None
    kind, label = section_kind(row, month=month)
    return {
        "arena_id": int(row["id"]),
        "slug": slug,
        "name": format_public_name(str(row.get("name") or "")),
        "kind": kind,
        "kind_label": label,
        "photo_url": _cover_url(row.get("photo_variants")),
        "path": place_path(city_name=city_name, slug=slug),
        "pinned": pinned,
    }


def _cover_url(raw: Any) -> str | None:
    variants = raw
    if isinstance(variants, str):
        text_value = variants.strip()
        if not text_value:
            return None
        parsed = json.loads(text_value)
        variants = parsed if isinstance(parsed, dict) else {}
    if not isinstance(variants, Mapping):
        return None
    return b_photo_url(variants.get("card") or variants.get("hero") or variants.get("thumb"))


async def _load_rows(
    session: AsyncSession,
    city_id: int,
    *,
    now: datetime | None,
) -> tuple[list[dict[str, Any]], int]:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    month = moment.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).month
    place_rows = (
        await session.execute(_PLACES_SQL, {"city_id": city_id, **public_scope_params()})
    ).mappings().all()
    score_rows = (
        await session.execute(
            _SCORES_SQL,
            {"city_id": city_id, "since": moment - _SCORE_WINDOW},
        )
    ).mappings().all()
    scores = {
        int(row["arena_id"]): int(row["views"] or 0) + _CONTACT_WEIGHT * int(row["clicks"] or 0)
        for row in score_rows
    }
    rows: list[dict[str, Any]] = []
    for row in place_rows:
        item = dict(row)
        item["score"] = scores.get(int(item["id"]), 0)
        item["sort_name"] = format_public_name(str(item.get("name") or ""))
        rows.append(item)
    return rows, month


async def list_pins(session: AsyncSession, city_id: int) -> dict[int, dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT pk.position, pk.arena_id, a.name
                FROM city_picks pk
                JOIN arenas a ON a.id = pk.arena_id
                WHERE pk.city_id = :city_id
                ORDER BY pk.position
                """
            ),
            {"city_id": int(city_id)},
        )
    ).mappings().all()
    return {
        int(row["position"]): {
            "arena_id": int(row["arena_id"]),
            "name": format_public_name(str(row["name"] or "")),
        }
        for row in rows
    }


async def search_city_places(session: AsyncSession, city_id: int, query: str) -> list[dict[str, Any]]:
    needle = query.strip()
    if not needle:
        return []
    rows = (
        await session.execute(
            text(
                f"""
                SELECT a.id, a.name, COALESCE(a.venue_type, 'ice') AS venue_type,
                       a.is_active, a.is_confirmed, a.created_by_trainer_id,
                       c.country, c.is_active AS city_is_active,
                       p.slug, p.amenities, p.season_start_month, p.season_end_month,
                       p.status AS profile_status,
                       EXISTS (
                           SELECT 1 FROM media m
                           WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
                       ) AS has_photo
                FROM arenas a
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                JOIN cities c ON c.id = a.city_id
                WHERE a.city_id = :city_id
                  AND {PUBLIC_ARENA_VISIBLE_SQL}
                  AND a.name ILIKE :q
                ORDER BY a.name, a.id
                LIMIT 20
                """
            ),
            {"city_id": int(city_id), "q": f"%{needle}%", **public_scope_params()},
        )
    ).mappings().all()
    month = datetime.now(timezone.utc).astimezone(ZoneInfo(DEFAULT_TIMEZONE)).month
    items: list[dict[str, Any]] = []
    for row in rows:
        _kind, label = section_kind(row, month=month)
        items.append(
            {
                "arena_id": int(row["id"]),
                "name": format_public_name(str(row["name"] or "")),
                "kind_label": label,
            }
        )
    return items


async def pin_place(session: AsyncSession, city_id: int, position: int, arena_id: int) -> None:
    if int(position) not in (1, 2, 3):
        raise ValueError("position must be 1, 2 or 3")
    found = (
        await session.execute(
            text("SELECT city_id FROM arenas WHERE id = :id"),
            {"id": int(arena_id)},
        )
    ).first()
    if found is None or int(found[0]) != int(city_id):
        raise LookupError("place is not in this city")
    await session.execute(
        text(
            """
            DELETE FROM city_picks
            WHERE city_id = :city_id AND (position = :position OR arena_id = :arena_id)
            """
        ),
        {"city_id": int(city_id), "position": int(position), "arena_id": int(arena_id)},
    )
    await session.execute(
        text(
            """
            INSERT INTO city_picks (city_id, position, arena_id, updated_at)
            VALUES (:city_id, :position, :arena_id, now())
            """
        ),
        {"city_id": int(city_id), "position": int(position), "arena_id": int(arena_id)},
    )
    await session.commit()
    clear_for_you_cache(int(city_id))


async def unpin_place(session: AsyncSession, city_id: int, position: int) -> None:
    if int(position) not in (1, 2, 3):
        raise ValueError("position must be 1, 2 or 3")
    await session.execute(
        text("DELETE FROM city_picks WHERE city_id = :city_id AND position = :position"),
        {"city_id": int(city_id), "position": int(position)},
    )
    await session.commit()
    clear_for_you_cache(int(city_id))
