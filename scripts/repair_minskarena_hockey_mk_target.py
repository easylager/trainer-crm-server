"""Move ABWS service/55 (hockey-rink MK) off arena_id=2 onto Конькобежный стадион (115).

Service/55 init.object = «Конькобежный стадион»; main «Арена» MK is service/62 on arena 2.

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
                    WHERE parser_key IN (:hockey, :main)
                    ORDER BY parser_key
                    """
                ),
                {"hockey": HOCKEY_PARSER, "main": MAIN_PARSER},
            )
        ).mappings().all()
        print("parser jobs:", [dict(r) for r in jobs])

        misplaced = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM ice_sessions
                    WHERE arena_id = :main_id
                      AND (session_label ILIKE :lbl OR kind = 'public_skate')
                    """
                ),
                {"main_id": MAIN_ARENA_ID, "lbl": HOCKEY_LABEL},
            )
        ).scalar_one()
        print(f"ice_sessions on arena {MAIN_ARENA_ID} (public_skate or hockey label): {misplaced}")

        if not apply:
            print("dry-run — pass --apply to update jobs and move hockey MK sessions")
            await engine.dispose()
            return

        await session.execute(
            text(
                """
                UPDATE ice_parser_jobs
                SET arena_id = :hockey_aid
                WHERE parser_key = :hockey_key AND arena_id <> :hockey_aid
                """
            ),
            {"hockey_aid": HOCKEY_ARENA_ID, "hockey_key": HOCKEY_PARSER},
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
        print("applied: hockey job → arena 115; hockey-labelled sessions moved")
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
