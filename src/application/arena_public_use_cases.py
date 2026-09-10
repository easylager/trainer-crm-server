"""
Read-only Ice Discovery public API (TASK-051).

Tier A/B/C is computed on read from future public_skate|open_ice sessions and
profile completeness. There is no stored data_tier column.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_media import attach_arena_media_payloads
from src.application.arena_profile import ARENA_PROFILE_STATUS_PUBLISHED, is_in_season
from src.application.ice_session_use_cases import (
    CLIENT_ICE_SESSION_KINDS,
    STATUS_ACTIVE,
    serialize_ice_session,
)
from src.application.subscription_tier_use_cases import get_trainer_booking_availability
from src.application.training_group_use_cases import (
    TG_RECRUITING,
    batch_open_groups_count_for_trainers,
    list_open_training_groups_catalog,
)
from src.application.trainer_use_cases import list_active_trainers_for_client
from src.shared.currency import currency_for_country
from src.shared.ice_discovery_scope import ICE_DISCOVERY_COUNTRY
from src.shared.notification_hours import NOTIFICATION_TZ
from src.shared.public_trainer_payload import sanitize_trainer_for_public_catalog

INTENT_SKATE = "skate"
INTENT_COACH = "coach"
INTENT_GROUP = "group"
ICE_INTENTS = (INTENT_SKATE, INTENT_COACH, INTENT_GROUP)

TIER_A = "A"
TIER_B = "B"
TIER_C = "C"

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 100
SEARCH_LIMIT = 8

# PDEC-005: vitrine shows only slots that have not started. An in-progress
# session is past — live line / pin / hub card all show start time, so
# "12:45 сегодня" at 13:10 is a lie even if the ice is still open.
_CURRENT_SESSION_SQL = """
    s.status = :st
    AND s.kind IN ('public_skate', 'open_ice')
    AND s.starts_at_utc > :now
    AND (s.valid_until IS NULL OR s.valid_until >= :now)
