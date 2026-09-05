"""Ice ingest alarm loop. Runs inside notification_service, never inside uvicorn."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from src.ingestion.jobs import SqlAlchemyParserJobStore
from src.ingestion.parsers import default_registry
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import LoggingScrapeRunRecorder

logger = logging.getLogger(__name__)

ICE_INGEST_LOOP_INTERVAL_SEC = 60


async def run_ice_ingest_scheduler_loop() -> None:
    """Poll ice_parser_jobs.next_run_at and run due strategies."""
    from src.infrastructure.db import async_session_factory

    while True:
        await asyncio.sleep(ICE_INGEST_LOOP_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                scheduler = IceIngestScheduler(
                    store=SqlAlchemyParserJobStore(session),
                    recorder=LoggingScrapeRunRecorder(),
                    registry=default_registry(),
                )
                outcomes = await scheduler.run_due(datetime.now(timezone.utc))
                await session.commit()
                if outcomes:
                    logger.info("ice ingest tick recorded %s run(s)", len(outcomes))
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("ice ingest scheduler tick failed")
