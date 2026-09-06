"""Ice ingest alarm loops. Run inside notification_service, never inside uvicorn."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from src.ingestion.alerts import tick_ice_health_alerts, tick_ice_health_weekly_digest
from src.ingestion.jobs import SqlAlchemyParserJobStore
from src.ingestion.parsers import default_registry
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import SqlAlchemyScrapeRunRecorder
from src.ingestion.ttl import purge_ice_scrape_ttl

logger = logging.getLogger(__name__)

ICE_INGEST_LOOP_INTERVAL_SEC = 60
ICE_TTL_LOOP_INTERVAL_SEC = 3600
ICE_HEALTH_ALERT_INTERVAL_SEC = 3600
ICE_HEALTH_DIGEST_INTERVAL_SEC = 3600


async def run_ice_ingest_scheduler_loop() -> None:
    """Poll ice_parser_jobs.next_run_at and run due strategies."""
    from src.infrastructure.db import async_session_factory
    from src.shared.config import get_settings

    while True:
        await asyncio.sleep(ICE_INGEST_LOOP_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                from src.ingestion.publish import SqlAlchemyIceSessionPublisher

                scheduler = IceIngestScheduler(
                    store=SqlAlchemyParserJobStore(session),
                    recorder=SqlAlchemyScrapeRunRecorder(session),
                    registry=default_registry(),
                    publisher=SqlAlchemyIceSessionPublisher(session),
                    by_egress_configured=bool(get_settings().by_egress_proxy_url),
                )
                outcomes = await scheduler.run_due(datetime.now(timezone.utc))
                await session.commit()
                if outcomes:
                    logger.info("ice ingest tick recorded %s run(s)", len(outcomes))
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("ice ingest scheduler tick failed")


async def run_ice_scrape_ttl_loop() -> None:
    """Purge scrape runs older than 90 days (keep last any + last ok) and stale slots."""
    from src.infrastructure.db import async_session_factory

    while True:
        await asyncio.sleep(ICE_TTL_LOOP_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                stats = await purge_ice_scrape_ttl(session, now=datetime.now(timezone.utc))
                await session.commit()
                if stats.runs_deleted or stats.sessions_deleted:
                    logger.info(
                        "ice ttl deleted runs=%s sessions=%s",
                        stats.runs_deleted,
                        stats.sessions_deleted,
                    )
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("ice scrape ttl tick failed")


async def run_ice_health_alert_loop() -> None:
    """Hourly: silent sources (no ok past cadence×N) and stale-fact city threshold."""
    from src.infrastructure.db import async_session_factory

    while True:
        await asyncio.sleep(ICE_HEALTH_ALERT_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                sent = await tick_ice_health_alerts(session, now=datetime.now(timezone.utc))
                await session.commit()
                if sent:
                    logger.info("ice health alert sent")
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("ice health alert tick failed")


async def run_ice_health_weekly_digest_loop() -> None:
    """Sunday admin digest: silent sources, stale share, tier A count next to share."""
    from src.infrastructure.db import async_session_factory

    while True:
        await asyncio.sleep(ICE_HEALTH_DIGEST_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                sent = await tick_ice_health_weekly_digest(session, now=datetime.now(timezone.utc))
                await session.commit()
                if sent:
                    logger.info("ice health weekly digest sent")
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("ice health weekly digest tick failed")
