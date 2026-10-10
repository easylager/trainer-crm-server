"""Minsk, Moscow, and St. Petersburg arenas with the slugs parser jobs bind on.

Rows live in ``src.ingestion.capital_arenas.ARENAS``. A fresh database has none of
these profiles, so ``build_minsk_job_seeds()`` cannot resolve (city, slug) until this
seed (or an equivalent load) has run.

Default is dry-run. ``--apply`` writes to a local test/dev DB.
Cloud/Railway requires ``--apply --i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/seed_capital_arenas.py
  PYTHONPATH=. python scripts/seed_capital_arenas.py --apply
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

from src.ingestion.capital_arenas import ARENAS, CAPITAL_CITIES, apply_capital_arenas  # noqa: E402
from src.shared.config import Settings  # noqa: E402
from src.shared.ops_db_guard import (  # noqa: E402
    add_i_know_this_is_prod_argument,
    assert_database_url,
    warn_prod_ack,
)


def _database_url() -> str:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    return url


def _print_plan() -> None:
    print(f"Cities to ensure: {len(CAPITAL_CITIES)}")
    print(f"Arenas to ensure: {len(ARENAS)}")
    for arena in ARENAS:
        print(
            f"  arena_id={arena.arena_id:>3} {arena.city_name} — {arena.name} "
            f"(slug={arena.slug}, parser={arena.parser_key})"
        )


def run(*, apply: bool, allow_prod: bool = False) -> None:
    url = _database_url()
    assert_database_url(url, apply=apply, allow_prod=allow_prod)
    if allow_prod:
        warn_prod_ack()
    if not apply:
        _print_plan()
        print("\nDry-run only. Re-run with --apply to write.")
        return

    engine = create_engine(url)
    with Session(engine) as session:
        apply_capital_arenas(session)
        session.commit()
    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    run(apply=args.apply, allow_prod=args.i_know_this_is_prod)


if __name__ == "__main__":
    main()