"""


def _today_minsk() -> date:
    """Calendar day for Ice copy and default feed window (UTC+3, no DST)."""
    return datetime.now(ZoneInfo(NOTIFICATION_TZ)).date()


class IcePublicQueryError(ValueError):
    """Invalid public Ice query (bbox, near, intent, missing geo)."""


def compute_data_tier(*, has_future_public_ice: bool, profile_complete: bool) -> str:
    """A = live public ice; B = contacts/photos/hours; C = address only."""
    if has_future_public_ice:
        return TIER_A
    if profile_complete:
        return TIER_B
    return TIER_C


def profile_is_complete(row: Mapping[str, Any]) -> bool:
    phone = str(row.get("phone") or "").strip()
    website = str(row.get("website_url") or "").strip()
    hours = _as_mapping(row.get("opening_hours"))
    has_media = bool(row.get("has_media"))
    return bool(phone or website or hours or has_media)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return round(2 * radius * math.asin(min(1.0, math.sqrt(a))), 2)


def parse_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    if not raw or not str(raw).strip():
        return None
    parts = [p.strip() for p in str(raw).split(",")]
    if len(parts) != 4:
        raise IcePublicQueryError("bbox must be min_lat,min_lon,max_lat,max_lon")
    try:
        min_lat, min_lon, max_lat, max_lon = (float(p) for p in parts)
    except ValueError as exc:
        raise IcePublicQueryError("bbox must be four numbers") from exc
    if min_lat > max_lat:
        min_lat, max_lat = max_lat, min_lat
    if min_lon > max_lon:
        min_lon, max_lon = max_lon, min_lon
    return min_lat, min_lon, max_lat, max_lon


def parse_near(raw: str | None) -> tuple[float, float] | None:
    if not raw or not str(raw).strip():
        return None
    parts = [p.strip() for p in str(raw).split(",")]
    if len(parts) != 2:
        raise IcePublicQueryError("near must be lat,lon")
    try:
        return float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise IcePublicQueryError("near must be two numbers") from exc


def parse_intent(raw: str | None) -> str:
    value = (raw or INTENT_SKATE).strip().lower() or INTENT_SKATE
    if value not in ICE_INTENTS:
        raise IcePublicQueryError("intent must be skate, coach or group")
    return value


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        utc = _as_utc(value)
        return None if utc is None else utc.isoformat()
    return value.isoformat()


def _hhmm(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "hour"):
        return f"{value.hour:02d}:{value.minute:02d}"
    raw = str(value)
    return raw[:5] if raw else None


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    n_abs = abs(int(n)) % 100
    if 11 <= n_abs <= 14:
        return many
    last = n_abs % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def _format_price_minor(minor: int | None, currency: str) -> str:
    if minor is None:
        return ""
    major = int(minor) / 100.0
    if major == int(major):
        return f"{int(major)} {currency}"
    return f"{major:.2f} {currency}"


def _date_label(local_date: date, today: date) -> str:
    if local_date == today:
        return "Сегодня"
    if local_date == today + timedelta(days=1):
        return "Завтра"
    return local_date.isoformat()


def _completeness_score(row: Mapping[str, Any]) -> int:
    score = 0
    for key in ("phone", "website_url", "short_description", "district"):
        if str(row.get(key) or "").strip():
            score += 1
    if _as_mapping(row.get("opening_hours")):
        score += 1
    amenities = _as_mapping(row.get("amenities"))
    if any(bool(v) for v in amenities.values()):
        score += 1
    if row.get("has_media"):
        score += 1
    return score


def _rank_tuple(item: Mapping[str, Any]) -> tuple:
    tier_rank = {TIER_A: 0, TIER_B: 1, TIER_C: 2}.get(str(item.get("tier") or TIER_C), 2)
    distance = item.get("distance_km")
    distance_key = float(distance) if distance is not None else 10**9
    has_48h = 0 if int(item.get("sessions_48h") or 0) > 0 else 1
    completeness = -int(item.get("completeness") or 0)
    return (tier_rank, distance_key, has_48h, completeness, int(item["id"]))


def _build_live(item: dict[str, Any], *, intent: str, today: date) -> dict[str, Any]:
    currency = item.get("currency_code") or "BYN"
    if intent == INTENT_SKATE:
        if not item.get("next_session_id"):
            return {
                "kind": "unknown",
                "text": "Расписание уточняется",
                "currency_code": currency,
            }
        local_date = item["next_local_date"]
        if isinstance(local_date, datetime):
            local_date = local_date.date()
        hhmm = _hhmm(item.get("next_starts_at_local")) or ""
        session_currency = item.get("next_currency_code") or currency
        price = _format_price_minor(item.get("next_price_adult_minor"), session_currency)
        more = max(0, int(item.get("future_session_count") or 0) - 1)
        parts = [f"{_date_label(local_date, today)} {hhmm}".strip()]
        if price:
            parts.append(price)
        if more:
            word = _plural_ru(more, "сеанс", "сеанса", "сеансов")
            parts.append(f"ещё {more} {word}")
        return {
            "kind": "session",
            "text": " · ".join(parts),
            "local_date": local_date.isoformat() if hasattr(local_date, "isoformat") else str(local_date),
            "starts_at_local": hhmm,
            "price_adult_minor": item.get("next_price_adult_minor"),
            "price_child_minor": item.get("next_price_child_minor"),
            "price_rental_minor": item.get("next_price_rental_minor"),
            "currency_code": session_currency,
            "more_count": more,
        }
    if intent == INTENT_COACH:
        trainers = int(item.get("trainer_count") or 0)
        slots = int(item.get("free_slots") or 0)
        t_word = _plural_ru(trainers, "тренер", "тренера", "тренеров")
        s_word = _plural_ru(slots, "свободный слот", "свободных слота", "свободных слотов")
        return {
            "kind": "trainers",
            "text": f"{trainers} {t_word} · {slots} {s_word} на неделе",
            "trainer_count": trainers,
            "free_slots": slots,
            "currency_code": currency,
        }
    groups = int(item.get("open_groups_count") or 0)
    g_word = _plural_ru(groups, "группа с набором", "группы с набором", "групп с набором")
    return {
        "kind": "groups",
        "text": f"{groups} {g_word}",
        "open_groups_count": groups,
        "currency_code": currency,
    }


def _public_list_item(item: dict[str, Any], *, intent: str, today: date) -> dict[str, Any]:
    hero = item.get("hero")
    thumb = None
    card = None
    if isinstance(hero, Mapping):
        variants = hero.get("variants") or {}
        if isinstance(variants, Mapping):
            thumb = variants.get("thumb") or variants.get("card")
            # TASK-090: карточка «Льда» показывает кадр во всю ширину. thumb — 320px,
            # на 390pt при DPR2 это мыло, поэтому список отдаёт ещё и card (800px).
            card = variants.get("card") or variants.get("hero") or thumb
    live = _build_live(item, intent=intent, today=today)
    return {
        "id": item["id"],
        "slug": item.get("slug"),
        "city_id": item["city_id"],
        "name": item["name"],
        "district": item.get("district"),
        "address": item.get("address"),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "on_map": item.get("latitude") is not None and item.get("longitude") is not None,
        "distance_km": item.get("distance_km"),
        "tier": item["tier"],
        "thumb": thumb,
        "card": card,
        "currency_code": item.get("currency_code"),
        "live": live,
        "live_line": live.get("text"),
    }


_LIST_SQL = f"""
SELECT
    a.id, a.city_id, a.name, a.address, a.latitude, a.longitude,
    p.slug, p.district, p.timezone, p.short_description, p.phone, p.website_url,
    p.social_urls, p.opening_hours, p.season_start_month, p.season_end_month,
    p.amenities, p.status, p.verified_at,
    c.country, c.name AS city_name,
    nxt.id AS next_session_id,
    nxt.kind AS next_kind,
    nxt.starts_at_utc AS next_starts_at_utc,
    nxt.local_date AS next_local_date,
    nxt.starts_at_local AS next_starts_at_local,
    nxt.price_adult_minor AS next_price_adult_minor,
    nxt.price_child_minor AS next_price_child_minor,
    nxt.price_rental_minor AS next_price_rental_minor,
    nxt.currency_code AS next_currency_code,
    COALESCE(sa.future_count, 0) AS future_session_count,
    COALESCE(sa.sessions_48h, 0) AS sessions_48h,
    COALESCE(tc.trainer_count, 0) AS trainer_count,
    COALESCE(fs.free_slots, 0) AS free_slots,
    COALESCE(og.open_groups, 0) AS open_groups_count,
    EXISTS (
        SELECT 1 FROM media m
        WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
    ) AS has_media
