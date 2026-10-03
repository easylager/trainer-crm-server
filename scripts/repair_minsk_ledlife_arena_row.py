"""Repair prod arena_id=4: arenas row must be Minsk ledlife, not Gomel «Манеж».

Profile + ice_parser_jobs already target ledlife (data/minsk-arenas-prod.csv id=4).
If ``arenas.city_id`` points at Гомель, slots publish correctly but the Ice catalog
filters by city — users in Минск never see СДЮШОР.

Default dry-run. Prod: ``--apply --i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/repair_minsk_ledlife_arena_row.py
  PYTHONPATH=. python scripts/repair_minsk_ledlife_arena_row.py --apply --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.shared.config import Settings
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    warn_prod_ack,
)

MINSK_CITY_ID = 2
ARENA_ID = 4
NAME = "СДЮШОР по фигурному катанию"
ADDRESS = "Минск, пр-т Каролинский, 5"
LAT = 53.85639
LON = 27.4907
SLUG = "minsk-ledlife"


async def _inspect(session) -> dict:
    row = (
        await session.execute(
            text(
                """
                SELECT a.id, a.name, a.city_id, c.name AS city_name,
                       a.address, a.latitude, a.longitude,
                       p.slug AS profile_slug, p.city_id AS profile_city_id
                FROM arenas a
                JOIN cities c ON c.id = a.city_id
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                WHERE a.id = :aid
                """
            ),
            {"aid": ARENA_ID},
        )
    ).mappings().first()
    return dict(row) if row else {}


async def run(*, apply: bool) -> None:
    url = Settings().database_url
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        before = await _inspect(session)
        if not before:
            raise SystemExit(f"arena_id={ARENA_ID} not found")
        print("before:", before)
        needs = (
            before.get("city_name") != "Минск"
            or before.get("name") != NAME
            or before.get("profile_slug") != SLUG
            or before.get("profile_city_id") != MINSK_CITY_ID
        )
        if not needs:
            print("already aligned with minsk-arenas-prod.csv — nothing to do")
            await engine.dispose()
            return
        if not apply:
            print(
                "would UPDATE arenas + arena_profiles for id=4 "
                "(trainer_arenas/slots on this id are left unchanged — review if Gomel «Манеж» was real)"
            )
            await engine.dispose()
            return
        await session.execute(
            text(
                """
                UPDATE arenas
                SET city_id = :city_id, name = :name, address = :address,
                    latitude = :lat, longitude = :lon
                WHERE id = :aid
                """
            ),
            {
                "aid": ARENA_ID,
                "city_id": MINSK_CITY_ID,
                "name": NAME,
                "address": ADDRESS,
                "lat": LAT,
                "lon": LON,
            },
        )
        await session.execute(
            text(
                """
                UPDATE arena_profiles
                SET city_id = :city_id, slug = :slug
                WHERE arena_id = :aid
                """
            ),
            {"aid": ARENA_ID, "city_id": MINSK_CITY_ID, "slug": SLUG},
        )
        await session.commit()
        after = await _inspect(session)
        print("after:", after)
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    assert_database_url(Settings().database_url, apply=args.apply, allow_prod=args.i_know_this_is_prod)
    if args.apply and args.i_know_this_is_prod:
        warn_prod_ack()
    asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    main()
