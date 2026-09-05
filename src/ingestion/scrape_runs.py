"""Scrape-run persistence seam. TASK-072 owns ice_scrape_runs; this TASK records outcomes."""
from __future__ import annotations

import logging
from typing import Protocol

from src.ingestion.types import ScrapeRunRecord

logger = logging.getLogger(__name__)


class IceScrapeRunRecorder(Protocol):
    async def record(self, run: ScrapeRunRecord) -> None:
        """Persist or log a parser attempt. Must not write ice_sessions."""


class InMemoryScrapeRunRecorder:
    def __init__(self) -> None:
        self.runs: list[ScrapeRunRecord] = []

    async def record(self, run: ScrapeRunRecord) -> None:
        self.runs.append(run)


class LoggingScrapeRunRecorder:
    """Stub until ice_scrape_runs exists. Always records the outcome of a tick."""

    async def record(self, run: ScrapeRunRecord) -> None:
        logger.info(
            "ice_scrape_run stub job_id=%s arena_id=%s parser_key=%s status=%s slots=%s dropped=%s error=%s",
            run.job_id,
            run.arena_id,
            run.parser_key,
            run.status,
            run.slot_count,
            run.slots_dropped,
            run.error_message,
        )