FROM arenas a
LEFT JOIN arena_profiles p ON p.arena_id = a.id
JOIN cities c ON c.id = a.city_id
LEFT JOIN LATERAL (
    SELECT s.id, s.kind, s.starts_at_utc, s.local_date, s.starts_at_local,
           s.price_adult_minor, s.price_child_minor, s.price_rental_minor, s.currency_code
    FROM ice_sessions s
    WHERE s.arena_id = a.id AND {_CURRENT_SESSION_SQL}
    ORDER BY s.starts_at_utc
    LIMIT 1
) nxt ON true
LEFT JOIN (
    SELECT s.arena_id,
           COUNT(*)::int AS future_count,
           COUNT(*) FILTER (WHERE s.starts_at_utc <= :now48)::int AS sessions_48h
    FROM ice_sessions s
    WHERE {_CURRENT_SESSION_SQL}
    GROUP BY s.arena_id
) sa ON sa.arena_id = a.id
LEFT JOIN (
    SELECT ta.arena_id, COUNT(DISTINCT t.id)::int AS trainer_count
    FROM trainer_arenas ta
    JOIN trainers t ON t.id = ta.trainer_id
      AND t.status = 'active' AND t.is_catalog_visible = true
    GROUP BY ta.arena_id
) tc ON tc.arena_id = a.id
LEFT JOIN (
    SELECT COALESCE(s.arena_id, t.primary_arena_id) AS arena_id, COUNT(*)::int AS free_slots
    FROM slots s
    JOIN trainers t ON t.id = s.trainer_id
      AND t.status = 'active' AND t.is_catalog_visible = true
    WHERE s.status = 'available'
      AND s.slot_date >= CURRENT_DATE AND s.slot_date <= CURRENT_DATE + 13
      AND ((s.slot_date + s.start_time) AT TIME ZONE :slot_tz) > :now
    GROUP BY COALESCE(s.arena_id, t.primary_arena_id)
) fs ON fs.arena_id = a.id
LEFT JOIN (
    SELECT tg.arena_id, COUNT(*)::int AS open_groups
    FROM training_groups tg
    JOIN trainers t ON t.id = tg.trainer_id
      AND t.status = 'active' AND t.is_catalog_visible = true
    WHERE tg.status = :tg_st AND tg.catalog_visible = true
      AND (
        SELECT COUNT(*)::int FROM training_group_members m
        WHERE m.training_group_id = tg.id AND m.status IN ('active', 'trial')
      ) < tg.max_members
    GROUP BY tg.arena_id
) og ON og.arena_id = a.id
WHERE a.is_active AND a.is_confirmed
  AND c.country = :ice_country
  AND (p.status IS NULL OR p.status = :published)
