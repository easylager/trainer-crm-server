"""Аудит полноты каталога: чего не хватает, чтобы закрыть всю Беларусь (TASK-146).

Отчёт для человека, который заполняет пробелы руками: по каждому городу —
сколько опубликовано мест по типам, у каких мест нет координат/фото/часов/телефона/
кассы, у каких катков нет парсера расписания (или он сломан/устарел), какие катки
из ``data/*sources*.csv`` / ``data/*arenas*-prod.csv`` не нашлись в БД и каких полей
не хватает магазинам из ``data/catalog/shops-*.json``.

Только чтение. Ничего не выдумываем: пустое поле — это строка «нет: …» в отчёте,
а не догадка. Скрипт-обёртка — ``scripts/catalog_coverage_report.py``.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.ice_discovery_scope import arena_publicly_visible_row
from src.shared.venue_types import (
    VENUE_TYPE_SHOP,
    has_public_skating,
    normalize_venue_type,
    venue_type_chip,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

_ARENAS_SQL = """
SELECT
    a.id, a.name, a.address, a.city_id, c.name AS city_name, c.country AS city_country,
    c.is_active AS city_is_active, a.created_by_trainer_id,
    a.venue_type, a.is_active, a.is_confirmed, a.latitude, a.longitude,
    p.status AS profile_status, p.phone, p.website_url, p.tickets_url,
    p.opening_hours, p.amenities,
    EXISTS (
        SELECT 1 FROM media m
        WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
    ) AS has_photo,
    j.id AS job_id, j.is_enabled AS job_enabled, j.parser_key, j.config AS job_config,
    j.created_at AS job_created_at, j.last_ok_at, j.failure_streak, j.last_error_code,
    (
        SELECT COUNT(*)::int FROM ice_sessions s
        WHERE s.arena_id = a.id AND s.status = 'active'
          AND s.kind IN ('public_skate', 'open_ice')
          AND s.starts_at_utc > :now
          AND (s.valid_until IS NULL OR s.valid_until >= :now)
    ) AS future_sessions
