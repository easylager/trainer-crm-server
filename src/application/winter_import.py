"""Импорт seed сезонных точек 2025/26 (TASK-343): идемпотентно, без дублей каталога.

``plan_rows`` — чистое планирование (дедуп, имена, точность геокода, часы, телефоны).
``import_points`` — запись в БД. Повторный прогон ничего не создаёт и не трогает ручные
правки: у существующей точки обновляются только часы / телефон / источник сезонной записи.

Правила (решения 01.11, каталог краевых случаев):
* закрытые / крытые арены и всё, что уже есть в каталоге (адрес или <=150 м), не дублируем;
* пустые названия и названия школ -> «Каток|Коробка, <адрес>», школа уходит в ``operator``;
* точность city / none -> координат не храним (пин не рисуем, расстояния нет);
* одинаковые имя+адрес или координаты в РАЗНЫХ городах -> точность none;
* OSM-кандидаты без адреса скрыты до подтверждения админом;
* часы — JSON по дням; пусто / непонятно -> «часы уточняйте», никогда не «круглосуточно»;
* новые города создаются неактивными: решение об их показе принимает человек.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_profile import slugify_arena_name
from src.shared.winter_hours import ParsedHours, parse_hours
from src.shared.winter_status import current_season, season_label
from src.shared.winter_text import (
    first_address,
    generated_name,
    is_indoor_name,
    is_school_name,
    normalize_address,
    phone_field,
)

logger = logging.getLogger(__name__)

SEED_SOURCE_SEASON = 2025
MATCH_RADIUS_M = 150.0
MAP_PRECISIONS = frozenset({"house", "osm_exact", "manual"})
NEMIGA_SLUG = "katok-na-nemige-u-dvortsa-sporta"


@dataclass
class PlannedPoint:
    key: str
    city: str
    kind: str  # rink | hockey_box
    name: str
    name_source: str  # source | generated
    operator: str | None
    address: str | None
    district: str | None
    lat: float | None
    lon: float | None
    precision: str
    phone: str | None
    hours: ParsedHours
    is_paid: bool
    source_url: str | None
    confidence: str | None
    hidden_reason: str | None = None
    same_complex_key: str | None = None
    skip_reason: str | None = None
    row_no: int = 0


def _f(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def read_seed(path: str | Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _source_key(city: str, kind: str, norm_addr: str, name: str, lat: float | None, lon: float | None, row_no: int) -> str:
    if norm_addr:
        raw = f"{city.lower()}|{norm_addr}|{kind}"
    else:
        raw = f"{city.lower()}|{kind}|{name.lower()}|{lat}|{lon}|{row_no}"
    return hashlib.sha1(raw.encode()).hexdigest()[:40]


def plan_rows(rows: Iterable[dict[str, str]]) -> list[PlannedPoint]:
    rows = list(rows)
    # Координаты и пары имя+адрес, встреченные в разных городах, недостоверны.
    coord_cities: dict[tuple[float, float], set[str]] = {}
    name_addr_cities: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        city = (r.get("city") or "").strip()
        lat, lon = _f(r.get("lat")), _f(r.get("lon"))
        if lat is not None and lon is not None:
            coord_cities.setdefault((round(lat, 4), round(lon, 4)), set()).add(city)
        na = ((r.get("name") or "").strip().lower(), normalize_address(first_address(r.get("address"))))
        if na[0] and na[1]:
            name_addr_cities.setdefault(na, set()).add(city)

    planned: list[PlannedPoint] = []
    by_key: dict[str, PlannedPoint] = {}
    by_complex: dict[tuple[str, str], PlannedPoint] = {}
    for i, r in enumerate(rows, start=1):
        city = (r.get("city") or "").strip()
        raw_name = (r.get("name") or "").strip()
        kind = "hockey_box" if "коробк" in (r.get("type") or "").lower() else "rink"
        address = first_address(r.get("address")) or None
        norm_addr = normalize_address(address, city)
        lat, lon = _f(r.get("lat")), _f(r.get("lon"))
        precision = (r.get("geocode_precision") or "none").strip() or "none"
        district = (r.get("district") or "").strip() or None
        if not city:
            continue
        shared_coord = (
            lat is not None and lon is not None and len(coord_cities.get((round(lat, 4), round(lon, 4)), ())) > 1
        )
        shared_name = bool(raw_name and norm_addr) and len(name_addr_cities.get((raw_name.lower(), normalize_address(address)), ())) > 1
        if shared_coord or shared_name:
            precision = "none"
        if precision in ("city", "none"):
            lat = lon = None

        operator = None
        name, name_source = raw_name, "source"
        if not raw_name or is_school_name(raw_name):
            name = generated_name(kind, address, district, city)
            name_source = "generated"
            operator = raw_name or None
        hours = parse_hours(r.get("hours"))
        paid = (r.get("paid") or "").strip().lower() == "платный"
        key = _source_key(city, kind, norm_addr, name, lat, lon, i)
        p = PlannedPoint(
            key=key, city=city, kind=kind, name=name[:128], name_source=name_source, operator=(operator or None),
            address=address, district=district, lat=lat, lon=lon, precision=precision,
            phone=phone_field(r.get("phone")), hours=hours, is_paid=paid,
            source_url=(r.get("source_url") or None), confidence=(r.get("confidence") or None), row_no=i,
        )
        if is_indoor_name(raw_name):
            p.skip_reason = "indoor"
        elif key in by_key:
            first = by_key[key]
            # Дубль внутри seed: добираем пустое, строку не создаём.
            if not first.phone and p.phone:
                first.phone = p.phone
            if not first.hours.known and p.hours.known:
                first.hours = p.hours
            p.skip_reason = "duplicate"
        else:
            by_key[key] = p
            if (r.get("confidence") or "") == "candidate" and not address:
                p.hidden_reason = "candidate"
            if norm_addr:
                twin = by_complex.get((city, norm_addr))
                if twin is not None and twin.kind != kind:
                    p.same_complex_key = twin.key
                    twin.same_complex_key = twin.same_complex_key or p.key
                by_complex.setdefault((city, norm_addr), p)
        planned.append(p)
    return planned


@dataclass
class ImportReport:
    created: int = 0
    existing: int = 0
    matched_catalog: list[str] = field(default_factory=list)
    skipped_indoor: list[str] = field(default_factory=list)
    skipped_duplicate: int = 0
    hidden_candidates: int = 0
    new_cities: list[str] = field(default_factory=list)
    no_map: int = 0
    hours_known: int = 0
    hours_unknown: int = 0
    nemiga: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


async def _city_id(session: AsyncSession, name: str, cache: dict[str, int], report: ImportReport) -> int:
    if name in cache:
        return cache[name]
    row = (
        await session.execute(
            text("SELECT id FROM cities WHERE lower(trim(name)) = lower(trim(:n)) ORDER BY is_active DESC, id LIMIT 1"),
            {"n": name},
        )
    ).first()
    if row:
        cache[name] = int(row[0])
        return cache[name]
    new_id = (
        await session.execute(
            text("INSERT INTO cities (name, country, is_active, sort_order) VALUES (:n, 'BY', false, 900) RETURNING id"),
            {"n": name},
        )
    ).scalar_one()
    report.new_cities.append(name)
    cache[name] = int(new_id)
    return cache[name]


async def _catalog_arenas(session: AsyncSession, city_id: int) -> list[dict[str, Any]]:
    """Арены города, которые не являются сезонными точками: с ними сверяем адрес и координаты."""
    res = await session.execute(
        text(
            """
            SELECT a.id, a.name, a.address, a.latitude, a.longitude
            FROM arenas a
            WHERE a.city_id = :cid AND a.is_active
              AND NOT EXISTS (SELECT 1 FROM seasonal_rinks sr WHERE sr.arena_id = a.id)
            """
        ),
        {"cid": city_id},
    )
    return [dict(r) for r in res.mappings()]


def _match_catalog(p: PlannedPoint, arenas: list[dict[str, Any]]) -> dict[str, Any] | None:
    norm = normalize_address(p.address, p.city)
    for a in arenas:
        if norm and normalize_address(a.get("address"), p.city) == norm:
            return a
    if p.precision in MAP_PRECISIONS and p.lat is not None and p.lon is not None:
        for a in arenas:
            if a["latitude"] is not None and a["longitude"] is not None:
                if haversine_m(p.lat, p.lon, float(a["latitude"]), float(a["longitude"])) <= MATCH_RADIUS_M:
                    return a
    return None


async def _upsert_season(
    session: AsyncSession, arena_id: int, season: int, p: PlannedPoint, *, state: str, hidden_reason: str | None
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO seasonal_rink_seasons
                (arena_id, season, state, state_source, hidden_reason, hours_text, opening_hours, hours_known,
                 hours_season, season_from, season_to, phone, source_url, source_kind, confidence)
            VALUES
                (:aid, :season, :state, 'import', :hr, :ht, CAST(:oh AS jsonb), :hk,
                 :hs, :sf, :st, :phone, :url, 'pdf', :conf)
            ON CONFLICT (arena_id, season) DO UPDATE SET
                hours_text = EXCLUDED.hours_text, opening_hours = EXCLUDED.opening_hours,
                hours_known = EXCLUDED.hours_known, hours_season = EXCLUDED.hours_season,
                season_from = EXCLUDED.season_from, season_to = EXCLUDED.season_to,
                phone = EXCLUDED.phone, source_url = EXCLUDED.source_url,
                confidence = EXCLUDED.confidence, updated_at = now()
            """
        ),
        {
            "aid": arena_id, "season": season, "state": state, "hr": hidden_reason,
            "ht": (p.hours.raw or None) and p.hours.raw[:256],
            "oh": json.dumps(p.hours.opening_hours) if p.hours.opening_hours else None,
            "hk": p.hours.known, "hs": season_label(SEED_SOURCE_SEASON),
            "sf": p.hours.season_from, "st": p.hours.season_to, "phone": p.phone,
            "url": p.source_url, "conf": p.confidence,
        },
    )