"""


def _row_to_arena_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    country = row.get("country")
    has_future = int(row.get("future_session_count") or 0) > 0
    data = dict(row)
    data["opening_hours"] = _as_mapping(row.get("opening_hours"))
    data["social_urls"] = _as_mapping(row.get("social_urls"))
    data["amenities"] = _as_mapping(row.get("amenities"))
    data["currency_code"] = currency_for_country(country)
    data["has_media"] = bool(row.get("has_media"))
    data["tier"] = compute_data_tier(
        has_future_public_ice=has_future,
        profile_complete=profile_is_complete(data),
    )
    data["completeness"] = _completeness_score(data)
    data["sessions_48h"] = int(row.get("sessions_48h") or 0)
    data["future_session_count"] = int(row.get("future_session_count") or 0)
    data["trainer_count"] = int(row.get("trainer_count") or 0)
    data["free_slots"] = int(row.get("free_slots") or 0)
    data["open_groups_count"] = int(row.get("open_groups_count") or 0)
    return data


async def _load_ice_arena_rows(
    session: AsyncSession,
    *,
    city_id: int | None,
    bbox: tuple[float, float, float, float] | None,
    intent: str,
    now: datetime,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "now": now,
        "now48": now + timedelta(hours=48),
        "st": STATUS_ACTIVE,
        "slot_tz": NOTIFICATION_TZ,
        "tg_st": TG_RECRUITING,
        "published": ARENA_PROFILE_STATUS_PUBLISHED,
        "ice_country": ICE_DISCOVERY_COUNTRY,
    }
    where = []
    if city_id is not None:
        where.append("a.city_id = :city_id")
        params["city_id"] = int(city_id)
    if bbox is not None:
        min_lat, min_lon, max_lat, max_lon = bbox
        where.append(
            "a.latitude IS NOT NULL AND a.longitude IS NOT NULL "
            "AND a.latitude BETWEEN :min_lat AND :max_lat "
            "AND a.longitude BETWEEN :min_lon AND :max_lon"
        )
        params.update(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)
    if intent == INTENT_SKATE:
        where.append("COALESCE(sa.future_count, 0) > 0")
    sql = _LIST_SQL
    if where:
        sql = sql + " AND " + " AND ".join(where)
    result = await session.execute(text(sql), params)
    return [_row_to_arena_dict(row) for row in result.mappings()]


async def list_ice_discovery_cities(session: AsyncSession) -> list[dict[str, Any]]:
    """Active cities that have public skate sessions and/or catalog trainers.

    Empty cities stay out of the Ice picker so a switch never lands on a fake map.
    """
    now = datetime.now(timezone.utc)
    rows = (
        await session.execute(
            text(
                f"""
                SELECT c.id, c.name, c.sort_order, c.country,
                       (
                           SELECT COUNT(*)::int
                           FROM arenas a
                           LEFT JOIN arena_profiles p ON p.arena_id = a.id
                           WHERE a.city_id = c.id
                             AND a.is_active AND a.is_confirmed
                             AND (p.status IS NULL OR p.status = :published)
                             AND EXISTS (
                                 SELECT 1 FROM ice_sessions s
                                 WHERE s.arena_id = a.id
                                   AND {_CURRENT_SESSION_SQL}
                             )
                       ) AS skate_count,
                       (
                           SELECT COUNT(*)::int
                           FROM trainers t
                           WHERE t.status = 'active'
                             AND t.is_catalog_visible = true
                             AND EXISTS (
                                 SELECT 1 FROM trainer_cities tc
                                 WHERE tc.trainer_id = t.id AND tc.city_id = c.id
                             )
                       ) AS trainer_count,
                       (
                           SELECT COUNT(*)::int
                           FROM arenas a
                           LEFT JOIN arena_profiles p ON p.arena_id = a.id
                           WHERE a.city_id = c.id
                             AND a.is_active AND a.is_confirmed
                             AND a.latitude IS NOT NULL AND a.longitude IS NOT NULL
                             AND (p.status IS NULL OR p.status = :published)
                       ) AS map_rink_count,
                       (
                           SELECT AVG(a.latitude)
                           FROM arenas a
                           LEFT JOIN arena_profiles p ON p.arena_id = a.id
                           WHERE a.city_id = c.id
                             AND a.is_active AND a.is_confirmed
                             AND a.latitude IS NOT NULL AND a.longitude IS NOT NULL
                             AND (p.status IS NULL OR p.status = :published)
                       ) AS latitude,
                       (
                           SELECT AVG(a.longitude)
                           FROM arenas a
                           LEFT JOIN arena_profiles p ON p.arena_id = a.id
                           WHERE a.city_id = c.id
                             AND a.is_active AND a.is_confirmed
                             AND a.latitude IS NOT NULL AND a.longitude IS NOT NULL
                             AND (p.status IS NULL OR p.status = :published)
                       ) AS longitude
                FROM cities c
                WHERE c.is_active AND c.country = :ice_country
                ORDER BY c.sort_order, c.id
                """
            ),
            {
                "published": ARENA_PROFILE_STATUS_PUBLISHED,
                "st": STATUS_ACTIVE,
                "now": now,
                "ice_country": ICE_DISCOVERY_COUNTRY,
            },
        )
    ).mappings()
    items = []
    for row in rows:
        skate_count = int(row["skate_count"] or 0)
        trainer_count = int(row["trainer_count"] or 0)
        map_rink_count = int(row["map_rink_count"] or 0)
        if skate_count <= 0 and trainer_count <= 0 and map_rink_count <= 0:
            continue
        lat = row["latitude"]
        lon = row["longitude"]
        items.append(
            {
                "id": int(row["id"]),
                "name": row["name"],
                "sort_order": row["sort_order"],
                "country": row["country"],
                "skate_count": skate_count,
                "trainer_count": trainer_count,
                "map_rink_count": map_rink_count,
                "latitude": float(lat) if lat is not None else None,
                "longitude": float(lon) if lon is not None else None,
            }
        )
    return items


async def list_public_ice_arenas(
    session: AsyncSession,
    *,
    city_id: int | None = None,
    bbox: str | None = None,
    near: str | None = None,
    intent: str | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    intent_value = parse_intent(intent)
    bbox_box = parse_bbox(bbox)
    near_pt = parse_near(near)
    if city_id is None and bbox_box is None and near_pt is None:
        raise IcePublicQueryError("city_id, bbox or near is required")
    cap = max(1, min(int(limit or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT))
    offset = 0
    if cursor:
        try:
            offset = max(0, int(cursor))
        except ValueError as exc:
            raise IcePublicQueryError("cursor must be an integer offset") from exc
    now = datetime.now(timezone.utc)
    rows = await _load_ice_arena_rows(
        session, city_id=city_id, bbox=bbox_box, intent=intent_value, now=now
    )
    if near_pt is not None:
        nlat, nlon = near_pt
        for row in rows:
            lat, lon = row.get("latitude"), row.get("longitude")
            if lat is None or lon is None:
                row["distance_km"] = None
            else:
                row["distance_km"] = haversine_km(nlat, nlon, float(lat), float(lon))
    else:
        for row in rows:
            row["distance_km"] = None
    rows.sort(key=_rank_tuple)
    page = rows[offset : offset + cap]
    await attach_arena_media_payloads(session, page)
    today = _today_minsk()
    items = [_public_list_item(row, intent=intent_value, today=today) for row in page]
    next_cursor = str(offset + cap) if offset + cap < len(rows) else None
    return {
        "items": items,
        "total": len(rows),
        "intent": intent_value,
        "next_cursor": next_cursor,
    }


async def get_hub_ice_teaser(
    session: AsyncSession, *, city_id: int | None
) -> dict[str, Any] | None:
    """Soonest future public_skate|open_ice slot in the session city, or None.

    Same MK filter as Ice tab intent=skate (tier A). No geolocation — distance
    stays unset. Hub bootstrap uses this so home load stays one round-trip.

    TASK-091. Два изменения против TASK-055:
      * без города клиента больше не отдаём None. Первый экран Главной обязан
        показать товар и новичку (AC-005), а город у него появляется только
        после первого выбора. Без city_id берём ближайший сеанс по стране —
        ровно то же, что делает вкладка «Лёд» своим pickFallbackCity;
      * отдаём кадр арены и название города: карточка на Главной — тот же
        объект, что карточка на «Льду», а не строка-тизер.
    """
    now = datetime.now(timezone.utc)
    params: dict[str, Any] = {
        "now": now,
        "st": STATUS_ACTIVE,
        "published": ARENA_PROFILE_STATUS_PUBLISHED,
        "ice_country": ICE_DISCOVERY_COUNTRY,
    }
    city_filter = ""
    if city_id is not None:
        params["city_id"] = int(city_id)
        city_filter = "  AND a.city_id = :city_id\n"
    sql = f"""
