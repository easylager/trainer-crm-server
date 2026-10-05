"""Ice ingest alarm loops. Run inside notification_service, never inside uvicorn."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

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
# TASK-146: алерты по конкретной арене — отдельным циклом, а не внутри тика
# планировщика: если планировщик завис или падает, устаревание всё равно заметим.
ICE_SOURCE_ALERT_INTERVAL_SEC = 120
# TASK-176: сторож «прогонов нет вообще» — тоже отдельным циклом, независимо от планировщика.
ICE_SCHEDULER_WATCHDOG_INTERVAL_SEC = 300


@dataclass(frozen=True)
class IceIngestTickResult:
    acquired: bool
    due: int = 0
    ran: int = 0
    ok: int = 0


async def run_ice_ingest_tick() -> IceIngestTickResult:
    """Один тик планировщика под общим advisory-локом."""
    # Импорты здесь, а не в начале цикла: ошибка импорта — это сбой тика (в лог, цикл жив),
    # а не тихая смерть задачи (TASK-176).
    from src.infrastructure.db.session import async_session_factory, engine
    from src.ingestion.publish import SqlAlchemyIceSessionPublisher
    from src.ingestion.scheduler_lock import run_with_ice_ingest_lock
    from src.ingestion.types import RUN_STATUS_OK
    from src.shared.config import get_settings

    async def run_tick() -> tuple[int, list]:
        async with async_session_factory() as session:
            scheduler = IceIngestScheduler(
                store=SqlAlchemyParserJobStore(session),
                recorder=SqlAlchemyScrapeRunRecorder(session),
                registry=default_registry(),
                publisher=SqlAlchemyIceSessionPublisher(session),
                by_egress_proxy_url=get_settings().by_egress_proxy_url,
                checkpoint=session.commit,
            )
            outcomes = await scheduler.run_due(datetime.now(timezone.utc))
            await session.commit()
            return scheduler.last_due_count, outcomes

    acquired, payload = await run_with_ice_ingest_lock(engine, run_tick)
    if not acquired or payload is None:
        return IceIngestTickResult(acquired=False)
    due, outcomes = payload
    return IceIngestTickResult(
        acquired=True,
        due=due,
        ran=len(outcomes),
        ok=sum(1 for record in outcomes if record.status == RUN_STATUS_OK),
    )


def _service_is_stopping() -> bool:
    """Отмену запросили снаружи (остановка сервиса), а не прилетел чужой CancelledError изнутри тика."""
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


async def run_ice_ingest_scheduler_loop(
    *,
    tick: Callable[[], Awaitable[IceIngestTickResult]] | None = None,
    interval_sec: float | None = None,
) -> None:
    """Poll ice_parser_jobs.next_run_at and run due strategies.

    TASK-176: строка heartbeat на каждый тик (включая пустые и пропущенные), и цикл
    не выходит молча — CancelledError пробрасывается только при остановке сервиса.
    ``tick`` / ``interval_sec`` — для тестов.
    """
    run_tick = tick or run_ice_ingest_tick
    interval = ICE_INGEST_LOOP_INTERVAL_SEC if interval_sec is None else interval_sec
    logger.info("ice ingest scheduler loop started; tick every %ss", interval)

    while True:
        await asyncio.sleep(interval)
        started = time.monotonic()
        result: IceIngestTickResult | None = None
        error: str | None = None
        try:
            result = await run_tick()
        except asyncio.CancelledError:
            if _service_is_stopping():
                logger.info("ice ingest scheduler loop stopped (service shutdown)")
                raise
            error = "CancelledError"
            logger.error(
                "ice ingest tick raised CancelledError while the service is running; loop continues",
                exc_info=True,
            )
        except Exception as exc:  # noqa: BLE001 — один тик не должен убить цикл
            error = type(exc).__name__
            logger.exception("ice ingest scheduler tick failed")
        duration = time.monotonic() - started
        if result is None:
            logger.info("ice ingest tick failed error=%s duration=%.1fs", error, duration)
        elif not result.acquired:
            logger.info(
                "ice ingest tick acquired=no (another runner owns the scheduler lock) duration=%.1fs",
                duration,
            )
        else:
            logger.info(
                "ice ingest tick acquired=yes due=%s ran=%s ok=%s duration=%.1fs",
                result.due,
                result.ran,
                result.ok,
                duration,
            )


async def run_ice_scheduler_watchdog_loop() -> None:
    """Каждые 5 минут: «планировщик не делает прогонов» → 🔴 в админ-бот, ✅ при восстановлении (TASK-176)."""
    from src.infrastructure.db import async_session_factory
    from src.ingestion.scheduler_watchdog import tick_scheduler_watchdog

    while True:
        await asyncio.sleep(ICE_SCHEDULER_WATCHDOG_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                kind = await tick_scheduler_watchdog(session, now=datetime.now(timezone.utc))
                await session.commit()
                if kind:
                    logger.info("ice scheduler watchdog sent: %s", kind)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("ice scheduler watchdog tick failed")


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


async def run_ice_source_alert_loop() -> None:
    """Каждые 2 минуты: пуш в админ-бот по арене, чей парсер сломался/устарел, и «восстановлено»."""
    from src.infrastructure.db import async_session_factory
    from src.ingestion.source_alerts import tick_source_failure_alerts

    while True:
        await asyncio.sleep(ICE_SOURCE_ALERT_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                alerts = await tick_source_failure_alerts(session, now=datetime.now(timezone.utc))
                await session.commit()
                if alerts:
                    logger.info("ice source alerts sent: %s", len(alerts))
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("ice source alert tick failed")


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
