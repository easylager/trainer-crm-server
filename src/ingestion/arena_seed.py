"""Insert cities, arenas, and published arena_profiles for parser binding.

Caller owns the transaction. The CLI scripts commit; tests pass a session on a
throwaway database and commit themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class SeedCity:
    name: str
    sort_order: int
    country: str = "BY"
    price_group: str = "BY_BASE"


@dataclass(frozen=True)
class SeedArena:
    arena_id: int
    city_name: str
    name: str
    address: str
    latitude: float | None
    longitude: float | None
    slug: str
    has_parser: bool = False
    parser_key: str | None = None
    timezone: str = "Europe/Minsk"


def arenas_by_parser_key(arenas: list[SeedArena]) -> dict[str, SeedArena]:
    found: dict[str, SeedArena] = {}
    for arena in arenas:
        if not arena.parser_key:
            continue
        if arena.parser_key in found:
            raise ValueError(f"duplicate parser_key {arena.parser_key}")
        found[arena.parser_key] = arena
    return found


def apply_arena_seed(
    session: Session,
    cities: list[SeedCity],
    arenas: list[SeedArena],
    *,
    verbose: bool = True,
) -> None:
    """Ensure cities, arenas, and profiles exist. Existing rows are left as-is."""
    city_ids: dict[str, int] = {}
    for cid, name in session.execute(text("SELECT id, name FROM cities")).fetchall():
        city_ids[name] = cid

    for city in cities:
        if city.name in city_ids:
            continue
        result = session.execute(
            text(
                "INSERT INTO cities (name, sort_order, country, price_group) "
                "VALUES (:name, :ord, :country, :price_group) RETURNING id"
            ),
            {
                "name": city.name,
                "ord": city.sort_order,
                "country": city.country,
                "price_group": city.price_group,
            },
        )
        city_ids[city.name] = result.scalar_one()
        if verbose:
            print(f"city created: {city.name} -> id={city_ids[city.name]}")

    for arena in arenas:
        city_id = city_ids[arena.city_name]
        existing = session.execute(
            text("SELECT id FROM arenas WHERE id = :aid"),
            {"aid": arena.arena_id},
        ).scalar_one_or_none()
        if existing is not None:
            if verbose:
                print(f"arena {arena.arena_id} already exists, skipping arena insert")
        else:
            session.execute(
                text(
                    "INSERT INTO arenas (id, city_id, name, address, latitude, longitude, "
                    "is_active, is_confirmed) "
                    "VALUES (:id, :city_id, :name, :address, :lat, :lon, true, true)"
                ),
                {
                    "id": arena.arena_id,
                    "city_id": city_id,
                    "name": arena.name,
                    "address": arena.address,
                    "lat": arena.latitude,
                    "lon": arena.longitude,
                },
            )
            if verbose:
                print(f"arena created: id={arena.arena_id} {arena.city_name} — {arena.name}")

        profile_exists = session.execute(
            text("SELECT 1 FROM arena_profiles WHERE arena_id = :aid"),
            {"aid": arena.arena_id},
        ).scalar_one_or_none()
        if profile_exists is not None:
            if verbose:
                print(f"arena_profile {arena.arena_id} already exists, skipping")
            continue
        session.execute(
            text(
                "INSERT INTO arena_profiles (arena_id, city_id, slug, district, timezone, "
                "status, amenities, social_urls) "
                "VALUES (:aid, :city_id, :slug, :district, :tz, 'published', "
                "'{}'::jsonb, '{}'::jsonb)"
            ),
            {
                "aid": arena.arena_id,
                "city_id": city_id,
                "slug": arena.slug,
                "district": arena.city_name,
                "tz": arena.timezone,
            },
        )
        if verbose:
            print(f"arena_profile created: arena_id={arena.arena_id} slug={arena.slug}")

    session.execute(
        text("SELECT setval(pg_get_serial_sequence('arenas', 'id'), " "GREATEST((SELECT MAX(id) FROM arenas), 1))")
    )