SELECT
    a.id AS arena_id,
    p.slug AS arena_slug,
    a.name AS arena_name,
    p.district AS arena_district,
    a.city_id AS city_id,
    c.name AS city_name,
    nxt.kind,
    nxt.starts_at_utc,
    nxt.local_date,
    nxt.starts_at_local,
    nxt.price_adult_minor,
    nxt.currency_code
FROM arenas a
LEFT JOIN arena_profiles p ON p.arena_id = a.id
JOIN cities c ON c.id = a.city_id
JOIN LATERAL (
    SELECT s.kind, s.starts_at_utc, s.local_date, s.starts_at_local,
           s.price_adult_minor, s.currency_code
    FROM ice_sessions s
    WHERE s.arena_id = a.id AND {_CURRENT_SESSION_SQL}
    ORDER BY s.starts_at_utc
    LIMIT 1
) nxt ON true
WHERE a.is_active AND a.is_confirmed
  AND c.country = :ice_country
{city_filter}  AND (p.status IS NULL OR p.status = :published)
ORDER BY nxt.starts_at_utc, a.id
LIMIT 1
"""
    row = (await session.execute(text(sql), params)).mappings().first()
    if not row:
        return None
    local_date = row["local_date"]
    starts_utc = row["starts_at_utc"]
    media_holder: dict[str, Any] = {"id": int(row["arena_id"])}
    await attach_arena_media_payloads(session, [media_holder])
    hero = media_holder.get("hero")
    thumb = None
    card = None
    if isinstance(hero, Mapping):
        variants = hero.get("variants") or {}
        if isinstance(variants, Mapping):
            thumb = variants.get("thumb") or variants.get("card")
            card = variants.get("card") or variants.get("hero") or thumb
    return {
        "arena_id": int(row["arena_id"]),
        "arena_slug": row["arena_slug"],
        "arena_name": row["arena_name"],
        "arena_district": row["arena_district"],
        "city_id": int(row["city_id"]) if row["city_id"] is not None else None,
        "city_name": row["city_name"],
        "kind": row["kind"],
        "starts_at_utc": starts_utc.isoformat() if hasattr(starts_utc, "isoformat") else str(starts_utc),
        "local_date": local_date.isoformat() if hasattr(local_date, "isoformat") else str(local_date),
        "starts_at_local": _hhmm(row["starts_at_local"]),
        "price_adult_minor": row["price_adult_minor"],
        "currency_code": row["currency_code"],
        "thumb": thumb,
        "card": card,
        "distance_km": None,
    }


async def _load_arena_by_ref(session: AsyncSession, arena_ref: str) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    params: dict[str, Any] = {
        "now": now,
        "now48": now + timedelta(hours=48),
        "st": STATUS_ACTIVE,
        "slot_tz": NOTIFICATION_TZ,
        "tg_st": TG_RECRUITING,
        "published": ARENA_PROFILE_STATUS_PUBLISHED,
        "ice_country": ICE_DISCOVERY_COUNTRY,
    }
    sql = _LIST_SQL
    if arena_ref.isdigit():
        sql += " AND a.id = :arena_id"
        params["arena_id"] = int(arena_ref)
    else:
        sql += " AND p.slug = :slug"
        params["slug"] = arena_ref.strip()
    sql += " ORDER BY a.id LIMIT 2"
    result = await session.execute(text(sql), params)
    rows = [_row_to_arena_dict(row) for row in result.mappings()]
    return rows[0] if rows else None


def _freshness_payload(
    row: Mapping[str, Any], *, observed_at: datetime | None, valid_until: datetime | None
) -> dict[str, Any]:
    website = str(row.get("website_url") or "").strip() or None
    source_label = "сайт катка" if website else None
    return {
        "schedule_observed_at": _iso(observed_at),
        "schedule_valid_until": _iso(valid_until),
        "source_kind": "rink_website" if website else None,
        "source_label": source_label,
        "source_url": website,
        "verified_at": _iso(row.get("verified_at")),
    }


async def get_public_arena_card(session: AsyncSession, arena_ref: str) -> dict[str, Any] | None:
    row = await _load_arena_by_ref(session, arena_ref)
    if row is None:
        return None
    await attach_arena_media_payloads(session, [row])
    observed = await session.execute(
        text(
            f"""
            SELECT MAX(s.observed_at), MIN(s.valid_until)
            FROM ice_sessions s
            WHERE s.arena_id = :aid AND {_CURRENT_SESSION_SQL}
            """
        ),
        {"aid": row["id"], "now": datetime.now(timezone.utc), "st": STATUS_ACTIVE},
    )
    obs_row = observed.fetchone()
    season_start = row.get("season_start_month")
    season_end = row.get("season_end_month")
    return {
        "id": row["id"],
        "slug": row.get("slug"),
        "city_id": row["city_id"],
        "city_name": row.get("city_name"),
        "name": row["name"],
        "district": row.get("district"),
        "address": row.get("address"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "timezone": row.get("timezone") or "Europe/Minsk",
        "short_description": row.get("short_description"),
        "phone": row.get("phone"),
        "website_url": row.get("website_url"),
        "social_urls": _as_mapping(row.get("social_urls")),
        "opening_hours": _as_mapping(row.get("opening_hours")),
        "season_start_month": season_start,
        "season_end_month": season_end,
        "in_season": is_in_season(season_start, season_end, _today_minsk().month),
        "amenities": _as_mapping(row.get("amenities")),
        "contacts": {
            "phone": row.get("phone"),
            "website_url": row.get("website_url"),
            "social_urls": _as_mapping(row.get("social_urls")),
        },
        "hero": row.get("hero"),
        "gallery": row.get("gallery") or [],
        "tier": row["tier"],
        "currency_code": row.get("currency_code"),
        "freshness": _freshness_payload(
            row,
            observed_at=obs_row[0] if obs_row else None,
            valid_until=obs_row[1] if obs_row else None,
        ),
    }


async def list_public_arena_sessions(
    session: AsyncSession,
    arena_ref: str,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any] | None:
    row = await _load_arena_by_ref(session, arena_ref)
    if row is None:
        return None
    start = date_from or _today_minsk()
    end = date_to or (start + timedelta(days=14))
    if end < start:
        start, end = end, start
    now = datetime.now(timezone.utc)
    result = await session.execute(
        text(
            f"""
            SELECT id, arena_id, kind, starts_at_utc, ends_at_utc, local_date, starts_at_local, ends_at_local,
                   price_adult_minor, price_child_minor, price_rental_minor, price_minor, currency_code,
                   price_note, session_label, age_note, capacity_note, external_url, status, recurrence_key,
                   source_id, observed_at, valid_until, confidence
            FROM ice_sessions s
            WHERE s.arena_id = :aid
              AND {_CURRENT_SESSION_SQL}
              AND s.local_date >= :dfrom AND s.local_date <= :dto
            ORDER BY s.local_date, s.starts_at_local, s.id
            """
        ),
        {
            "aid": row["id"],
            "st": STATUS_ACTIVE,
            "now": now,
            "dfrom": start,
            "dto": end,
        },
    )
    keys = [
        "id",
        "arena_id",
        "kind",
        "starts_at_utc",
        "ends_at_utc",
        "local_date",
        "starts_at_local",
        "ends_at_local",
        "price_adult_minor",
        "price_child_minor",
        "price_rental_minor",
        "price_minor",
        "currency_code",
        "price_note",
        "session_label",
        "age_note",
        "capacity_note",
        "external_url",
        "status",
        "recurrence_key",
        "source_id",
        "observed_at",
        "valid_until",
        "confidence",
    ]
    by_date: dict[str, list[dict[str, Any]]] = {}
    for raw in result.fetchall():
        mapped = dict(zip(keys, raw, strict=True))
        ser = serialize_ice_session(mapped)
        ser.pop("parser_key", None)
        day = ser["local_date"]
        by_date.setdefault(day, []).append(ser)
    days = [{"local_date": d, "sessions": by_date[d]} for d in sorted(by_date)]
    return {
        "arena_id": row["id"],
        "timezone": row.get("timezone") or "Europe/Minsk",
        "from": start.isoformat(),
        "to": end.isoformat(),
        "days": days,
        "kinds": list(CLIENT_ICE_SESSION_KINDS),
    }


async def list_public_arena_trainers(
    session: AsyncSession, arena_ref: str
) -> dict[str, Any] | None:
    row = await _load_arena_by_ref(session, arena_ref)
    if row is None:
        return None
    items, total = await list_active_trainers_for_client(
        session, limit=50, offset=0, arena_id=int(row["id"])
    )
    trainer_ids = [int(t["id"]) for t in items]
    open_grp = await batch_open_groups_count_for_trainers(session, trainer_ids)
    out = []
    for trainer in items:
        body = sanitize_trainer_for_public_catalog(trainer)
        availability = await get_trainer_booking_availability(session, int(body["id"]))
        body["can_book"] = availability["can_book"]
        body["open_groups_count"] = int(open_grp.get(body["id"], 0))
        out.append(body)
    groups, _groups_total = await list_open_training_groups_catalog(
        session, arena_id=int(row["id"]), limit=50, offset=0
    )
    return {
        "arena_id": row["id"],
        "items": out,
        "total": total,
        "groups": groups,
    }


async def _pg_trgm_enabled(session: AsyncSession) -> bool:
    result = await session.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")
    )
    return bool(result.scalar())


async def search_public_ice(
    session: AsyncSession, q: str, *, limit: int = SEARCH_LIMIT
) -> dict[str, Any]:
    query = (q or "").strip()
    if len(query) < 2:
        raise IcePublicQueryError("q must be at least 2 characters")
    cap = max(1, min(int(limit or SEARCH_LIMIT), 20))
    like = f"%{query}%"
    use_trgm = await _pg_trgm_enabled(session)
    arena_sql = """
        SELECT a.id, p.slug, a.name, a.city_id, p.district, c.name AS city_name
        FROM arenas a
        LEFT JOIN arena_profiles p ON p.arena_id = a.id
        JOIN cities c ON c.id = a.city_id
        WHERE a.is_active AND a.is_confirmed
          AND c.country = :ice_country
          AND (p.status IS NULL OR p.status = :published)
          AND (
            to_tsvector('simple', coalesce(a.name, '') || ' ' || coalesce(p.district, ''))
              @@ plainto_tsquery('simple', :q)
            OR a.name ILIKE :like
            OR coalesce(p.district, '') ILIKE :like
          )
        ORDER BY a.name, a.id
        LIMIT :lim
    """
    if use_trgm:
        arena_sql = """
            SELECT a.id, p.slug, a.name, a.city_id, p.district, c.name AS city_name
            FROM arenas a
            LEFT JOIN arena_profiles p ON p.arena_id = a.id
            JOIN cities c ON c.id = a.city_id
            WHERE a.is_active AND a.is_confirmed
              AND c.country = :ice_country
              AND (p.status IS NULL OR p.status = :published)
              AND (
                to_tsvector('simple', coalesce(a.name, '') || ' ' || coalesce(p.district, ''))
                  @@ plainto_tsquery('simple', :q)
                OR a.name ILIKE :like
                OR coalesce(p.district, '') ILIKE :like
                OR similarity(a.name, :q) > 0.2
              )
            ORDER BY GREATEST(similarity(a.name, :q), 0) DESC, a.name, a.id
            LIMIT :lim
        """
    arenas = await session.execute(
        text(arena_sql),
        {
            "q": query,
            "like": like,
            "lim": cap,
            "published": ARENA_PROFILE_STATUS_PUBLISHED,
            "ice_country": ICE_DISCOVERY_COUNTRY,
        },
    )
    trainers = await session.execute(
        text(
            """
            SELECT t.id, p.first_name, p.last_name, p.city_id
            FROM trainers t
            JOIN trainer_profiles p ON p.trainer_id = t.id
            WHERE t.status = 'active' AND t.is_catalog_visible = true
              AND (
                to_tsvector('simple', coalesce(p.first_name, '') || ' ' || coalesce(p.last_name, ''))
                  @@ plainto_tsquery('simple', :q)
                OR coalesce(p.first_name, '') ILIKE :like
                OR coalesce(p.last_name, '') ILIKE :like
              )
            ORDER BY p.last_name, p.first_name, t.id
            LIMIT :lim
            """
        ),
        {"q": query, "like": like, "lim": cap},
    )
    cities = await session.execute(
        text(
            """
            SELECT id, name
            FROM cities
            WHERE is_active AND country = :ice_country
              AND (
                to_tsvector('simple', coalesce(name, '')) @@ plainto_tsquery('simple', :q)
                OR name ILIKE :like
              )
            ORDER BY name, id
            LIMIT :lim
            """
        ),
        {"q": query, "like": like, "lim": cap, "ice_country": ICE_DISCOVERY_COUNTRY},
    )
    arena_items = [
        {
            "id": int(r[0]),
            "slug": r[1],
            "name": r[2],
            "city_id": int(r[3]),
            "district": r[4],
            "city_name": r[5],
        }
        for r in arenas.fetchall()
    ]
    trainer_items = [
        {
            "id": int(r[0]),
            "first_name": r[1],
            "last_name": r[2],
            "name": " ".join(x for x in (r[1], r[2]) if x).strip(),
            "city_id": int(r[3]) if r[3] is not None else None,
        }
        for r in trainers.fetchall()
    ]
    city_items = [{"id": int(r[0]), "name": r[1]} for r in cities.fetchall()]
    return {
        "q": query,
        "groups": [
            {"type": "arena", "items": arena_items},
            {"type": "trainer", "items": trainer_items},
            {"type": "city", "items": city_items},
        ],
    }


_ICE_CITIES_SQL = """
SELECT
  c.id,
  c.name,
  c.sort_order,
  c.country,
  COUNT(DISTINCT rink.id)::int AS map_rink_count,
  COUNT(DISTINCT coach.trainer_id)::int AS trainer_count,
  AVG(rink.latitude) AS latitude,
  AVG(rink.longitude) AS longitude
