"""TASK-187: 24:00 end time normalizes to 00:00 local."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob
from src.ingestion.validate import IceSessionValidator

_NOW = datetime(2026, 1, 10, 8, 0, tzinfo=timezone.utc)


def _job() -> ParserJob:
    return ParserJob(
        id=1,
        arena_id=99,
        parser_key="fake",
        is_enabled=True,
        cadence="daily",
        next_run_at=_NOW,
        last_run_at=None,
        config={
            "timezone": "Europe/Minsk",
            "currency_code": "BYN",
            "prices_already_minor": True,
        },
    )


@pytest.mark.asyncio
async def test_2230_to_2400_publishes_as_midnight_end() -> None:
    """AC-4."""
    extraction = Extraction(
        arena_id=99,
        parser_key="fake",
        snapshot="{}",
        slots=[
            ExtractedSlot(
                local_date="2026-01-15",
                starts_at_local="22:30",
                ends_at_local="24:00",
                kind_raw="массовое катание",
                price_adult="10",
            )
        ],
        observed_at=_NOW,
    )
    drafts = IceSessionNormalizer().normalize(extraction, _job(), now=_NOW)
    validated = IceSessionValidator().validate(drafts)
    assert len(validated) == 1
    row = validated[0]
    assert row.starts_at_local.hour == 22 and row.starts_at_local.minute == 30
    assert row.ends_at_local.hour == 0 and row.ends_at_local.minute == 0
    assert row.ends_at_utc > row.starts_at_utc