async def import_points(
    session: AsyncSession, planned: list[PlannedPoint], *, now: datetime, publish: bool = False
) -> ImportReport:
    """Записать точки. ``publish`` -> профиль каталога ``published`` (по умолчанию ``draft``)."""
    report = ImportReport()
    season = current_season(now)
    city_cache: dict[str, int] = {}
    catalog_cache: dict[int, list[dict[str, Any]]] = {}
    arena_by_key: dict[str, int] = {}
    profile_status = "published" if publish else "draft"

    for p in planned:
        if p.skip_reason == "indoor":
            report.skipped_indoor.append(f"{p.city}: {p.name}")
            continue
        if p.skip_reason == "duplicate":
            report.skipped_duplicate += 1
            continue
        existing = (
            await session.execute(text("SELECT arena_id FROM seasonal_rinks WHERE source_key = :k"), {"k": p.key})
        ).first()
        city_id = await _city_id(session, p.city, city_cache, report)
        if existing:
            aid = int(existing[0])
            arena_by_key[p.key] = aid
            # Ручное не трогаем: меняем только часы, телефон, источник в сезонной записи.
            row = (
                await session.execute(
                    text("SELECT state FROM seasonal_rink_seasons WHERE arena_id=:a AND season=:s"),
                    {"a": aid, "s": season},
                )
            ).first()
            if row is None:
                await _upsert_season(session, aid, season, p, state="waiting", hidden_reason=None)
            else:
                await session.execute(
                    text(
                        """UPDATE seasonal_rink_seasons SET hours_text=:ht, opening_hours=CAST(:oh AS jsonb),
                           hours_known=:hk, season_from=:sf, season_to=:st,
                           phone = COALESCE(:phone, phone), source_url = COALESCE(:url, source_url), updated_at=now()
                           WHERE arena_id=:a AND season=:s"""
                    ),
                    {
                        "a": aid, "s": season, "ht": p.hours.raw[:256] or None,
                        "oh": json.dumps(p.hours.opening_hours) if p.hours.opening_hours else None,
                        "hk": p.hours.known, "sf": p.hours.season_from, "st": p.hours.season_to,
                        "phone": p.phone, "url": p.source_url,
                    },
                )
            report.existing += 1
            continue

        arenas = catalog_cache.setdefault(city_id, await _catalog_arenas(session, city_id))
        matched = _match_catalog(p, arenas)
        if matched is not None:
            report.matched_catalog.append(f"{p.city}: {p.name} -> arena {matched['id']} {matched['name']}")
            continue

        arena_id = int(
            (
                await session.execute(
                    text(
                        """INSERT INTO arenas (city_id, name, address, latitude, longitude, venue_type, is_active, is_confirmed)
                           VALUES (:c, :n, :a, :lat, :lon, 'outdoor', true, true) RETURNING id"""
                    ),
                    {"c": city_id, "n": p.name, "a": p.address, "lat": p.lat, "lon": p.lon},
                )
            ).scalar_one()
        )
        arena_by_key[p.key] = arena_id
        kind_slug = "korobka" if p.kind == "hockey_box" else "katok"
        slug = f"{slugify_arena_name(p.city)}-{kind_slug}-{arena_id}"
        await session.execute(
            text(
                """INSERT INTO arena_profiles (arena_id, city_id, slug, district, status, phone, amenities, social_urls)
                   VALUES (:a, :c, :slug, :d, :st, :ph, '{}'::jsonb, '{}'::jsonb)"""
            ),
            {"a": arena_id, "c": city_id, "slug": slug, "d": p.district, "st": profile_status, "ph": p.phone},
        )
        await session.execute(
            text(
                """INSERT INTO seasonal_rinks (arena_id, kind, operator, is_paid, often_hockey, geocode_precision,
                                               source_key, name_source)
                   VALUES (:a, :k, :op, :paid, :oh, :prec, :key, :ns)"""
            ),
            {
                "a": arena_id, "k": p.kind, "op": (p.operator or None) and p.operator[:256],
                "paid": p.is_paid, "oh": p.kind == "hockey_box" and bool(p.operator and is_school_name(p.operator)),
                "prec": p.precision, "key": p.key, "ns": p.name_source,
            },
        )
        state = "hidden" if p.hidden_reason else "waiting"
        await _upsert_season(session, arena_id, season, p, state=state, hidden_reason=p.hidden_reason)
        if p.hidden_reason:
            report.hidden_candidates += 1
            await session.execute(
                text(
                    """INSERT INTO seasonal_moderation_items (kind, arena_id) VALUES ('new_point', :a)
                       ON CONFLICT DO NOTHING"""
                ),
                {"a": arena_id},
            )
        if p.precision not in MAP_PRECISIONS:
            report.no_map += 1
        report.hours_known += 1 if p.hours.known else 0
        report.hours_unknown += 0 if p.hours.known else 1
        report.created += 1

    for p in planned:
        if p.same_complex_key and p.key in arena_by_key and p.same_complex_key in arena_by_key:
            await session.execute(
                text("UPDATE seasonal_rinks SET same_complex_id = :o WHERE arena_id = :a AND same_complex_id IS NULL"),
                {"o": arena_by_key[p.same_complex_key], "a": arena_by_key[p.key]},
            )
    report.nemiga = await pin_nemiga(session, now=now)
    return report


