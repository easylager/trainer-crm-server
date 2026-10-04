"""Retire standalone hockey MK job (service/55) and move misplaced sessions to arena 115.

Hockey ABWS is ingested inside ``minskarena_speed_oval_v1`` (one row per arena_id).
Prod may still have ``minskarena_saleframe_v1`` on arena 2 from an older seed.

Default dry-run. Prod: ``--apply --i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/repair_minskarena_hockey_mk_target.py
  PYTHONPATH=. python scripts/repair_minskarena_hockey_mk_target.py --apply --i-know-this-is-prod
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
    assert_railway_target_database,
    async_database_url,
    warn_prod_ack,
)

HOCKEY_ARENA_ID = 115
MAIN_ARENA_ID = 2
HOCKEY_PARSER = "minskarena_saleframe_v1"
MAIN_PARSER = "minskarena_main_saleframe_v1"
SPEED_OVAL_PARSER = "minskarena_speed_oval_v1"
HOCKEY_LABEL = "%хоккейн%"


async def run(*, apply: bool) -> None:
    url = async_database_url(Settings().database_url)
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        jobs = (
            await session.execute(
                text(
                    """
                    SELECT id, arena_id, parser_key, is_enabled
                    FROM ice_parser_jobs
                    WHERE parser_key IN (:hockey, :main, :oval)
                    ORDER BY parser_key, arena_id
                    """
                ),
                {"hockey": HOCKEY_PARSER, "main": MAIN_PARSER, "oval": SPEED_OVAL_PARSER},
            )
        ).mappings().all()
        print("parser jobs:", [dict(r) for r in jobs])

        misplaced = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM ice_sessions
                    WHERE arena_id = :main_id
                      AND (session_label ILIKE :lbl OR session_label ILIKE '%хоккейной площадке%')
                    """
                ),
                {"main_id": MAIN_ARENA_ID, "lbl": HOCKEY_LABEL},
            )
        ).scalar_one()
        print(f"ice_sessions on arena {MAIN_ARENA_ID} with hockey label: {misplaced}")

        stale_hockey_jobs = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM ice_parser_jobs
                    WHERE parser_key = :hockey_key
                    """
                ),
                {"hockey_key": HOCKEY_PARSER},
            )
        ).scalar_one()
        print(f"stale {HOCKEY_PARSER} job rows: {stale_hockey_jobs}")

        if not apply:
            print(
                "dry-run — pass --apply to delete stale hockey job rows, "
                "move hockey-labelled sessions to 115; then seed for main arena /62"
            )
            await engine.dispose()
            return

        await session.execute(
            text("DELETE FROM ice_parser_jobs WHERE parser_key = :hockey_key"),
            {"hockey_key": HOCKEY_PARSER},
        )
        await session.execute(
            text(
                """
                UPDATE ice_sessions
                SET arena_id = :hockey_aid
                WHERE arena_id = :main_id
                  AND (session_label ILIKE :lbl OR session_label ILIKE '%хоккейной площадке%')
                """
            ),
            {"hockey_aid": HOCKEY_ARENA_ID, "main_id": MAIN_ARENA_ID, "lbl": HOCKEY_LABEL},
        )
        await session.commit()
        print(
            f"applied: removed {HOCKEY_PARSER} jobs; hockey-labelled sessions → arena {HOCKEY_ARENA_ID}. "
            f"Run seed_ice_parser_jobs for {MAIN_PARSER} on arena {MAIN_ARENA_ID}."
        )
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    url = Settings().database_url
    assert_database_url(url, apply=args.apply, allow_prod=args.i_know_this_is_prod)
    if args.i_know_this_is_prod:
        assert_railway_target_database(url)
        warn_prod_ack()
    asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    main()
