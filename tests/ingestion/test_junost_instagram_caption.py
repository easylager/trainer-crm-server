"""Junost Instagram caption parser (manual copy-paste, arena_id=8)."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.ingestion.junost_instagram_caption import (
    JunostInstagramCaptionParser,
    parse_junost_instagram_caption,
)
from src.ingestion.parsers import default_registry
from src.ingestion.types import ParserJob

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / "data/fixtures/minsk-junost"
_CAPTION = (_FIXTURES / "instagram-caption-2026-10-04.txt").read_text(encoding="utf-8")
_NOW = datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc)


def _job(**overrides) -> ParserJob:
    base = ParserJob(
        id=8,
        arena_id=8,
        parser_key=JunostInstagramCaptionParser.parser_key,
        is_enabled=True,
        cadence="weekly",
        next_run_at=_NOW - timedelta(minutes=5),
        last_run_at=None,
        config={
            "caption_file": str(_FIXTURES / "instagram-caption-2026-10-04.txt"),
            "timezone": "Europe/Minsk",
            "kind": "public_skate",
            "requires_by_egress": False,
            "pivot_year": 2026,
        },
    )
    return replace(base, **overrides) if overrides else base


def test_registered_in_default_registry() -> None:
    parser = default_registry().get("junost_instagram_caption_v1")
    assert isinstance(parser, JunostInstagramCaptionParser)


def test_parse_october_2026_post() -> None:
    slots = parse_junost_instagram_caption(_CAPTION, pivot_year=2026)
    assert len(slots) == 2
    assert slots[0].local_date == "2026-10-04"
    assert slots[0].starts_at_local == "17:00"
    assert slots[0].ends_at_local == "17:45"
    assert slots[1].starts_at_local == "18:15"
    assert slots[1].ends_at_local == "19:00"


@pytest.mark.asyncio
async def test_extract_applies_prices() -> None:
    extraction = await JunostInstagramCaptionParser().extract(_job())
    assert len(extraction.slots) == 2
    assert extraction.slots[0].price_adult == 8.0
    assert extraction.slots[0].price_child == 6.0
    assert extraction.slots[0].price_rental == 7.0
    assert extraction.slots[0].age_note == "детский до 16 лет"


@pytest.mark.asyncio
async def test_inline_caption_text() -> None:
    base = _job()
    job = replace(
        base,
        config={
            **base.config,
            "caption_text": _CAPTION,
            "caption_file": "/nonexistent",
        },
    )
    extraction = await JunostInstagramCaptionParser().extract(job)
    assert len(extraction.slots) == 2