async def pin_nemiga(session: AsyncSession, *, now: datetime) -> str:
    """Немига — существующая арена каталога: закрепляем первой и заводим зимнюю запись."""
    row = (
        await session.execute(
            text(
                """SELECT a.id FROM arenas a JOIN arena_profiles p ON p.arena_id = a.id
                   WHERE p.slug = :slug LIMIT 1"""
            ),
            {"slug": NEMIGA_SLUG},
        )
    ).first()
    if row is None:
        row = (
            await session.execute(
                text(
                    """SELECT id FROM arenas WHERE venue_type = 'outdoor' AND is_active AND name ILIKE '%немиг%'
                       ORDER BY id LIMIT 1"""
                )
            )
        ).first()
    if row is None:
        return "not found: pin skipped"
    aid = int(row[0])
    await session.execute(text("UPDATE arena_profiles SET catalog_pin = 1 WHERE arena_id = :a"), {"a": aid})
    await session.execute(
        text(
            """INSERT INTO seasonal_rinks (arena_id, kind, geocode_precision, name_source)
               VALUES (:a, 'rink', 'house', 'admin') ON CONFLICT (arena_id) DO NOTHING"""
        ),
        {"a": aid},
    )
    await session.execute(
        text(
            """INSERT INTO seasonal_rink_seasons (arena_id, season, state, state_source, source_kind, confidence)
               VALUES (:a, :s, 'waiting', 'import', 'admin', 'high') ON CONFLICT (arena_id, season) DO NOTHING"""
        ),
        {"a": aid, "s": current_season(now)},
    )
    return f"arena {aid} pinned"
