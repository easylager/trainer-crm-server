"""manual_schedule_v1: ничего не ищет, но стоит в реестре — каток «на наблюдении»."""

from __future__ import annotations

import pytest

from src.ingestion.manual_schedule_v1 import PARSER_KEY_MANUAL_SCHEDULE, ManualScheduleParser
from src.ingestion.parsers import default_registry
from src.ingestion.types import ParserJob


@pytest.mark.asyncio
async def test_manual_schedule_returns_no_slots_and_is_registered() -> None:
    job = ParserJob(
        id=1,
        arena_id=26,
        parser_key=PARSER_KEY_MANUAL_SCHEDULE,
        is_enabled=True,
        cadence="weekly",
        next_run_at=None,
        last_run_at=None,
        config={"timezone": "Europe/Minsk", "kind": "public_skate"},
    )
    extraction = await ManualScheduleParser().extract(job)
    assert extraction.slots == []
    assert extraction.arena_id == 26
    assert default_registry().get(PARSER_KEY_MANUAL_SCHEDULE) is not None