FROM arenas a
JOIN cities c ON c.id = a.city_id
LEFT JOIN arena_profiles p ON p.arena_id = a.id
LEFT JOIN ice_parser_jobs j ON j.arena_id = a.id
ORDER BY c.name, a.name, a.id
"""

GAP_COORDS = "координаты"
GAP_PHOTO = "фото"
GAP_HOURS = "часы работы"
GAP_PHONE = "телефон"
GAP_TICKETS = "касса (tickets_url)"
GAP_WEBSITE = "сайт"
GAP_ADDRESS = "адрес"


@dataclass
class ArenaRow:
    id: int
    name: str
    address: str | None
    city_id: int
    city_name: str
    country: str
    venue_type: str
    published: bool
    gaps: list[str]
    job_id: int | None
    job_enabled: bool
    parser_key: str | None
    parser_state: str | None
    future_sessions: int
    amenities: dict[str, Any]


@dataclass
class KnownRink:
    """Каток из файлов data/, которого может не быть в БД."""

    source_file: str
    name: str
    city_name: str | None
    arena_id: int | None
    address: str | None
    country: str | None = None
    note: str | None = None


@dataclass
class ShopGap:
    city_name: str
    name: str
    missing_in_file: list[str]
    db_arena_id: int | None
    missing_in_db: list[str]


@dataclass
class CityCoverage:
    city_name: str
    country: str
    published_by_type: dict[str, int] = field(default_factory=dict)
    unpublished: int = 0
    arenas_with_gaps: list[ArenaRow] = field(default_factory=list)
    rinks_without_parser: list[ArenaRow] = field(default_factory=list)
    rinks_parser_problem: list[ArenaRow] = field(default_factory=list)
    known_missing_in_db: list[KnownRink] = field(default_factory=list)
    shops: list[ShopGap] = field(default_factory=list)
    rink_sharpening_problems: list[str] = field(default_factory=list)


@dataclass
class CoverageReport:
    generated_at: datetime
    cities: list[CityCoverage]
    totals: dict[str, int]


def normalize_name(value: str | None) -> str:
    """Имя для сравнения: без регистра, ё→е, кавычек, пунктуации и лишних пробелов."""
    s = str(value or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'“”„()\-–—.,:;!?/\\]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _empty_mapping(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return not value.strip()
    return not value


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except ValueError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def arena_gaps(row: dict[str, Any]) -> list[str]:
    """Чего не хватает карточке места. Касса — только у катков (там продают сеансы)."""
    gaps: list[str] = []
    if row.get("latitude") is None or row.get("longitude") is None:
        gaps.append(GAP_COORDS)
    if not row.get("has_photo"):
        gaps.append(GAP_PHOTO)
    if _empty_mapping(row.get("opening_hours")):
        gaps.append(GAP_HOURS)
    if _blank(row.get("phone")):
        gaps.append(GAP_PHONE)
    if has_public_skating(row.get("venue_type")) and _blank(row.get("tickets_url")):
        gaps.append(GAP_TICKETS)
    if _blank(row.get("website_url")):
        gaps.append(GAP_WEBSITE)
    return gaps


def _parser_state(row: dict[str, Any], now: datetime) -> str | None:
    """None — парсер в порядке; иначе короткое человеческое описание проблемы."""
    from src.ingestion.freshness import is_schedule_stale

    if row.get("job_id") is None:
        return "нет парсера"
    if not row.get("job_enabled"):
        return f"парсер {row.get('parser_key')} выключен"
    streak = int(row.get("failure_streak") or 0)
    if streak > 0:
        return f"парсер {row.get('parser_key')} падает ({row.get('last_error_code') or 'error'}, {streak} подряд)"
    config = row.get("job_config")
    if is_schedule_stale(
        has_enabled_job=True,
        last_ok_at=row.get("last_ok_at"),
        config=config if isinstance(config, dict) else None,
        now=now,
        created_at=row.get("job_created_at"),
    ):
        last = row.get("last_ok_at")
        when = last.strftime("%Y-%m-%d %H:%M UTC") if last else "никогда"
        return f"парсер {row.get('parser_key')} устарел (последний ok: {when})"
    return None


def _is_published(row: dict[str, Any]) -> bool:
    return arena_publicly_visible_row(row)


async def load_arenas(session: AsyncSession, *, now: datetime) -> list[ArenaRow]:
    result = await session.execute(text(_ARENAS_SQL), {"now": now})
    rows: list[ArenaRow] = []
    for raw in result.mappings():
        data = dict(raw)
        published = _is_published(data)
        skating = has_public_skating(data.get("venue_type"))
        rows.append(
            ArenaRow(
                id=int(data["id"]),
                name=str(data["name"] or ""),
                address=data.get("address"),
                city_id=int(data["city_id"]),
                city_name=str(data["city_name"] or ""),
                country=str(data.get("city_country") or data.get("country") or ""),
                venue_type=normalize_venue_type(data.get("venue_type")),
                published=published,
                gaps=arena_gaps(data),
                job_id=data.get("job_id"),
                job_enabled=bool(data.get("job_enabled")),
                parser_key=data.get("parser_key"),
                parser_state=_parser_state(data, now) if skating else None,
                future_sessions=int(data.get("future_sessions") or 0),
                amenities=_as_dict(data.get("amenities")),
            )
        )
    return rows


# ── Известные катки из data/ ─────────────────────────────────────────────


def _city_from_address(address: str | None) -> str | None:
    """«Минск, ул. Ташкентская, 19» → «Минск». Без запятой — не гадаем."""
    if not address or "," not in address:
        return None
    head = address.split(",", 1)[0].strip()
    return head or None


def load_known_rinks(paths: Iterable[Path]) -> list[KnownRink]:
    """Катки из CSV в data/: колонки arena_id?, arena_name|name, city_name?, address?, country?.

    Берём всё; фильтр по стране делает build_coverage_report.
    """
    rinks: list[KnownRink] = []
    for path in paths:
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for rec in reader:
                name = (rec.get("arena_name") or rec.get("name") or "").strip()
                if not name:
                    continue
                # Вторичные источники того же катка и «не лёд / только тренировки» —
                # не пробел каталога.
                if (rec.get("is_primary") or "").strip().lower() == "false":
                    continue
                verdict = (rec.get("spike_verdict") or rec.get("update_cadence") or "").strip()
                if verdict.startswith("skip_"):
                    continue
                raw_id = (rec.get("arena_id") or "").strip()
                address = (rec.get("address") or "").strip() or None
                city = (rec.get("city_name") or "").strip() or _city_from_address(address)
                country = (rec.get("country") or "").strip()
                rinks.append(
                    KnownRink(
                        source_file=path.name,
                        name=name,
                        city_name=city or ("Минск" if path.name.startswith("minsk-") else None),
                        arena_id=int(raw_id) if raw_id.isdigit() else None,
                        address=address,
                        country=country or None,
                        note=verdict or None,
                    )
                )
    # Файл источников знает arena_id, но не адрес; прод-выгрузка арен — наоборот.
    # Склеиваем по arena_id, чтобы один каток не выглядел двумя разными.
    address_by_id = {r.arena_id: r.address for r in rinks if r.arena_id is not None and r.address}
    for r in rinks:
        if r.address is None and r.arena_id in address_by_id:
            r.address = address_by_id[r.arena_id]
    return rinks


# Слова, которые есть в названии почти любого катка: по ним «Ледовая арена» в Берёзе
# совпала бы с «Ледовой ареной» в Кобрине. Сравниваем по остальным.
_GENERIC_NAME_TOKENS = frozenset(
    """
    каток катка катки ледовый ледовая ледовое ледовой лед дворец дворца спорта спорт
    спортивный спортивная арена арены тц трц хк ск гу центр хоккейный хоккейная
    минск минской минская области область крытый крытая парк сдюшор по фигурному
    катанию фигурное фигурного им имени комплекс мобильный площадка стадион
    конькобежный малая большая школьные дворовые пул ice city arena
    """.split()
)
_STREET_NOISE = re.compile(
    r"\b(минск|минская|область|ул|улица|пр т|пр|т|проспект|пер|переулок|пл|площадь|"
    r"с с|д|дом|г|город|region|hrodna)\b"
)


def name_tokens(value: str | None) -> set[str]:
    return {t for t in normalize_name(value).split() if len(t) >= 3 and t not in _GENERIC_NAME_TOKENS}


def address_key(value: str | None) -> tuple[str, str] | None:
    """«ул. Притыцкого 27, Минск» и «Минск, ул. Притыцкого, 27» → ('притыцкого', '27')."""
    s = _STREET_NOISE.sub(" ", normalize_name(value))
    m = re.search(r"([а-яa-z]{4,})\s+(\d+)", re.sub(r"\s+", " ", s))
    return (m.group(1), m.group(2)) if m else None


def _token_overlap_ratio(a: str, b: str) -> float:
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    union = ta | tb
    return len(ta & tb) / len(union)


def _coords_within_meters(
    lat_a: float | None,
    lon_a: float | None,
    lat_b: float | None,
    lon_b: float | None,
    *,
    max_m: float = 150.0,
) -> bool:
    if lat_a is None or lon_a is None or lat_b is None or lon_b is None:
        return False
    r = 6_371_000.0
    phi1, phi2 = math.radians(lat_a), math.radians(lat_b)
    dphi = math.radians(lat_b - lat_a)
    dlambda = math.radians(lon_b - lon_a)
    x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x)) <= max_m


def _names_match(
    a: str,
    b: str,
    *,
    lat_a: float | None = None,
    lon_a: float | None = None,
    lat_b: float | None = None,
    lon_b: float | None = None,
) -> bool:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if _token_overlap_ratio(a, b) >= 0.5:
        return True
    return _coords_within_meters(lat_a, lon_a, lat_b, lon_b)


def _same_place(
    name_a: str,
    addr_a: str | None,
    name_b: str,
    addr_b: str | None,
    *,
    lat_a: float | None = None,
    lon_a: float | None = None,
    lat_b: float | None = None,
    lon_b: float | None = None,
) -> bool:
    if _names_match(name_a, name_b, lat_a=lat_a, lon_a=lon_a, lat_b=lat_b, lon_b=lon_b):
        return True
    ka, kb = address_key(addr_a), address_key(addr_b)
    return ka is not None and ka == kb


def match_known_rink(rink: KnownRink, arenas: list[ArenaRow]) -> ArenaRow | None:
    """Сначала по arena_id (если имя похоже), потом по имени/адресу в том же городе."""
    visible = [a for a in arenas if a.published]
    if rink.arena_id is not None:
        for arena in visible:
            if arena.id == rink.arena_id and _same_place(
                arena.name,
                arena.address,
                rink.name,
                rink.address,
            ):
                return arena
    city = normalize_name(rink.city_name) if rink.city_name else None
    for arena in visible:
        if city and normalize_name(arena.city_name) != city:
            continue
        if _same_place(arena.name, arena.address, rink.name, rink.address):
            return arena
    return None


def default_known_rink_files(data_dir: Path = DATA_DIR) -> list[Path]:
    # Прод-выгрузки арен первыми: у них есть адрес и город — по ним лучше склейка.
    files = sorted(data_dir.glob("*arenas*-prod.csv")) + sorted(data_dir.glob("*sources*.csv"))
    return list(dict.fromkeys(files))


# ── Магазины из data/catalog ─────────────────────────────────────────────


def shop_file_gaps(raw: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if _blank(raw.get("address")):
        gaps.append(GAP_ADDRESS)
    if not raw.get("hours"):
        gaps.append(GAP_HOURS)
    if not [p for p in raw.get("phones") or [] if str(p).strip()]:
        gaps.append(GAP_PHONE)
    if _blank(raw.get("website")) and _blank(raw.get("instagram")):
        gaps.append("сайт/инстаграм")
    return gaps


def default_shop_files(data_dir: Path = DATA_DIR) -> list[Path]:
    return sorted((data_dir / "catalog").glob("shops-*.json"))


def _shop_coverage(
    path: Path, arenas: list[ArenaRow]
) -> tuple[str, list[ShopGap], list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    city = str(data.get("city") or "").strip()
    city_key = normalize_name(city)
    in_city = [a for a in arenas if normalize_name(a.city_name) == city_key]
    shops_db = [a for a in in_city if a.venue_type == VENUE_TYPE_SHOP]
    gaps: list[ShopGap] = []
    for raw in data.get("shops") or []:
        name = str(raw.get("name") or "").strip()
        match = next((a for a in shops_db if normalize_name(a.name) == normalize_name(name)), None)
        db_missing: list[str] = []
        if match is None:
            db_missing = []
        else:
            db_missing = [g for g in match.gaps if g in (GAP_COORDS, GAP_PHOTO, GAP_HOURS, GAP_PHONE)]
            if not match.published:
                db_missing.append("не опубликован")
        gaps.append(
            ShopGap(
                city_name=city,
                name=name,
                missing_in_file=shop_file_gaps(raw),
                db_arena_id=match.id if match else None,
                missing_in_db=db_missing,
            )
        )
    problems: list[str] = []
    for rule in data.get("rink_sharpening") or []:
        note = str(rule.get("note") or "")
        needles = [normalize_name(m) for m in rule.get("match") or []]
        hits = [
            a
            for a in in_city
            if a.venue_type != VENUE_TYPE_SHOP
            and any(n and n in normalize_name(a.name) for n in needles)
        ]
        if not hits:
            problems.append(f"{note}: каток не найден в БД")
        elif len(hits) > 1:
            names = ", ".join(f"#{a.id} {a.name}" for a in hits)
            problems.append(f"{note}: неоднозначно ({names})")
        elif not hits[0].amenities.get("skate_sharpening"):
            problems.append(f"{note}: #{hits[0].id} без отметки «заточка» в карточке")
    return city, gaps, problems


# ── Сборка ───────────────────────────────────────────────────────────────


async def build_coverage_report(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    countries: set[str] | None = frozenset({"BY"}),
    city: str | None = None,
    known_rink_files: list[Path] | None = None,
    shop_files: list[Path] | None = None,
) -> CoverageReport:
    now = now or datetime.now(timezone.utc)
    arenas = await load_arenas(session, now=now)
    if countries:
        arenas = [a for a in arenas if a.country in countries]
    city_key = normalize_name(city) if city else None

    by_city: dict[str, CityCoverage] = {}

    def bucket(name: str, country: str = "") -> CityCoverage:
        key = normalize_name(name) or "—"
        if key not in by_city:
            by_city[key] = CityCoverage(city_name=name or "—", country=country)
        return by_city[key]

    for arena in arenas:
        cov = bucket(arena.city_name, arena.country)
        if not arena.published:
            cov.unpublished += 1
            continue
        cov.published_by_type[arena.venue_type] = cov.published_by_type.get(arena.venue_type, 0) + 1
        if arena.gaps:
            cov.arenas_with_gaps.append(arena)
        if arena.parser_state == "нет парсера":
            cov.rinks_without_parser.append(arena)
        elif arena.parser_state:
            cov.rinks_parser_problem.append(arena)

    files = known_rink_files if known_rink_files is not None else default_known_rink_files()
    for rink in load_known_rinks(files):
        if countries and rink.country and rink.country not in countries:
            continue
        if match_known_rink(rink, arenas) is not None:
            continue
        cov = bucket(rink.city_name or "—")
        # Один каток в двух файлах под разными именами — одна строка отчёта.
        if any(
            _same_place(prev.name, prev.address, rink.name, rink.address) for prev in cov.known_missing_in_db
        ):
            continue
        cov.known_missing_in_db.append(rink)

    for path in shop_files if shop_files is not None else default_shop_files():
        shop_city, gaps, problems = _shop_coverage(path, arenas)
        cov = bucket(shop_city)
        cov.shops.extend(gaps)
        cov.rink_sharpening_problems.extend(problems)

    cities = sorted(by_city.values(), key=lambda c: (-sum(c.published_by_type.values()), c.city_name))
    if city_key:
        cities = [c for c in cities if normalize_name(c.city_name) == city_key]
    totals: dict[str, int] = defaultdict(int)
    for cov in cities:
        totals["published"] += sum(cov.published_by_type.values())
        totals["unpublished"] += cov.unpublished
        totals["with_gaps"] += len(cov.arenas_with_gaps)
        totals["rinks_without_parser"] += len(cov.rinks_without_parser)
        totals["rinks_parser_problem"] += len(cov.rinks_parser_problem)
        totals["known_missing_in_db"] += len(cov.known_missing_in_db)
        totals["shops_with_gaps"] += sum(1 for s in cov.shops if _shop_has_gap(s))
    return CoverageReport(generated_at=now, cities=cities, totals=dict(totals))


def _shop_has_gap(shop: ShopGap) -> bool:
    return bool(shop.missing_in_file or shop.missing_in_db or shop.db_arena_id is None)


def format_coverage_report(report: CoverageReport) -> str:
    t = report.totals
    lines = [
        f"Покрытие каталога — {report.generated_at:%Y-%m-%d %H:%M} UTC",
        (
            f"Итого: опубликовано {t.get('published', 0)}, не опубликовано {t.get('unpublished', 0)}; "
            f"с пробелами в карточке {t.get('with_gaps', 0)}; катков без парсера "
            f"{t.get('rinks_without_parser', 0)}, с проблемным парсером {t.get('rinks_parser_problem', 0)}; "
            f"известных катков нет в БД {t.get('known_missing_in_db', 0)}; "
            f"магазинов с пробелами {t.get('shops_with_gaps', 0)}"
        ),
    ]
    for cov in report.cities:
        lines += ["", f"=== {cov.city_name}" + (f" ({cov.country})" if cov.country else "") + " ==="]
        if cov.published_by_type:
            parts = ", ".join(
                f"{venue_type_chip(k)} {v}" for k, v in sorted(cov.published_by_type.items(), key=lambda kv: -kv[1])
            )
            lines.append(f"Опубликовано: {parts}" + (f" · не опубликовано: {cov.unpublished}" if cov.unpublished else ""))
        elif cov.unpublished:
            lines.append(f"Опубликованных нет · не опубликовано: {cov.unpublished}")
        if cov.rinks_without_parser:
            lines.append(f"Катки без парсера расписания ({len(cov.rinks_without_parser)}):")
            for a in cov.rinks_without_parser:
                tail = f", сеансов в базе: {a.future_sessions}" if a.future_sessions else ""
                lines.append(f"  - #{a.id} {a.name}{tail}")
        if cov.rinks_parser_problem:
            lines.append(f"Катки с проблемным парсером ({len(cov.rinks_parser_problem)}):")
            for a in cov.rinks_parser_problem:
                lines.append(f"  - #{a.id} {a.name}: {a.parser_state}; будущих сеансов: {a.future_sessions}")
        if cov.arenas_with_gaps:
            lines.append(f"Пробелы в карточках ({len(cov.arenas_with_gaps)}):")
            for a in sorted(cov.arenas_with_gaps, key=lambda r: (-len(r.gaps), r.name)):
                lines.append(f"  - #{a.id} {a.name} [{venue_type_chip(a.venue_type)}] — нет: {', '.join(a.gaps)}")
        if cov.known_missing_in_db:
            lines.append(f"Известны по data/, но нет в БД ({len(cov.known_missing_in_db)}):")
            for r in cov.known_missing_in_db:
                ref = f" (arena_id {r.arena_id} в файле)" if r.arena_id is not None else ""
                addr = f", {r.address}" if r.address else ""
                note = f" [{r.note}]" if r.note else ""
                lines.append(f"  - {r.name}{addr}{ref}{note} ← {r.source_file}")
        if cov.shops:
            gaps = [s for s in cov.shops if _shop_has_gap(s)]
            lines.append(f"Магазины из data/catalog: {len(cov.shops)}, с пробелами: {len(gaps)}")
            for s in gaps:
                bits = []
                if s.missing_in_file:
                    bits.append("в файле нет: " + ", ".join(s.missing_in_file))
                if s.db_arena_id is None:
                    bits.append("в БД отсутствует (scripts/load_catalog_shops.py --apply)")
                elif s.missing_in_db:
                    bits.append(f"в БД #{s.db_arena_id} нет: " + ", ".join(s.missing_in_db))
                lines.append(f"  - {s.name} — " + "; ".join(bits))
        for problem in cov.rink_sharpening_problems:
            lines.append(f"  ? заточка на катке — {problem}")
    return "\n".join(lines)


def coverage_report_as_dict(report: CoverageReport) -> dict[str, Any]:
    def arena(a: ArenaRow) -> dict[str, Any]:
        return {
            "id": a.id,
            "name": a.name,
            "venue_type": a.venue_type,
            "gaps": a.gaps,
            "parser_key": a.parser_key,
            "parser_state": a.parser_state,
            "future_sessions": a.future_sessions,
        }

    return {
        "generated_at": report.generated_at.isoformat(),
        "totals": report.totals,
        "cities": [
            {
                "city_name": c.city_name,
                "country": c.country,
                "published_by_type": c.published_by_type,
                "unpublished": c.unpublished,
                "arenas_with_gaps": [arena(a) for a in c.arenas_with_gaps],
                "rinks_without_parser": [arena(a) for a in c.rinks_without_parser],
                "rinks_parser_problem": [arena(a) for a in c.rinks_parser_problem],
                "known_missing_in_db": [r.__dict__ for r in c.known_missing_in_db],
                "shops": [s.__dict__ for s in c.shops],
                "rink_sharpening_problems": c.rink_sharpening_problems,
            }
            for c in report.cities
        ],
    }
