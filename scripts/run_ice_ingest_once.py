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
    assert_railway_target_database,
    warn_prod_ack,
)

BY_EGRESS_PARSER_KEYS = frozenset(
    {
        "ledlife_origin_html_v1",
    }
)

MINSK_MK_PARSER_KEYS = frozenset(
    {
        "minskarena_main_saleframe_v1",
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
        # RU pilot (Moscow / St. Petersburg) — see data/parsers/{msk,spb}-*.md
        "ldsokolniki_html_v1",
        "ledovyydvorets_html_v1",
        "yubileyny_afisha_html_v1",
        "junost_instagram_caption_v1",
    }
) | BY_EGRESS_PARSER_KEYS


def _database_url() -> str:
    return Settings().database_url


def _assert_local_database(url: str, *, apply: bool = True, allow_prod: bool = False) -> None:
    assert_database_url(url, apply=apply, allow_prod=allow_prod)


async def _run_once() -> None:
    from sqlalchemy import text

    from src.infrastructure.db.session import async_session_factory, engine
    from src.ingestion.jobs import SqlAlchemyParserJobStore
    from src.ingestion.parsers import default_registry
    from src.ingestion.publish import SqlAlchemyIceSessionPublisher
    from src.ingestion.scheduler import IceIngestScheduler
    from src.ingestion.scheduler_lock import run_with_ice_ingest_lock
    from src.ingestion.scrape_runs import SqlAlchemyScrapeRunRecorder
    from src.ingestion.types import RUN_STATUS_OK

    def _scheduler(session, *, max_jobs_per_tick: int | None = 20):
        return IceIngestScheduler(
            store=SqlAlchemyParserJobStore(session),
            recorder=SqlAlchemyScrapeRunRecorder(session),
            registry=default_registry(),
            publisher=SqlAlchemyIceSessionPublisher(session),
            checkpoint=session.commit,
            by_egress_proxy_url=Settings().by_egress_proxy_url,
            max_jobs_per_tick=max_jobs_per_tick,
        )

    async def _bump_keys(session, keys: frozenset[str], *, enable_by: bool = False):
        now = datetime.now(timezone.utc)
        key_list = sorted(keys)
        placeholders = ", ".join(f":key_{i}" for i in range(len(key_list)))
        params = {"now": now, **{f"key_{i}": key for i, key in enumerate(key_list)}}
        if enable_by:
            await session.execute(
                text(
                    f"""
                    UPDATE ice_parser_jobs
                    SET is_enabled = true, next_run_at = :now
                    WHERE parser_key IN ({placeholders})
                    """
                ),
                params,
            )
        else:
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
        return now

    async def run_jobs():
        all_outcomes: list = []
        async with async_session_factory() as session:
            by_list = sorted(BY_EGRESS_PARSER_KEYS)
            by_ph = ", ".join(f":by_{i}" for i in range(len(by_list)))
            found = await session.execute(
                text(
                    f"""
                    SELECT parser_key, arena_id, is_enabled
                    FROM ice_parser_jobs
                    WHERE parser_key IN ({by_ph})
                    """
                ),
                {f"by_{i}": k for i, k in enumerate(by_list)},
            )
            rows = {str(r[0]): r for r in found.fetchall()}
            for key in by_list:
                if key not in rows:
                    print(
                        f"WARNING: no ice_parser_jobs row for parser_key={key} — "
                        f"run: PYTHONPATH=. python scripts/seed_ice_parser_jobs.py --apply "
                        f"(add --i-know-this-is-prod on cloud DB)"
                    )
            # Pass 1: BY-egress (Юность / СДЮШОР) без лимита 20 — иначе junost (job id ~130)
            # не попадает в тик среди десятков региональных парсеров.
            now = await _bump_keys(session, BY_EGRESS_PARSER_KEYS, enable_by=True)
            await session.commit()
            all_outcomes.extend(await _scheduler(session, max_jobs_per_tick=None).run_due(now))
            await session.commit()

            now = await _bump_keys(session, MINSK_MK_PARSER_KEYS)
            await session.commit()
            all_outcomes.extend(await _scheduler(session).run_due(now))
            await session.commit()
            return all_outcomes

    acquired, outcomes = await run_with_ice_ingest_lock(engine, run_jobs)
    if not acquired:
        print("ice ingest scheduler is already running; one-shot run skipped")
        return

    if not outcomes:
        print("no due ice_parser_jobs")
        return
    for record in outcomes:
        published = record.slot_count if record.status == RUN_STATUS_OK else 0
        # TASK-178: extracted — сколько вернул адаптер, published — сколько дошло до витрины.
        extracted = record.slot_count + record.slots_dropped
        http = record.http_status if record.http_status is not None else "-"
        code = record.error_code or ""
        error = record.error_message or ""
        print(
            f"arena_id={record.arena_id} parser_key={record.parser_key} "
            f"status={record.status} http={http} slots_extracted={extracted} "
            f"slots_published={published} code={code} error={error}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    url = _database_url()
    _assert_local_database(url, apply=True, allow_prod=args.i_know_this_is_prod)
    if args.i_know_this_is_prod:
        assert_railway_target_database(url)
        warn_prod_ack()
    asyncio.run(_run_once())


if __name__ == "__main__":
    main()
