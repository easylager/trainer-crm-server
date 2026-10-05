import pytest

from src.ingestion.adapters_regional_batch_b import LidaLdsParser
from src.ingestion.types import ParserJob
from src.shared.schedule_basis import SCHEDULE_BASIS_PHOTO


@pytest.mark.asyncio
async def test_lida_without_ocr_images_returns_empty_not_weekday_grid() -> None:
    job = ParserJob(
        id=1,
        arena_id=37,
        parser_key="lida_lds_v1",
        is_enabled=True,
        cadence="weekly",
        next_run_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        last_run_at=None,
        config={
            "prices_url": "https://hc-lida.by/massovoe-katanie.html",
            "default_duration_minutes": 45,
        },
    )
    html = "<html><body><p>посещение без предоставления коньков 10 руб.</p></body></html>"
    parser = LidaLdsParser()

    async def fake_load(_job, **kwargs):
        return html

    from src.ingestion import adapters_regional_batch_b as mod

    mod.load_source_text = fake_load  # type: ignore[method-assign]
    mod._lida_image_urls = lambda _html, _base: []  # type: ignore[method-assign]

    extraction = await parser.extract(job)
    assert extraction.slots == []
    assert extraction.schedule_basis is None


@pytest.mark.asyncio
async def test_lida_fixture_week_start_marks_projected() -> None:
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "lida-lds"
    job = ParserJob(
        id=1,
        arena_id=37,
        parser_key="lida_lds_v1",
        is_enabled=True,
        cadence="weekly",
        next_run_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        last_run_at=None,
        config={
            "fixture_dir": str(fixture),
            "week_start": "2026-09-01",
            "default_duration_minutes": 45,
        },
    )
    extraction = await LidaLdsParser().extract(job)
    assert extraction.slots
    assert extraction.schedule_basis == "projected"
