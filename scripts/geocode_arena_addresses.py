"""
One-off: fill arenas.latitude / arenas.longitude from address via Nominatim (OpenStreetMap).

Why Nominatim: no API key, enough for a manual or small batch run. See fair-use:
https://operations.osm.org/policies/nominatim/

Do not call this in a loop from the web app — only run locally / CI occasionally.
Default pause between requests is 1.1s (conservative for the public instance).

Usage:
  PYTHONPATH=. python scripts/geocode_arena_addresses.py --dry-run
  PYTHONPATH=. python scripts/geocode_arena_addresses.py --dry-run --limit 3
  GEOCODE_CONTACT_EMAIL=you@domain.com PYTHONPATH=. python scripts/geocode_arena_addresses.py
  PYTHONPATH=. python scripts/geocode_arena_addresses.py --contact you@domain.com --force

Requires: httpx (already in requirements.txt).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.application.arena_profile import (
    district_from_nominatim_address,
    nominatim_result_matches_city,
)
from src.shared.config import Settings

NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
DEFAULT_SLEEP_SEC = 1.1


def _db_url(settings: Settings) -> str:
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    return url


def _strip_leading_city_abbrev(addr: str) -> str:
    """Nominatim often misses queries starting with «г. Минск, …»; «Минск, …» works better."""
    return re.sub(r"^\s*г\.\s*", "", addr.strip(), flags=re.IGNORECASE)


def _build_search_query(address: str, city_name: str) -> str:
    """Build free-text query. Country is enforced via countrycodes=by — do not append «Беларусь»
    (in practice it *reduces* hit rate for street addresses in BY)."""
    addr = _strip_leading_city_abbrev(address or "")
    city = (city_name or "").strip()
    if not addr:
        return ""
    lower = addr.lower()
    if city and city.lower() not in lower:
        addr = f"{addr}, {city}"
    return addr


def geocode_nominatim(
    client: httpx.Client,
    *,
    query: str,
    user_agent: str,
    sleep_between_retries: float,
) -> tuple[float, float] | None:
    if not query:
        return None

    def _one_request(params: dict[str, str]) -> list:
        url = f"{NOMINATIM_SEARCH}?{urlencode(params)}"
        r = client.get(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept-Language": "ru,be,en",
            },
        )
        if r.status_code == 429:
            raise RuntimeError("Nominatim rate-limited (429); increase --sleep or retry later.")
        r.raise_for_status()
        return r.json()

    # 1) Restrict to Belarus (best default for this product).
    params_by = {
        "q": query,
        "format": "json",
        "limit": "1",
        "countrycodes": "by",
        "addressdetails": "0",
    }
    data = _one_request(params_by)
    if not data and sleep_between_retries > 0:
        time.sleep(sleep_between_retries)
    # 2) Rare edge: OSM has a point just across the border or missing country code — retry without filter.
    if not data:
        params_world = {k: v for k, v in params_by.items() if k != "countrycodes"}
        data = _one_request(params_world)

    if not data:
        return None
    first = data[0]
    lat = float(first["lat"])
    lon = float(first["lon"])
    return lat, lon


def reverse_geocode_nominatim(
    client: httpx.Client,
    *,
    latitude: float,
    longitude: float,
    user_agent: str,
) -> dict | None:
    url = f"{NOMINATIM_REVERSE}?lat={latitude}&lon={longitude}&format=json&addressdetails=1"
    r = client.get(
        url,
        headers={"User-Agent": user_agent, "Accept-Language": "ru,be,en"},
    )
    if r.status_code == 429:
        raise RuntimeError("Nominatim rate-limited (429); increase --sleep or retry later.")
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        return None
    return data


def _run_reverse(args, engine, user_agent: str) -> None:
    """Fill arena_profiles.district from existing coordinates. Never call from the web app."""
    active_clause = "" if args.include_inactive else "AND a.is_active IS TRUE"
    district_clause = "" if args.force else "AND (p.district IS NULL OR trim(p.district) = '')"
    sql = text(
        f"""
        SELECT a.id, a.name, a.latitude, a.longitude, c.name AS city_name, p.district
        FROM arenas a
        JOIN cities c ON c.id = a.city_id
        LEFT JOIN arena_profiles p ON p.arena_id = a.id
        WHERE a.latitude IS NOT NULL AND a.longitude IS NOT NULL
        {active_clause}
        {district_clause}
        ORDER BY a.id
        """
    )
    with Session(engine) as session:
        rows = list(session.execute(sql).mappings().all())
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
    if not rows:
        print("Нет арен для обратного геокодинга (координаты, --force, --include-inactive).")
        return

    print(f"Обратный геокодинг: {len(rows)} арен (sleep={args.sleep}s, dry_run={args.dry_run}).")
    updated = 0
    skipped_city = 0
    failed = 0
    unusual: list[str] = []

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for i, row in enumerate(rows):
            aid = int(row["id"])
            name = row["name"] or ""
            city_name = row["city_name"] or ""
            lat, lon = float(row["latitude"]), float(row["longitude"])
            try:
                payload = reverse_geocode_nominatim(
                    client, latitude=lat, longitude=lon, user_agent=user_agent
                )
            except Exception as e:
                print(f"[{aid}] {name!r} ERROR: {e}")
                failed += 1
                if i + 1 < len(rows):
                    time.sleep(args.sleep)
                continue
            address = (payload or {}).get("address") if payload else None
            district = district_from_nominatim_address(address if isinstance(address, dict) else None)
            if not nominatim_result_matches_city(address if isinstance(address, dict) else None, city_name):
                print(f"[{aid}] {name!r} — промах города (ожидали {city_name!r}), не пишем.")
                skipped_city += 1
            elif not district:
                print(f"[{aid}] {name!r} — район не найден в ответе Nominatim.")
                failed += 1
            else:
                if address and not address.get("city_district") and address.get("suburb"):
                    unusual.append(f"[{aid}] {name}: suburb={district!r} (нет city_district)")
                print(f"[{aid}] {name!r} → {district}")
                if not args.dry_run:
                    with Session(engine) as session:
                        result = session.execute(
                            text(
                                """
                                UPDATE arena_profiles
                                SET district = :district
                                WHERE arena_id = :id
                                  AND (:force OR district IS NULL OR trim(district) = '')
                                """
                            ),
                            {"district": district, "id": aid, "force": bool(args.force)},
                        )
                        session.commit()
                        if result.rowcount:
                            updated += 1
                        else:
                            print(f"[{aid}] нет строки arena_profiles — пропуск (нужен бэкфилл профиля).")
            if i + 1 < len(rows):
                time.sleep(args.sleep)

    if unusual:
        print("К просмотру глазами (микрорайон вместо округа):")
        for line in unusual:
            print(" ", line)
    active_sql = text(
        """
        SELECT
          COUNT(*) FILTER (WHERE a.is_active) AS active,
          COUNT(*) FILTER (WHERE a.is_active AND p.district IS NOT NULL AND trim(p.district) <> '') AS with_district
        FROM arenas a
        LEFT JOIN arena_profiles p ON p.arena_id = a.id
        """
    )
    with Session(engine) as session:
        cov = session.execute(active_sql).mappings().one()
    active = int(cov["active"] or 0)
    with_d = int(cov["with_district"] or 0)
    pct = (100.0 * with_d / active) if active else 0.0
    print(f"Покрытие district у активных: {with_d}/{active} ({pct:.1f}%). Цель AC-002: ≥90%.")
    if args.dry_run:
        print(f"Готово (dry-run). Промах города: {skipped_city}, без района/ошибок: {failed}.")
    else:
        print(f"Готово. Районов записано: {updated}, промах города: {skipped_city}, ошибок: {failed}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Geocode arena addresses (Nominatim → DB).")
    parser.add_argument("--dry-run", action="store_true", help="Print results only, do not UPDATE.")
    parser.add_argument("--limit", type=int, default=0, help="Max arenas to process (0 = all).")
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_SEC,
        help=f"Seconds between HTTP requests (default {DEFAULT_SLEEP_SEC}).",
    )
    parser.add_argument(
        "--contact",
        default="",
        help="Email or URL for User-Agent (or set GEOCODE_CONTACT_EMAIL). Required unless --dry-run.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-geocode even when latitude/longitude already set.",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Also process arenas with is_active = false.",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Fill arena_profiles.district from existing lat/lon (Nominatim reverse).",
    )
    args = parser.parse_args()

    contact = (args.contact or os.environ.get("GEOCODE_CONTACT_EMAIL", "") or "").strip()
    if not args.dry_run and not contact:
        print(
            "Укажите контакт для User-Agent (требование Nominatim): "
            "--contact you@domain.com или переменная GEOCODE_CONTACT_EMAIL.",
            file=sys.stderr,
        )
        sys.exit(1)
    ua_contact = contact if contact else "dry-run@local.invalid"
    user_agent = f"TrainerCRM-ArenaGeocode/1.0 ({ua_contact})"

    settings = Settings()
    engine = create_engine(_db_url(settings))

    if args.reverse:
        _run_reverse(args, engine, user_agent)
        return

    active_clause = "" if args.include_inactive else "AND a.is_active IS TRUE"
    null_clause = "" if args.force else "AND (a.latitude IS NULL OR a.longitude IS NULL)"

    sql = text(
        f"""
        SELECT a.id, a.name, a.address, c.name AS city_name
        FROM arenas a
        JOIN cities c ON c.id = a.city_id
        WHERE trim(coalesce(a.address, '')) != ''
        {active_clause}
        {null_clause}
        ORDER BY a.id
        """
    )

    with Session(engine) as session:
        rows = list(session.execute(sql).mappings().all())

    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    if not rows:
        print("Нет арен для обработки (проверьте адреса, --force, --include-inactive).")
        return

    print(f"К обработке: {len(rows)} арен (sleep={args.sleep}s, dry_run={args.dry_run}).")

    updated = 0
    failed = 0
    resolved = 0

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for i, row in enumerate(rows):
            aid = int(row["id"])
            name = row["name"] or ""
            address = row["address"] or ""
            city_name = row["city_name"] or ""
            q = _build_search_query(address, city_name)
            try:
                coords = geocode_nominatim(
                    client,
                    query=q,
                    user_agent=user_agent,
                    sleep_between_retries=min(1.0, args.sleep),
                )
            except Exception as e:
                print(f"[{aid}] {name!r} ERROR: {e}")
                failed += 1
                time.sleep(args.sleep)
                continue

            if coords is None:
                print(f"[{aid}] {name!r} — не найдено по запросу: {q!r}")
                failed += 1
            else:
                lat, lon = coords
                resolved += 1
                print(f"[{aid}] {name!r} → {lat:.6f}, {lon:.6f}")
                if not args.dry_run:
                    with Session(engine) as session:
                        session.execute(
                            text(
                                "UPDATE arenas SET latitude = :lat, longitude = :lon WHERE id = :id"
                            ),
                            {"lat": lat, "lon": lon, "id": aid},
                        )
                        session.commit()
                    updated += 1

            # Public Nominatim: be gentle — sleep after every request (including failures).
            if i + 1 < len(rows):
                time.sleep(args.sleep)

    if args.dry_run:
        print(f"Готово (dry-run). Найдено координат: {resolved}, без результата/ошибок: {failed}.")
    else:
        print(f"Готово. Строк в БД обновлено: {updated}, не удалось: {failed}.")


if __name__ == "__main__":
    main()
