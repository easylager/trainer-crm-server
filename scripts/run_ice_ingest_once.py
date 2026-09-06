"""One-shot ice ingest: run due ice_parser_jobs against a local DB only.

Makes enabled Minsk MK jobs due, then IceIngestScheduler.run_due(now).
Never writes to cloud/prod databases.

Usage:
  PYTHONPATH=. python scripts/run_ice_ingest_once.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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

MINSK_MK_PARSER_KEYS = frozenset(
    {
        "minskarena_saleframe_v1",
        "zamok_html_v1",
        "chizhovka_html_v1",
        "ledby_html_v1",
        "diamond_html_v1",
    }
)


class ProdDatabaseError(RuntimeError):
    """Refuses writes against a non-local / production-looking URL."""


def _database_url() -> str:
    return Settings().database_url


def _assert_local_database(url: str, *, apply: bool = True) -> None:
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
    url = _database_url()
    _assert_local_database(url, apply=True)
    asyncio.run(_run_once())


if __name__ == "__main__":
    main()
