"""Regional (non-Minsk) BY ice arenas: cities + arenas + arena_profiles skeleton.

Arena rows live in ``src.ingestion.regional_arenas.ARENAS`` (shared with the parser-job seed).
Source of facts: the prod census (names, addresses, coordinates only). This script writes
to local dev/test Postgres after ``--apply``. Cloud/Railway needs ``--apply --i-know-this-is-prod``.

Arena ids match the prod census and the parser specs. Default is dry-run.

Usage:
  PYTHONPATH=. python scripts/seed_regional_arenas.py
  PYTHONPATH=. python scripts/seed_regional_arenas.py --apply
  PYTHONPATH=. python scripts/seed_regional_arenas.py --apply --i-know-this-is-prod
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.ingestion.regional_arenas import ARENAS, NEW_CITIES, apply_regional_arenas  # noqa: E402
from src.shared.config import Settings  # noqa: E402
from src.shared.ops_db_guard import (  # noqa: E402
    add_i_know_this_is_prod_argument,
    assert_database_url,
    warn_prod_ack,
)


def _assert_local_database(url: str, *, apply: bool, allow_prod: bool = False) -> None:
    assert_database_url(url, apply=apply, allow_prod=allow_prod)


def _database_url() -> str:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    return url


def _print_plan() -> None:
    print(f"Cities to ensure: {len(NEW_CITIES)}")
    ready = sum(1 for arena in ARENAS if arena.has_parser)
    print(f"Arenas to ensure: {len(ARENAS)} (parser-ready: {ready})")
    for arena in ARENAS:
        flag = "parser" if arena.has_parser else "profile-only"
        print(f"  arena_id={arena.arena_id:>3} [{flag:12}] {arena.city_name} — {arena.name} " f"(slug={arena.slug})")


def run(*, apply: bool, allow_prod: bool = False) -> None:
    url = _database_url()
    _assert_local_database(url, apply=apply, allow_prod=allow_prod)
    if allow_prod:
        warn_prod_ack()
    if not apply:
        _print_plan()
        print("\nDry-run only. Re-run with --apply to write.")
        return

    engine = create_engine(url)
    with Session(engine) as session:
        apply_regional_arenas(session)
        session.commit()
    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    run(apply=args.apply, allow_prod=args.i_know_this_is_prod)


if __name__ == "__main__":
    main()
