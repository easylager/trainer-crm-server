"""TASK-065: import Minsk ice_parser_jobs from the parser census.

Default is dry-run. ``--apply`` writes to a local test/dev DB.
Cloud/Railway requires ``--apply --i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/seed_ice_parser_jobs.py
  PYTHONPATH=. python scripts/seed_ice_parser_jobs.py --apply
  PYTHONPATH=. python scripts/seed_ice_parser_jobs.py --apply --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ingestion.seed_jobs import build_minsk_job_seeds, upsert_ice_parser_jobs
from src.shared.config import Settings
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    warn_prod_ack,
)


def _database_url() -> str:
    settings = Settings()
    return settings.database_url


def _assert_local_database(url: str, *, apply: bool, allow_prod: bool = False) -> None:
    assert_database_url(url, apply=apply, allow_prod=allow_prod)


def _print_seeds() -> None:
    seeds = build_minsk_job_seeds()
    enabled = [seed for seed in seeds if seed.is_enabled]
    disabled = [seed for seed in seeds if not seed.is_enabled]
    print(f"Minsk ice_parser_jobs seed: {len(seeds)} job(s), {len(enabled)} enabled, {len(disabled)} disabled")
    for seed in seeds:
        flag = "ON " if seed.is_enabled else "off"
        url = seed.config.get("url") or seed.config.get("schedule_url") or ""
        print(f"  [{flag}] arena_id={seed.arena_id} {seed.parser_key} {seed.cadence} {url}")


async def _apply() -> None:
    from src.infrastructure.db import async_session_factory

    seeds = build_minsk_job_seeds()
    async with async_session_factory() as session:
        report = await upsert_ice_parser_jobs(session, seeds)
        await session.commit()
    print(
        f"applied: inserted={report.inserted} updated={report.updated} "
        f"skipped_missing_arena={report.skipped_missing_arena}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write ice_parser_jobs")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    url = _database_url()
    _assert_local_database(url, apply=args.apply, allow_prod=args.i_know_this_is_prod)
    if args.i_know_this_is_prod:
        warn_prod_ack()
    _print_seeds()
    if not args.apply:
        print("dry-run; pass --apply to write")
        return
    asyncio.run(_apply())


if __name__ == "__main__":
    main()
