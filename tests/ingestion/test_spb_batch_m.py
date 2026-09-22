"""SPb batch M ice parser: Ледовая арена «Динамо-Юниор» (arena_id=173).

Fixture + hand-extracted ``expected.json`` come from a direct ``curl`` of the
operator's own live page (``shorspb.ru/Skating``) on 2026-09-22 (see
``data/parsers/spb-dinamo-yunior.md``). This test runs the real
extract -> normalize -> validate pipeline against the captured fixture and
checks the result against that ground truth — same pattern as
``tests/ingestion/test_spb_batch_b.py``.

Currency is RUB and timezone is Europe/Moscow — the assertions below check
that explicitly, since ``IceSessionNormalizer`` silently falls back to
BYN/Europe/Minsk when a job.config omits those keys.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters_spb_batch_m import DinamoYuniorHtmlParser
from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.parsers import default_registry
from src.ingestion.types import ParserJob
from src.ingestion.validate import IceSessionValidator

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / "data/fixtures"

_DINAMO_YUNIOR_CONFIG = {
    "url": "https://shorspb.ru/Skating",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "week_start": "2026-09-22",
    "horizon_days": 7,
    "requires_by_egress": False,
}


def _job(*, arena_id: int, parser_key: str, config: dict, job_id: int) -> ParserJob:
    return ParserJob(
        id=job_id,
        arena_id=arena_id,
        parser_key=parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc),
        last_run_at=None,
        config=config,
    )


def _dinamo_yunior_job() -> ParserJob:
    cfg = dict(_DINAMO_YUNIOR_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-dinamo-yunior")
    return _job(arena_id=173, parser_key="dinamoyunior_html_v1", config=cfg, job_id=401)


def _load_expected(slug: str) -> dict:
    return json.loads((_FIXTURES / slug / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_dinamo_yunior_matches_expected_snapshot() -> None:
    job = _dinamo_yunior_job()
    expected = _load_expected("spb-dinamo-yunior")
    now = datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc)
    extraction = await DinamoYuniorHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 1
    slot = slots[0]
    gold = expected["sessions"][0]
    assert slot.local_date == date.fromisoformat(gold["local_date"]) == date(2026, 9, 26)
    assert slot.starts_at_local == time.fromisoformat(gold["starts_at_local"])
    assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
    assert slot.kind == "public_skate"
    assert slot.currency_code == "RUB"
    assert slot.price_adult_minor == gold["price_adult_minor"] == 50000
    assert slot.price_child_minor is None
    assert slot.price_rental_minor == gold["price_rental_minor"] == 30000


@pytest.mark.asyncio
async def test_dinamo_yunior_price_anchors_on_currency_not_label_proximity() -> None:
    """AC (spec item 5): the source prints an unrelated '1 час (60 минут)'
    duration before the actual price on the same line as the label — a
    naive 'first number after the label' read would wrongly capture that
    duration instead of the real price. Confirmed against the live fixture."""
    job = _dinamo_yunior_job()
    extraction = await DinamoYuniorHtmlParser().extract(job)
    assert extraction.slots
    slot = extraction.slots[0]
    assert slot.price_adult == "500"
    assert slot.price_rental == "300"


@pytest.mark.asyncio
async def test_dinamo_yunior_empty_schedule_is_valid_empty_state(tmp_path: Path) -> None:
    """AC (spec item 1 convention, mirrors KupchinoArenaHtmlParser): if the
    operator ever clears the schedule paragraph, zero slots is a valid
    'nothing scheduled' state, not an error."""
    empty_html = "<html><body><h1>Пока нет сеансов массового катания.</h1></body></html>"
    fixture_dir = tmp_path / "spb-dinamo-yunior-empty"
    fixture_dir.mkdir()
    (fixture_dir / "skating.html").write_text(empty_html, encoding="utf-8")
    cfg = dict(_DINAMO_YUNIOR_CONFIG)
    cfg["fixture_dir"] = str(fixture_dir)
    job = _job(arena_id=173, parser_key="dinamoyunior_html_v1", config=cfg, job_id=402)

    extraction = await DinamoYuniorHtmlParser().extract(job)

    assert extraction.slots == []


def test_dinamo_yunior_registered() -> None:
    registry = default_registry()
    assert registry.get("dinamoyunior_html_v1") is not None
