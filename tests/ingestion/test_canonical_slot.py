"""AC-005: two fake extractors yield the same CanonicalSlotDraft shape."""
from __future__ import annotations

import inspect
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.parsers import IceParser, MinskArenaSaleframeParser
from src.ingestion.types import CanonicalSlotDraft, ParserJob
from src.ingestion.validate import IceSessionValidator
from tests.ingestion.fakes import FakeHtmlRowParser, FakeJsonWidgetParser

_NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
_ARENA_ID = 2

_JSON_PAYLOAD = {
    "events": [
        {
            "id": "55-1700",
            "date": "2026-09-06",
            "start": "17:00",
            "end": "17:45",
            "kind": "Массовое катание",
            "adult": 850,
            "child": 600,
            "age_note": "детский до 14 лет",
        }
    ]
}

_HTML = """
<table>
  <tr data-kind="Массовое катание">
    <td>2026-09-06</td>
    <td>17:00-17:45</td>
    <td>8.50 р.</td>
    <td>6,00</td>
  </tr>
</table>
"""

_EXPECTED_FIELDS = frozenset(
    {
        "arena_id",
        "kind",
        "starts_at_utc",
        "ends_at_utc",
        "local_date",
        "starts_at_local",
        "ends_at_local",
        "price_adult_minor",
        "price_child_minor",
        "price_rental_minor",
        "currency_code",
        "status",
        "observed_at",
        "valid_until",
        "session_label",
        "age_note",
        "external_url",
        "source_id",
        "parser_job_id",
        "scrape_run_id",
    }
)


def _job(*, parser_key: str, config: dict) -> ParserJob:
    return ParserJob(
        id=10,
        arena_id=_ARENA_ID,
        parser_key=parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=_NOW,
        last_run_at=None,
        config=config,
    )


async def _to_validated(parser: IceParser, job: ParserJob) -> list[CanonicalSlotDraft]:
    extraction = await parser.extract(job)
    drafts = IceSessionNormalizer().normalize(extraction, job, now=_NOW)
    return IceSessionValidator().validate(drafts)


@pytest.mark.asyncio
async def test_json_and_html_fakes_share_canonical_slot_shape() -> None:
    json_job = _job(
        parser_key=FakeJsonWidgetParser.parser_key,
        config={
            "url": "https://saleframe.example/widget",
            "prices_already_minor": True,
            "default_duration_minutes": 45,
            "timezone": "Europe/Minsk",
            "currency_code": "BYN",
            "payload": _JSON_PAYLOAD,
            "observed_at": _NOW,
        },
    )
    html_job = _job(
        parser_key=FakeHtmlRowParser.parser_key,
        config={
            "url": "https://zamok.example/schedule",
            "prices_already_minor": False,
            "default_duration_minutes": 45,
            "timezone": "Europe/Minsk",
            "currency_code": "BYN",
            "html": _HTML,
            "observed_at": _NOW,
        },
    )

    json_slots = await _to_validated(FakeJsonWidgetParser(), json_job)
    html_slots = await _to_validated(FakeHtmlRowParser(), html_job)

    assert len(json_slots) == 1
    assert len(html_slots) == 1
    json_slot, html_slot = json_slots[0], html_slots[0]

    assert set(json_slot.__dataclass_fields__) == _EXPECTED_FIELDS
    assert set(html_slot.__dataclass_fields__) == _EXPECTED_FIELDS
    assert set(json_slot.__dataclass_fields__) == set(CanonicalSlotDraft.__dataclass_fields__)

    for slot in (json_slot, html_slot):
        assert slot.arena_id == _ARENA_ID
        assert slot.kind == "public_skate"
        assert slot.local_date == date(2026, 9, 6)
        assert slot.starts_at_local == time(17, 0)
        assert slot.ends_at_local == time(17, 45)
        assert slot.starts_at_utc == datetime(2026, 9, 6, 14, 0, tzinfo=timezone.utc)
        assert slot.ends_at_utc == datetime(2026, 9, 6, 14, 45, tzinfo=timezone.utc)
        assert slot.price_adult_minor == 850
        assert slot.price_child_minor == 600
        assert slot.price_rental_minor is None
        assert slot.currency_code == "BYN"
        assert slot.status == "active"
        assert isinstance(slot.price_adult_minor, int)
        assert isinstance(slot.starts_at_utc, datetime)


def test_strategy_has_no_sql_and_does_not_bypass_validator() -> None:
    for cls in (FakeJsonWidgetParser, FakeHtmlRowParser, MinskArenaSaleframeParser):
        source = inspect.getsource(cls)
        assert "INSERT" not in source
        assert "ice_sessions" not in source
        assert "execute(" not in source

    validate_src = inspect.getsource(IceSessionValidator.validate)
    assert "kind" in validate_src

    scheduler_path = Path("src/ingestion/scheduler.py")
    sched = scheduler_path.read_text(encoding="utf-8")
    assert "IceSessionValidator" in sched
    assert "INSERT INTO ice_sessions" not in sched
