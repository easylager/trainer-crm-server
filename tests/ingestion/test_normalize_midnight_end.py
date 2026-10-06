"""TASK-187: 24:00 и нечитаемое время — строка, а не прогон."""
from __future__ import annotations

from datetime import date, datetime, time, timezone

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
        config={"timezone": "Europe/Minsk", "currency_code": "BYN", "prices_already_minor": True},
    )


def _extraction(*slots: ExtractedSlot) -> Extraction:
    return Extraction(arena_id=99, parser_key="fake", snapshot="{}", slots=list(slots), observed_at=_NOW)


def _slot(start: str, end: str | None, day: str = "2026-01-15") -> ExtractedSlot:
    return ExtractedSlot(
        local_date=day, starts_at_local=start, ends_at_local=end, kind_raw="массовое катание", price_adult="10"
    )


def test_2230_to_2400_publishes_as_midnight_end() -> None:
    """AC-4: 22:30–24:00 → 22:30–00:00, 90 минут."""
    drafts = IceSessionNormalizer().normalize(_extraction(_slot("22:30", "24:00")), _job(), now=_NOW)
    validated = IceSessionValidator().validate(drafts)
    assert len(validated) == 1
    row = validated[0]
    assert row.local_date == date(2026, 1, 15)
    assert row.starts_at_local == time(22, 30)
    assert row.ends_at_local == time(0, 0)
    assert (row.ends_at_utc - row.starts_at_utc).total_seconds() == 90 * 60


def test_2400_as_start_is_next_day_midnight() -> None:
    """Ревью #4: 24:00 как НАЧАЛО — 00:00 следующего дня, а не 00:00 этого."""
    drafts = IceSessionNormalizer().normalize(_extraction(_slot("24:00", "01:00")), _job(), now=_NOW)
    assert len(drafts) == 1
    assert drafts[0].local_date == date(2026, 1, 16)
    assert drafts[0].starts_at_local == time(0, 0)
    assert drafts[0].ends_at_local == time(1, 0)


def test_unreadable_time_drops_row_not_run() -> None:
    normalizer = IceSessionNormalizer()
    drafts, report = normalizer.normalize_with_report(
        _extraction(_slot("18:00", "19:00"), _slot("25:61", "26:00"), _slot("19:30", "ночь"), _slot("x", None)),
        _job(),
        now=_NOW,
    )
    assert [d.starts_at_local for d in drafts] == [time(18, 0)]
    assert report.invalid_time == 3
    assert "кривые дата/время 3" in report.summary()
