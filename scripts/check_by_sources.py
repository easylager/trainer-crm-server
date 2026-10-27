"""Do the parsers that need a Belarusian IP actually work from THIS computer?

Read-only: reads job configs from the database, runs each parser's ``extract`` and the normalizer,
prints how many sessions came out. Nothing is written. Run it on a computer with a Belarusian IP
(VPN off), with Railway env for the database URL:

  bash scripts/run_ice_ingest_prod_local.sh scripts/check_by_sources.py --i-know-this-is-prod

Default arenas: every job whose config says ``requires_by_egress`` plus the ones that time out from
the server (Минск Арена 2, Конькобежный 115, Солигорск 19, Горки 32, Бобруйск 38). Override with ``--arena 2 32``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    assert_railway_target_database,
    warn_prod_ack,
)

TIMEOUT_ARENAS = (2, 115, 19, 32, 38)


def _my_ip() -> str:
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=10) as r:  # noqa: S310 — fixed https URL
            info = json.load(r)
        return f"{info.get('ip')} · {info.get('country')} · {info.get('city')} · {info.get('org')}"
    except Exception as exc:  # noqa: BLE001
        return f"не удалось определить ({exc})"


async def _run(arenas: list[int] | None) -> int:
    from sqlalchemy import text

    from src.infrastructure.db.session import async_session_factory
    from src.ingestion.jobs import job_from_row
    from src.ingestion.normalize import IceSessionNormalizer
    from src.ingestion.parsers import default_registry

    print(f"Мой IP: {_my_ip()}")
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT j.id, j.arena_id, j.parser_key, j.is_enabled, j.cadence, j.next_run_at, j.last_run_at,
                           j.config, j.notes, j.last_ok_at, j.last_ok_slot_count, j.failing_since, j.failure_streak,
                           j.last_error_code, j.last_error_summary, j.alert_state, j.alert_sent_at,
                           ap.timezone AS arena_timezone, a.name
                    FROM ice_parser_jobs j
                    JOIN arenas a ON a.id = j.arena_id
                    LEFT JOIN arena_profiles ap ON ap.arena_id = j.arena_id
                    WHERE j.is_enabled ORDER BY j.arena_id
                    """
                )
            )
        ).all()
    registry, normalizer, now = default_registry(), IceSessionNormalizer(), datetime.now(timezone.utc)
    failures = 0
    for row in rows:
        config = row.config if isinstance(row.config, dict) else {}
        wanted = row.arena_id in arenas if arenas else (bool(config.get("requires_by_egress")) or row.arena_id in TIMEOUT_ARENAS)
        if not wanted:
            continue
        parser = registry.get(row.parser_key)
        label = f"{row.arena_id:>4} {row.name[:30]:30} {row.parser_key}"
        if parser is None:
            print(f"{label}: нет парсера в реестре")
            continue
        job = job_from_row(row)
        try:
            extraction = await asyncio.wait_for(parser.extract(job), timeout=60)
            drafts = normalizer.normalize(extraction, job, now=now)
            print(f"{label}: OK, из источника {len(extraction.slots)}, будущих сеансов {len(drafts)}")
        except Exception as exc:  # noqa: BLE001 — the point is to show the failure
            failures += 1
            print(f"{label}: НЕ РАБОТАЕТ — {type(exc).__name__}: {str(exc)[:140]}")
    print(f"\nНе сработало: {failures}")
    return failures


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arena", type=int, nargs="*")
    add_i_know_this_is_prod_argument(ap)
    args = ap.parse_args()
    from src.shared.config import Settings

    url = Settings().database_url
    assert_database_url(url, apply=False, allow_prod=args.i_know_this_is_prod)
    if args.i_know_this_is_prod:
        warn_prod_ack()
    sys.exit(1 if asyncio.run(_run(args.arena)) else 0)


if __name__ == "__main__":
    main()
