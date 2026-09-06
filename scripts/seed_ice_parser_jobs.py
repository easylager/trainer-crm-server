"""TASK-065: import Minsk ice_parser_jobs from the parser census.

Default is dry-run. ``--apply`` writes to a local test/dev DB only — never production.

Usage:
  PYTHONPATH=. python scripts/seed_ice_parser_jobs.py
  PYTHONPATH=. python scripts/seed_ice_parser_jobs.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ingestion.seed_jobs import build_minsk_job_seeds, upsert_ice_parser_jobs
from src.shared.config import Settings

LOCAL_DB_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "postgres", "db", "host.docker.internal"}
)
CLOUD_DB_MARKERS = (
    "railway",
    "supabase",
    "neon.tech",
    "amazonaws.com",
    "azure",
    "render.com",
    "onrender.com",
    "planetscale",
    "digitalocean",
    "prod.",
    "production",
)
ALLOWED_APPLY_DB_NAMES = frozenset({"trainer_crm_test", "trainer_crm"})


class ProdDatabaseError(RuntimeError):
    """Refuses writes against a non-local / production-looking URL."""


def _database_url() -> str:
    settings = Settings()
    return settings.database_url


def _assert_local_database(url: str, *, apply: bool) -> None:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    host = (parsed.hostname or "").lower()
    haystack = f"{host} {url.lower()}"
    if any(marker in haystack for marker in CLOUD_DB_MARKERS):
        raise ProdDatabaseError(f"refusing cloud/prod database host {host!r}")
    local_ok = host in LOCAL_DB_HOSTS or (host.startswith("127.") and host.count(".") == 3)
    if not local_ok:
        raise ProdDatabaseError(f"refusing non-local database host {host!r}")
    if not apply:
        return
    dbname = (parsed.path or "").lstrip("/").split("?")[0]
    if dbname not in ALLOWED_APPLY_DB_NAMES:
        raise ProdDatabaseError(f"apply is limited to {sorted(ALLOWED_APPLY_DB_NAMES)}, got {dbname!r}")


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
    parser.add_argument("--apply", action="store_true", help="write ice_parser_jobs (local DB only)")
    args = parser.parse_args()
    url = _database_url()
    _assert_local_database(url, apply=args.apply)
    _print_seeds()
    if not args.apply:
        print("dry-run; pass --apply to write")
        return
    asyncio.run(_apply())


if __name__ == "__main__":
    main()