FROM cities c
LEFT JOIN (
  SELECT a.city_id, a.id, a.latitude, a.longitude
  FROM arenas a
  LEFT JOIN arena_profiles p ON p.arena_id = a.id
  WHERE a.is_active AND a.is_confirmed
    AND a.latitude IS NOT NULL AND a.longitude IS NOT NULL
    AND (p.status IS NULL OR p.status = :published)
) rink ON rink.city_id = c.id
LEFT JOIN (
  SELECT tc.city_id, tc.trainer_id
  FROM trainer_cities tc
  JOIN trainers t ON t.id = tc.trainer_id
    AND t.status = 'active' AND COALESCE(t.is_catalog_visible, true) = true
  UNION
  SELECT p.city_id, p.trainer_id
  FROM trainer_profiles p
  JOIN trainers t ON t.id = p.trainer_id
    AND t.status = 'active' AND COALESCE(t.is_catalog_visible, true) = true
  WHERE p.city_id IS NOT NULL
) coach ON coach.city_id = c.id
WHERE c.is_active
GROUP BY c.id, c.name, c.sort_order, c.country
HAVING COUNT(DISTINCT rink.id) > 0 OR COUNT(DISTINCT coach.trainer_id) > 0
ORDER BY c.sort_order, c.id
"""


async def list_ice_cities(session: AsyncSession) -> dict[str, Any]:
    """Cities that belong on the Ice tab picker: a map rink and/or a catalog trainer."""
    result = await session.execute(
        text(_ICE_CITIES_SQL), {"published": ARENA_PROFILE_STATUS_PUBLISHED}
    )
    items: list[dict[str, Any]] = []
    for row in result.mappings():
        lat = row["latitude"]
        lon = row["longitude"]
        items.append(
            {
                "id": int(row["id"]),
                "name": row["name"],
                "sort_order": int(row["sort_order"] or 0),
                "country": row["country"],
                "map_rink_count": int(row["map_rink_count"] or 0),
                "trainer_count": int(row["trainer_count"] or 0),
                "latitude": float(lat) if lat is not None else None,
                "longitude": float(lon) if lon is not None else None,
            }
        )
    return {"items": items}


async def record_ice_city_interest(
    session: AsyncSession,
    *,
    city_id: int,
    intent: str | None = None,
    source: str | None = None,
) -> dict[str, Any] | None:
    """Persist a client tap that they want skating in a city without map rinks."""
    found = await session.execute(
        text("SELECT 1 FROM cities WHERE id = :id AND is_active"),
        {"id": int(city_id)},
    )
    if found.first() is None:
        return None
    intent_value = parse_intent(intent) if intent else INTENT_SKATE
    src = str(source or "coming_soon_cta").strip()[:32] or "coming_soon_cta"
    inserted = await session.execute(
        text(
            """
            INSERT INTO ice_city_interest (city_id, intent, source)
            VALUES (:city_id, :intent, :source)
            RETURNING id
            """
        ),
        {"city_id": int(city_id), "intent": intent_value, "source": src},
    )
    await session.commit()
    return {"ok": True, "id": int(inserted.scalar_one())}

