"""Seed ice_parser_jobs for the 17 regional (non-Minsk) BY rinks with a live MK source.

Configs come straight from src/ingestion/seed_config_regional_batch_{a,b,c,d}.py
(written by the batch subagents against real live URLs, verified 2026-09-07).
One row per arena_id, upserted via the same idempotent helper TASK-065 uses for
Minsk (src.ingestion.seed_jobs.upsert_ice_parser_jobs).

Default is dry-run. ``--apply`` writes to a local test/dev DB.
Cloud/Railway requires ``--apply --i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/seed_regional_ice_parser_jobs.py
  PYTHONPATH=. python scripts/seed_regional_ice_parser_jobs.py --apply
  PYTHONPATH=. python scripts/seed_regional_ice_parser_jobs.py --apply --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ingestion.seed_jobs import JobSeed, upsert_ice_parser_jobs
from src.shared.config import Settings
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    warn_prod_ack,
)


def _assert_local_database(url: str, *, apply: bool, allow_prod: bool = False) -> None:
    assert_database_url(url, apply=apply, allow_prod=allow_prod)


def build_regional_job_seeds() -> list[JobSeed]:
    from src.ingestion.seed_config_regional_batch_a import (
        BARANOVICHI_LDS_CONFIG,
        BREST_LDS_CONFIG,
        KOBRIN_LDS_CONFIG,
        PARSER_KEY_BARANOVICHI_LDS,
        PARSER_KEY_BREST_LDS,
        PARSER_KEY_KOBRIN_LDS,
        PARSER_KEY_PINSK_VOLNA,
        PINSK_VOLNA_CONFIG,
    )
    from src.ingestion.seed_config_regional_batch_b import (
        GRODNO_NEMAN_CONFIG,
        GRODNO_TRINITI_CONFIG,
        LIDA_LDS_CONFIG,
        NOVOPOLOTSK_LDS_CONFIG,
        PARSER_KEY_GRODNO_NEMAN,
        PARSER_KEY_GRODNO_TRINITI,
        PARSER_KEY_LIDA_LDS,
        PARSER_KEY_NOVOPOLOTSK_LDS,
    )
    from src.ingestion.seed_config_regional_batch_c import (
        GORKI_LDS_CONFIG,
        MOGILEV_DS_CONFIG,
        ORSHA_ARENA_CONFIG,
        OSTROVETS_LDS_CONFIG,
        PARSER_KEY_GORKI_LDS,
        PARSER_KEY_MOGILEV_DS,
        PARSER_KEY_ORSHA_ARENA,
        PARSER_KEY_OSTROVETS_LDS,
        PARSER_KEY_VITEBSK_DS,
        VITEBSK_DS_CONFIG,
    )
    from src.ingestion.seed_config_regional_batch_d import (
        BOBRUISK_ARENA_CONFIG,
        GOMEL_LDS_CONFIG,
        PARSER_KEY_BOBRUISK_ARENA,
        PARSER_KEY_GOMEL_LDS,
        PARSER_KEY_SHKLOV_ARENA,
        PARSER_KEY_SOLIGORSK_SZK,
        SHKLOV_ARENA_CONFIG,
        SOLIGORSK_SZK_CONFIG,
    )

    # (arena_id, parser_key, config, cadence)
    rows: list[tuple[int, str, dict, str]] = [
        (22, PARSER_KEY_BREST_LDS, BREST_LDS_CONFIG, "daily"),
        (23, PARSER_KEY_BARANOVICHI_LDS, BARANOVICHI_LDS_CONFIG, "daily"),
        (25, PARSER_KEY_KOBRIN_LDS, KOBRIN_LDS_CONFIG, "daily"),
        (24, PARSER_KEY_PINSK_VOLNA, PINSK_VOLNA_CONFIG, "daily"),
        (10, PARSER_KEY_GRODNO_TRINITI, GRODNO_TRINITI_CONFIG, "daily"),
        (11, PARSER_KEY_GRODNO_NEMAN, GRODNO_NEMAN_CONFIG, "daily"),
        (37, PARSER_KEY_LIDA_LDS, LIDA_LDS_CONFIG, "daily"),
        (30, PARSER_KEY_NOVOPOLOTSK_LDS, NOVOPOLOTSK_LDS_CONFIG, "daily"),
        (29, PARSER_KEY_VITEBSK_DS, VITEBSK_DS_CONFIG, "daily"),
        (43, PARSER_KEY_MOGILEV_DS, MOGILEV_DS_CONFIG, "daily"),
        (31, PARSER_KEY_ORSHA_ARENA, ORSHA_ARENA_CONFIG, "daily"),
        (32, PARSER_KEY_GORKI_LDS, GORKI_LDS_CONFIG, "daily"),
        (41, PARSER_KEY_OSTROVETS_LDS, OSTROVETS_LDS_CONFIG, "daily"),
        (38, PARSER_KEY_BOBRUISK_ARENA, BOBRUISK_ARENA_CONFIG, "daily"),
        (19, PARSER_KEY_SOLIGORSK_SZK, SOLIGORSK_SZK_CONFIG, "daily"),
        (42, PARSER_KEY_SHKLOV_ARENA, SHKLOV_ARENA_CONFIG, "daily"),
        (33, PARSER_KEY_GOMEL_LDS, GOMEL_LDS_CONFIG, "daily"),
    ]
    return [
        JobSeed(
            arena_id=arena_id,
            parser_key=parser_key,
            cadence=cadence,
            is_enabled=True,
            config=config,
            notes=f"regional seed: {parser_key}",
        )
        for arena_id, parser_key, config, cadence in rows
    ]


def _database_url() -> str:
    return Settings().database_url


def _print_seeds(seeds: list[JobSeed]) -> None:
    print(f"Regional ice_parser_jobs seed: {len(seeds)} job(s)")
    for seed in seeds:
        url = seed.config.get("url") or seed.config.get("schedule_url") or seed.config.get("prices_url") or ""
        print(f"  arena_id={seed.arena_id:>3} {seed.parser_key:<24} {seed.cadence} {url}")


async def _apply(seeds: list[JobSeed]) -> None:
    from src.infrastructure.db import async_session_factory

    async with async_session_factory() as session:
        report = await upsert_ice_parser_jobs(session, seeds)
        await session.commit()
    print(f"inserted={report.inserted} updated={report.updated} skipped_missing_arena={report.skipped_missing_arena}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()

    url = _database_url()
    _assert_local_database(url, apply=args.apply, allow_prod=args.i_know_this_is_prod)
    if args.i_know_this_is_prod:
        warn_prod_ack()
    seeds = build_regional_job_seeds()
    if not args.apply:
        _print_seeds(seeds)
        print("\nDry-run only. Re-run with --apply to write.")
        return
    asyncio.run(_apply(seeds))


if __name__ == "__main__":
    main()
