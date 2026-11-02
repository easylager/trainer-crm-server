"""Публичное чтение зимних точек (TASK-343): список по городу и карточка.

Сорт: закреп (Немига) -> подтверждённо залитые -> расстояние (только у точных точек, если
передан lat/lon) -> район -> имя. Скрытые точки и кандидаты не отдаются. «Открыто сейчас»
по часам прошлой зимы не считаем: отдаём часы как справку с подписью сезона.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_consumer_events import hmac_actor
from src.application.winter_links import (
    bell_param, bot_link, gone_param, map_allowed, photo_param, route_url, static_map_url, NEAR_PARAM,
)
from src.shared import winter_status as ws
from src.shared.config import Settings
from src.shared.winter_hours import hours_summary_ru

TOKEN_TTL = timedelta(minutes=30)
SHARED_PHONE_MIN = 3
_STATE_RANK = {"flooded": 0, "waiting": 1, "stale": 2, "closed": 3}

_SELECT = """
SELECT a.id, a.name, a.address, a.latitude, a.longitude, a.city_id, c.name AS city_name,
       p.slug, p.district, p.catalog_pin,
       sr.kind, sr.operator, sr.is_paid, sr.price_note, sr.often_hockey, sr.geocode_precision, sr.same_complex_id,
       s.state, s.state_at, s.state_source, s.quality, s.dispute, s.doubtful, s.hours_text, s.opening_hours,
       s.hours_known, s.hours_season, s.season_from, s.season_to, s.phone, s.source_url, s.confidence, s.season
