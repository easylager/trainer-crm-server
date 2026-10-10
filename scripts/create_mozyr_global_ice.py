"""TASK-205: idempotent Mozyr Global ICE — city, arena (sequence id), weekly_grid_v1 job.

Does not touch other cities, arenas, or parser jobs. Default dry-run.

Usage:
  PYTHONPATH=. python scripts/create_mozyr_global_ice.py
  PYTHONPATH=. python scripts/create_mozyr_global_ice.py --apply
  PYTHONPATH=. python scripts/create_mozyr_global_ice.py --apply --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.ingestion.seed_config_mozyr_global_ice import (
    MOZYR_GLOBAL_ICE_CONFIG,
    PARSER_KEY_WEEKLY_GRID_V1,
)
from src.shared.config import Settings
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    warn_prod_ack,
)

CITY_NAME = "Мозырь"
CITY_SORT_ORDER = 33
SLUG = "mozyr-global-ice"
ARENA_NAME = "Global ICE"
ARENA_ADDRESS = "бульвар Дружбы, 11А"
ARENA_LAT = 52.0309001
ARENA_LON = 29.2427777
PROFILE_TIMEZONE = "Europe/Minsk"
JOB_CADENCE = "daily"


@dataclass(frozen=True)
class MozyrProvisionResult:
    city_id: int
    arena_id: int
    job_id: int | None
    created_city: bool
    created_arena: bool
    created_profile: bool
    created_job: bool
    updated_job: bool


def _database_url() -> str:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    return url


def _find_city_id(session: Session) -> int | None:
    row = session.execute(
        text("SELECT id FROM cities WHERE name = :name AND country = 'BY' LIMIT 1"),
        {"name": CITY_NAME},
    ).fetchone()
    return int(row[0]) if row else None


def _find_arena_id(session: Session, city_id: int) -> int | None:
    row = session.execute(
        text(
            """
            SELECT p.arena_id
            FROM arena_profiles p
            JOIN arenas a ON a.id = p.arena_id
            WHERE a.city_id = :city_id AND p.slug = :slug
            LIMIT 1
            """
        ),
        {"city_id": city_id, "slug": SLUG},
    ).fetchone()
    return int(row[0]) if row else None


def apply_mozyr_global_ice(session: Session) -> MozyrProvisionResult:
    """Create or update Mozyr Global ICE rows. Caller commits."""
    created_city = created_arena = created_profile = created_job = False
    updated_job = False
    job_id: int | None = None

    city_id = _find_city_id(session)
    if city_id is None:
        city_id = int(
            session.execute(
                text(
                    "INSERT INTO cities (name, sort_order, country, price_group) "
                    "VALUES (:name, :ord, 'BY', 'BY_BASE') RETURNING id"
                ),
                {"name": CITY_NAME, "ord": CITY_SORT_ORDER},
            ).scalar_one()
        )
        created_city = True

    arena_id = _find_arena_id(session, city_id)
    if arena_id is None:
        arena_id = int(
            session.execute(
                text(
                    """
                    INSERT INTO arenas (city_id, name, address, latitude, longitude,
                                        is_active, is_confirmed)
                    VALUES (:city_id, :name, :address, :lat, :lon, true, true)
                    RETURNING id
                    """
                ),
                {
                    "city_id": city_id,
                    "name": ARENA_NAME,
                    "address": ARENA_ADDRESS,
                    "lat": ARENA_LAT,
                    "lon": ARENA_LON,
                },
            ).scalar_one()
        )
        created_arena = True
        session.execute(
            text(
                """
                INSERT INTO arena_profiles (arena_id, city_id, slug, district, timezone,
                                            status, amenities, social_urls)
                VALUES (:aid, :city_id, :slug, :district, :tz, 'published',
                        '{}'::jsonb, '{}'::jsonb)
                """
            ),
            {
                "aid": arena_id,
                "city_id": city_id,
                "slug": SLUG,
                "district": CITY_NAME,
                "tz": PROFILE_TIMEZONE,
            },
        )
        created_profile = True
    else:
        session.execute(
            text(
                """
                UPDATE arena_profiles
                SET timezone = :tz
                WHERE arena_id = :aid AND slug = :slug
                """
            ),
            {"aid": arena_id, "slug": SLUG, "tz": PROFILE_TIMEZONE},
        )

    config_json = json.dumps(MOZYR_GLOBAL_ICE_CONFIG, ensure_ascii=False)
    now = datetime.now(timezone.utc)
    job_row = session.execute(
        text(
            """
            SELECT id, parser_key FROM ice_parser_jobs
            WHERE arena_id = :aid AND parser_key = :parser_key
            """
        ),
        {"aid": arena_id, "parser_key": PARSER_KEY_WEEKLY_GRID_V1},
    ).fetchone()
    if job_row is None:
        other = session.execute(
            text("SELECT id, parser_key FROM ice_parser_jobs WHERE arena_id = :aid"),
            {"aid": arena_id},
        ).fetchone()
        if other is not None:
            raise SystemExit(
                f"arena_id={arena_id} already has ice_parser_jobs id={other[0]} "
                f"parser_key={other[1]} — refusing to replace"
            )
        job_id = int(
            session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs (
                        arena_id, parser_key, is_enabled, cadence, next_run_at, config, notes
                    ) VALUES (
                        :arena_id, :parser_key, true, :cadence, :next_run_at,
                        CAST(:config AS jsonb), :notes
                    )
                    RETURNING id
                    """
                ),
                {
                    "arena_id": arena_id,
                    "parser_key": PARSER_KEY_WEEKLY_GRID_V1,
                    "cadence": JOB_CADENCE,
                    "next_run_at": now,
                    "config": config_json,
                    "notes": "TASK-205: Mozyr Global ICE projected grid",
                },
            ).scalar_one()
        )
        created_job = True
    else:
        job_id = int(job_row[0])
        session.execute(
            text(
                """
                UPDATE ice_parser_jobs
                SET is_enabled = true,
                    cadence = :cadence,
                    config = CAST(:config AS jsonb),
                    notes = :notes
                WHERE id = :id AND parser_key = :parser_key
                """
            ),
            {
                "id": job_id,
                "parser_key": PARSER_KEY_WEEKLY_GRID_V1,
                "cadence": JOB_CADENCE,
                "config": config_json,
                "notes": "TASK-205: Mozyr Global ICE projected grid",
            },
        )
        updated_job = True

    return MozyrProvisionResult(
        city_id=city_id,
        arena_id=arena_id,
        job_id=job_id,
        created_city=created_city,
        created_arena=created_arena,
        created_profile=created_profile,
        created_job=created_job,
        updated_job=updated_job,
    )


def provision(*, apply: bool, allow_prod: bool = False) -> MozyrProvisionResult:
    url = _database_url()
    assert_database_url(url, apply=apply, allow_prod=allow_prod)
    if allow_prod:
        warn_prod_ack()

    if not apply:
        print("Dry-run: would ensure city, arena+profile, ice_parser_jobs row for Mozyr Global ICE.")
        print(f"  city: {CITY_NAME} (BY)")
        print(f"  arena: {ARENA_NAME}, slug={SLUG}")
        print(f"  parser: {PARSER_KEY_WEEKLY_GRID_V1}, cadence={JOB_CADENCE}")
        return MozyrProvisionResult(
            city_id=0,
            arena_id=0,
            job_id=None,
            created_city=False,
            created_arena=False,
            created_profile=False,
            created_job=False,
            updated_job=False,
        )

    engine = create_engine(url)
    with Session(engine) as session:
        result = apply_mozyr_global_ice(session)
        session.commit()
    print(f"Result: city_id={result.city_id} arena_id={result.arena_id} job_id={result.job_id}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    provision(apply=args.apply, allow_prod=args.i_know_this_is_prod)


if __name__ == "__main__":
    main()
