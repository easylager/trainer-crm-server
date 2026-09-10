"""One-shot ice ingest: make due MK jobs and run IceIngestScheduler once.

Makes enabled Minsk + regional BY MK jobs due, then IceIngestScheduler.run_due(now).
Default: local DB only. Cloud/Railway: ``--i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/run_ice_ingest_once.py
  PYTHONPATH=. python scripts/run_ice_ingest_once.py --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shared.config import Settings
from src.shared.ops_db_guard import (
    ProdDatabaseError,
    add_i_know_this_is_prod_argument,
    assert_database_url,
    warn_prod_ack,
)

MINSK_MK_PARSER_KEYS = frozenset(
    {
        "minskarena_saleframe_v1",
        "zamok_html_v1",
        "chizhovka_html_v1",
        "brest_lds_v1",
        "baranovichi_lds_v1",
        "kobrin_lds_v1",
        "pinsk_volna_v1",
        "grodno_triniti_v1",
        "grodno_neman_v1",
        "lida_lds_v1",
        "novopolotsk_lds_v1",
        "vitebsk_ds_v1",
        "mogilev_ds_v1",
        "orsha_arena_v1",
        "gorki_lds_v1",
        "ostrovets_lds_v1",
        "bobruisk_arena_v1",
        "soligorsk_szk_v1",
        "shklov_arena_v1",
        "gomel_lds_v1",
        "ledby_html_v1",
        "diamond_html_v1",
        "minskarena_speed_oval_v1",
    }
)


def _database_url() -> str:
    return Settings().database_url


def _assert_local_database(url: str, *, apply: bool = True, allow_prod: bool = False) -> None:
    assert_database_url(url, apply=apply, allow_prod=allow_prod)


async def _run_once() -> None:
    from sqlalchemy import text

    from src.infrastructure.db import async_session_factory
    from src.ingestion.jobs import SqlAlchemyParserJobStore
    from src.ingestion.parsers import default_registry
    from src.ingestion.publish import SqlAlchemyIceSessionPublisher
    from src.ingestion.scheduler import IceIngestScheduler
    from src.ingestion.scrape_runs import SqlAlchemyScrapeRunRecorder
    from src.ingestion.types import RUN_STATUS_OK

    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        keys = sorted(MINSK_MK_PARSER_KEYS)
        placeholders = ", ".join(f":key_{i}" for i in range(len(keys)))
        params = {"now": now, **{f"key_{i}": key for i, key in enumerate(keys)}}
        await session.execute(
            text(
                f"""
                UPDATE ice_parser_jobs
                SET next_run_at = :now
                WHERE is_enabled = true AND parser_key IN ({placeholders})
                """
            ),
            params,
        )
        scheduler = IceIngestScheduler(
            store=SqlAlchemyParserJobStore(session),
            recorder=SqlAlchemyScrapeRunRecorder(session),
            registry=default_registry(),
            publisher=SqlAlchemyIceSessionPublisher(session),
        )
        outcomes = await scheduler.run_due(now)
        await session.commit()

    if not outcomes:
        print("no due ice_parser_jobs")
        return
    for record in outcomes:
        published = record.slot_count if record.status == RUN_STATUS_OK else 0
        http = record.http_status if record.http_status is not None else "-"
        error = record.error_message or ""
        print(
            f"arena_id={record.arena_id} parser_key={record.parser_key} "
            f"status={record.status} http={http} slots_found={record.slot_count} "
            f"slots_published={published} error={error}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    url = _database_url()
    _assert_local_database(url, apply=True, allow_prod=args.i_know_this_is_prod)
    if args.i_know_this_is_prod:
        warn_prod_ack()
    asyncio.run(_run_once())


if __name__ == "__main__":
    main()