FROM seasonal_rinks sr
JOIN arenas a ON a.id = sr.arena_id AND a.is_active
JOIN cities c ON c.id = a.city_id
JOIN seasonal_rink_seasons s ON s.arena_id = a.id AND s.season = :season
LEFT JOIN arena_profiles p ON p.arena_id = a.id
WHERE s.state <> 'hidden'
"""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --- токен страницы для анонимной отметки (W1) -------------------------------------
def make_page_token(arena_id: int, now: datetime) -> str | None:
    exp = int((now + TOKEN_TTL).timestamp())
    sig = hmac_actor("wtoken", f"{int(arena_id)}|{exp}")
    return f"{exp}.{sig[:32]}" if sig else None  # без секрета отметки с сайта выключены


def check_page_token(arena_id: int, token: str | None, now: datetime) -> bool:
    try:
        exp_s, sig = (token or "").split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < int(now.timestamp()) or exp > int((now + TOKEN_TTL).timestamp()) + 5:
        return False
    good = hmac_actor("wtoken", f"{int(arena_id)}|{exp}")
    return bool(good) and hmac.compare_digest(good[:32], sig)


def site_actor(ip: str | None, user_agent: str | None) -> str | None:
    h = hmac_actor("wsite", f"{(ip or '').strip()}|{(user_agent or '').strip()[:200]}")
    return f"site:{h[:32]}" if h else None


# --- сборка -----------------------------------------------------------------------
async def _live_marks(session: AsyncSession, ids: list[int], now: datetime) -> dict[int, list[ws.MarkIn]]:
    if not ids:
        return {}
    rows = (
        await session.execute(
            text(
                """SELECT arena_id, kind, value, weight, actor, created_at, source FROM seasonal_rink_marks
                   WHERE arena_id = ANY(:ids) AND kind IN ('crowd', 'hockey') AND created_at >= :since"""
            ),
            {"ids": ids, "since": now - ws.LIVE_WINDOW},
        )
    ).all()
    out: dict[int, list[ws.MarkIn]] = defaultdict(list)
    for r in rows:
        out[int(r.arena_id)].append(ws.MarkIn(r.kind, r.value, float(r.weight), r.actor, r.created_at, r.source))
    return out


async def _photos(session: AsyncSession, ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not ids:
        return {}
    rows = (
        await session.execute(
            text(
                """SELECT id, arena_id, variants, created_at FROM seasonal_rink_photos
                   WHERE arena_id = ANY(:ids) AND published AND status = 'accepted' AND report_count < 2
                   ORDER BY id DESC"""
            ),
            {"ids": ids},
        )
    ).all()
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if len(out[int(r.arena_id)]) < 6:
            out[int(r.arena_id)].append({"id": int(r.id), "variants": r.variants, "created_at": r.created_at.isoformat()})
    return out


def _shape(r: Any, *, live: dict, photos: list, shared_phone: bool, origin: tuple[float, float] | None,
           settings: Settings, detail: bool) -> dict[str, Any]:
    precise = map_allowed(r.geocode_precision) and r.latitude is not None
    dist = None
    if origin and precise:
        dist = round(haversine_km(origin[0], origin[1], float(r.latitude), float(r.longitude)), 1)
    hours_label = f"зимой {r.hours_season}" if r.hours_season else None
    item: dict[str, Any] = {
        "id": int(r.id), "slug": r.slug, "name": r.name, "kind": r.kind, "district": r.district,
        "city_id": int(r.city_id), "city": r.city_name, "address": r.address,
        "state": r.state, "state_at": r.state_at.isoformat() if r.state_at else None,
        "checked_by": "admin" if r.state_source == "admin" else ("people" if r.state_source == "engine" else None),
        "quality": r.quality, "dispute": bool(r.dispute), "doubtful": bool(r.doubtful),
        "crowd": live.get("crowd"), "hockey": live.get("hockey"),
        "crowd_at": live.get("crowd_at"), "hockey_at": live.get("hockey_at"),
        "distance_km": dist, "pin": r.catalog_pin,
        "is_paid": r.is_paid, "price_note": r.price_note,
        "often_hockey_note": "Часто занята под хоккей и занятия школы" if r.often_hockey else None,
        "geocode_precision": r.geocode_precision, "map_allowed": precise,
        "locating": not precise,  # плашка «Точку уточняем»
        "lat": float(r.latitude) if precise else None, "lon": float(r.longitude) if precise else None,
        "hours": {
            "known": bool(r.hours_known), "weekly": (r.opening_hours or {}).get("weekly") if r.hours_known else None,
            "summary": hours_summary_ru(r.opening_hours) if r.hours_known else None,
            "text": r.hours_text, "label": hours_label,
            "season_from": r.season_from, "season_to": r.season_to,
            "fallback": None if r.hours_known else "Часы уточняйте по телефону",
        },
        "phone": r.phone, "phone_shared": bool(shared_phone and r.phone),
        "source_url": r.source_url, "season": int(r.season), "season_label": ws.season_label(int(r.season)),
        "photos": photos,
        "route_url": route_url(r.latitude, r.longitude, r.geocode_precision, r.address, r.city_name),
        "same_complex_id": r.same_complex_id,
        "own_page": has_winter_page(r.slug),  # у существующих арен (Немига) страница обычная, не зимняя
    }
    if settings.winter_static_map_thumbs or detail:
        item["static_map_url"] = static_map_url(
            r.latitude, r.longitude, r.geocode_precision, api_key=settings.yandex_static_api_key,
            width=650 if detail else 160, height=450 if detail else 160, zoom=16 if detail else 15,
        )
    return item


async def _shared_phones(session: AsyncSession, season: int) -> set[str]:
    rows = (
        await session.execute(
            text(
                """SELECT phone FROM seasonal_rink_seasons WHERE season=:s AND phone IS NOT NULL AND state <> 'hidden'
                   GROUP BY phone HAVING count(*) >= :n"""
            ),
            {"s": season, "n": SHARED_PHONE_MIN},
        )
    ).scalars().all()
    return set(rows)


async def list_points(
    session: AsyncSession, city_id: int, *, now: datetime, lat: float | None = None, lon: float | None = None,
    kind: str | None = None, only_flooded: bool = False,
) -> dict[str, Any]:
    settings = Settings()
    season = ws.current_season(now)
    rows = (await session.execute(text(_SELECT + " AND a.city_id = :city"), {"season": season, "city": city_id})).all()
    rows = [r for r in rows if (kind is None or r.kind == kind)]
    ids = [int(r.id) for r in rows]
    live, photos, shared = await _live_marks(session, ids, now), await _photos(session, ids), await _shared_phones(session, season)
    origin = (lat, lon) if lat is not None and lon is not None else None
    items = [
        _shape(r, live=ws.live_summary(live.get(int(r.id), []), now), photos=photos.get(int(r.id), []),
               shared_phone=r.phone in shared, origin=origin, settings=settings, detail=False)
        for r in rows
    ]
    if only_flooded:
        items = [i for i in items if i["state"] == "flooded"]

    def key(i: dict[str, Any]):
        return (
            i["pin"] is None, i["pin"] or 0,
            _STATE_RANK.get(i["state"], 9),
            i["distance_km"] is None, i["distance_km"] if i["distance_km"] is not None else 0.0,
            (i["district"] or "~"), i["name"],
        )

    items.sort(key=key)
    flooded = sum(1 for i in items if i["state"] == "flooded")
    return {"items": items, "total": len(items), "flooded": flooded, "season_label": ws.season_label(season),
            "bell_near_link": bot_link(settings.client_bot_username, NEAR_PARAM)}


async def get_point(session: AsyncSession, ident: str | int, *, now: datetime, lat: float | None = None,
                    lon: float | None = None) -> dict[str, Any] | None:
    settings = Settings()
    season = ws.current_season(now)
    if str(ident).isdigit():
        cond, params = "a.id = :ident", {"ident": int(ident)}
    else:
        cond, params = "p.slug = :ident", {"ident": str(ident)}
    r = (await session.execute(text(_SELECT + f" AND {cond}"), {"season": season, **params})).first()
    if r is None:
        return None
    live = await _live_marks(session, [int(r.id)], now)
    photos = await _photos(session, [int(r.id)])
    shared = await _shared_phones(session, season)
    origin = (lat, lon) if lat is not None and lon is not None else None
    item = _shape(r, live=ws.live_summary(live.get(int(r.id), []), now), photos=photos.get(int(r.id), []),
                  shared_phone=r.phone in shared, origin=origin, settings=settings, detail=True)
    item["mark_token"] = make_page_token(int(r.id), now)
    item["links"] = {
        "bell": bot_link(settings.client_bot_username, bell_param(int(r.id))),
        "near": bot_link(settings.client_bot_username, NEAR_PARAM),
        "photo": bot_link(settings.client_bot_username, photo_param(int(r.id))),
        "gone": bot_link(settings.client_bot_username, gone_param(int(r.id))),
    }
    item["noindex"] = bool(r.doubtful)
    return item


# --- сайт: итоги города, «чем была точка», sitemap (волна 2) ---------------------------
INDEXABLE_PRECISIONS = frozenset({"house", "osm_exact", "manual"})
_WINTER_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-(?:korobka|katok)-[0-9]+$")


def has_winter_page(slug: str | None) -> bool:
    """Свой зимний адрес у точек из seed (``<город>-<korobka|katok>-<id>``).

    Немига и другие существующие арены каталога только закреплены в «Зимой»: их страница остаётся обычной.
    """
    return bool(slug and _WINTER_SLUG_RE.match(slug))


def is_indexable(item: dict[str, Any]) -> bool:
    """O3: в индекс — только точная точка, не «под вопросом», минимум три факта из четырёх.

    Факты: адрес; часы или телефон; тип; цена известна (бесплатно/платно). Остальные страницы
    открываются людям, но с ``noindex,follow`` и вне sitemap: сотни тонких страниц портят сайт целиком.
    """
    if item.get("doubtful") or not item.get("map_allowed"):
        return False
    hours = item.get("hours") or {}
    facts = [
        bool((item.get("address") or "").strip()),
        bool(hours.get("known") or item.get("phone")),
        bool(item.get("kind")),
        item.get("is_paid") is not None,
    ]
    return sum(facts) >= 3


async def city_summary(session: AsyncSession, city_id: int, *, now: datetime) -> dict[str, int]:
    """Сколько зимних точек в городе и сколько залито — для плитки «Зимой» на странице города."""
    row = (
        await session.execute(
            text(
                """SELECT count(*) AS total, count(*) FILTER (WHERE s.state = 'flooded') AS flooded
                   FROM seasonal_rinks sr
                   JOIN arenas a ON a.id = sr.arena_id AND a.is_active
                   JOIN seasonal_rink_seasons s ON s.arena_id = a.id AND s.season = :season
                   WHERE a.city_id = :city AND s.state <> 'hidden'"""
            ),
            {"season": ws.current_season(now), "city": city_id},
        )
    ).one()
    return {"total": int(row.total), "flooded": int(row.flooded)}


async def lookup_any(session: AsyncSession, ident: str | int) -> dict[str, Any] | None:
    """Точка в любом состоянии, в том числе скрытая: чтобы вместо голого 404 показать понятную страницу.

    ``None`` — такой точки в зимнем каталоге не было. ``hidden`` — была, но сейчас не показывается.
    """
    cond, params = ("a.id = :ident", {"ident": int(ident)}) if str(ident).isdigit() else ("p.slug = :ident", {"ident": str(ident)})
    r = (
        await session.execute(
            text(
                f"""SELECT a.id, a.name, a.is_active, a.city_id, c.name AS city_name, p.slug, s.state
                    FROM seasonal_rinks sr
                    JOIN arenas a ON a.id = sr.arena_id
                    JOIN cities c ON c.id = a.city_id
                    LEFT JOIN arena_profiles p ON p.arena_id = a.id
                    LEFT JOIN seasonal_rink_seasons s ON s.arena_id = a.id AND s.season = (
                        SELECT max(season) FROM seasonal_rink_seasons WHERE arena_id = a.id)
                    WHERE {cond} LIMIT 1"""
            ),
            params,
        )
    ).first()
    if r is None:
        return None
    return {
        "id": int(r.id), "name": r.name, "slug": r.slug, "city_id": int(r.city_id), "city": r.city_name,
        "hidden": (not r.is_active) or r.state in (None, "hidden"),
        "own_page": has_winter_page(r.slug),
    }


async def sitemap_points(session: AsyncSession, *, now: datetime) -> list[dict[str, Any]]:
    """Индексируемые точки (O3) с городом и датой правки — для sitemap.xml."""
    season = ws.current_season(now)
    rows = (await session.execute(text(_SELECT + " AND p.status = 'published' AND p.slug IS NOT NULL ORDER BY a.city_id, a.id"),
                                   {"season": season})).all()
    settings = Settings()
    out: list[dict[str, Any]] = []
    for r in rows:
        item = _shape(r, live={}, photos=[], shared_phone=False, origin=None, settings=settings, detail=False)
        if is_indexable(item):
            out.append({"slug": r.slug, "city": r.city_name, "city_id": int(r.city_id)})
    return out


async def cities_with_points(session: AsyncSession, *, now: datetime) -> list[str]:
    """Названия городов, где есть хотя бы одна показываемая зимняя точка (страница «Зимой в …» не пустая)."""
    rows = (
        await session.execute(
            text(
                """SELECT DISTINCT c.name, c.sort_order, c.id FROM seasonal_rinks sr
                   JOIN arenas a ON a.id = sr.arena_id AND a.is_active
                   JOIN cities c ON c.id = a.city_id AND c.is_active
                   JOIN seasonal_rink_seasons s ON s.arena_id = a.id AND s.season = :season AND s.state <> 'hidden'
                   ORDER BY c.sort_order, c.id"""
            ),
            {"season": ws.current_season(now)},
        )
    ).all()
    return [str(r.name) for r in rows]
