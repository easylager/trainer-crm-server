"""SPb batch B ice parser: Ледовая арена «Купчино» (arena_id=110).

Fixture + hand-extracted ``expected.json`` come from a direct ``curl`` of the
operator's own live page on 2026-09-22 (see ``data/parsers/spb-kupchino-arena.md``).
This test runs the real extract -> normalize -> validate pipeline against the
captured fixture and checks the result against that ground truth — same
pattern as ``tests/ingestion/test_ru_pilot_adapters.py``.

Currency is RUB and timezone is Europe/Moscow — the assertions below check
that explicitly, since ``IceSessionNormalizer`` silently falls back to
BYN/Europe/Minsk when a job.config omits those keys.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters_spb_batch_b import KupchinoArenaHtmlParser
from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.parsers import default_registry
from src.ingestion.types import ParserJob
from src.ingestion.validate import IceSessionValidator

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / "data/fixtures"

_KUPCHINO_ARENA_CONFIG = {
    "url": "https://arenakupchino.ru/massskating",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "prices_already_minor": True,
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


def _kupchino_arena_job() -> ParserJob:
    cfg = dict(_KUPCHINO_ARENA_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-kupchino-arena")
    return _job(arena_id=110, parser_key="kupchinoarena_html_v1", config=cfg, job_id=301)


def _load_expected(slug: str) -> dict:
    return json.loads((_FIXTURES / slug / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_kupchino_arena_matches_expected_snapshot() -> None:
    job = _kupchino_arena_job()
    expected = _load_expected("spb-kupchino-arena")
    now = datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc)
    extraction = await KupchinoArenaHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 2
    by_start = {slot.starts_at_local: slot for slot in slots}
    for gold in expected["sessions"]:
        slot = by_start[time.fromisoformat(gold["starts_at_local"])]
        assert slot.local_date == date.fromisoformat(gold["local_date"]) == date(2026, 9, 26)
        assert slot.kind == "public_skate"
        assert slot.currency_code == "RUB"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"] == 50000
        assert slot.price_child_minor is None
        assert slot.price_rental_minor == gold["price_rental_minor"] == 50000


@pytest.mark.asyncio
async def test_kupchino_arena_mixed_cyrillic_latin_preposition_both_accepted() -> None:
    """AC (spec item 3): the source's own two session lines use a Cyrillic
    'с' before the first start time and a Latin 'c' before the second — a
    real copy-paste typo, not a parsing artifact. Both must be extracted."""
    job = _kupchino_arena_job()
    extraction = await KupchinoArenaHtmlParser().extract(job)
    assert len(extraction.slots) == 2
    starts = {slot.starts_at_local for slot in extraction.slots}
    assert starts == {"15:15", "19:45"}


@pytest.mark.asyncio
async def test_kupchino_arena_empty_schedule_block_is_valid_empty_state(tmp_path: Path) -> None:
    """AC (spec item 9 convention): the operator sometimes clears the 'Время
    сеанса:' block down to nothing between updates — zero slots, not an error."""
    empty_html = (
        "<h2 class='tn-atom'>Время<br>сеанса:</h2> </div> <div>"
        "<h3 class='tn-atom'></h3>"
        "<h2 class='tn-atom'>Стоимость<br>входного билета</h2> </div> <div>"
        "<h3 class='tn-atom'>500 ₽</h3>"
    )
    fixture_dir = tmp_path / "spb-kupchino-arena-empty"
    fixture_dir.mkdir()
    (fixture_dir / "massskating.html").write_text(empty_html, encoding="utf-8")
    cfg = dict(_KUPCHINO_ARENA_CONFIG)
    cfg["fixture_dir"] = str(fixture_dir)
    job = _job(arena_id=110, parser_key="kupchinoarena_html_v1", config=cfg, job_id=302)

    extraction = await KupchinoArenaHtmlParser().extract(job)

    assert extraction.slots == []


def test_kupchino_arena_registered() -> None:
    registry = default_registry()
    assert registry.get("kupchinoarena_html_v1") is not None
