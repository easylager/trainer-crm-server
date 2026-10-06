"""TASK-196 AC-1: нормализатор берёт таймзону арены, если в конфиге задачи её нет.

До этого вся корректность расписаний держалась на совпадении «все города UTC+3»:
конфиг задачи молчил → Минск. У арены в Екатеринбурге (UTC+5) местное 19:00 —
это 14:00 UTC, а не 16:00. Порядок: конфиг задачи → таймзона арены → Минск.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from src.ingestion.jobs import job_from_row
from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob

_NOW = datetime(2026, 1, 10, 8, 0, tzinfo=timezone.utc)


def _job(*, config: dict | None = None, arena_timezone: str | None = None) -> ParserJob:
    return ParserJob(
        id=1,
        arena_id=99,
        parser_key="fake",
        is_enabled=True,
        cadence="daily",
        next_run_at=_NOW,
        last_run_at=None,
        config=config if config is not None else {},
        arena_timezone=arena_timezone,
    )


def _extraction() -> Extraction:
    slot = ExtractedSlot(
        local_date="2026-01-15",
        starts_at_local="19:00",
        ends_at_local="20:00",
        kind_raw="массовое катание",
        price_adult="10",
    )
    return Extraction(arena_id=99, parser_key="fake", snapshot="{}", slots=[slot], observed_at=_NOW)


def _starts_at_utc(job: ParserJob) -> datetime:
    drafts = IceSessionNormalizer().normalize(_extraction(), job, now=_NOW)
    assert len(drafts) == 1
    return drafts[0].starts_at_utc


def test_arena_timezone_utc5_shifts_start_by_five_hours() -> None:
    """AC-1: арена с UTC+5 (Екатеринбург) без таймзоны в конфиге — 19:00 → 14:00 UTC."""
    starts = _starts_at_utc(_job(arena_timezone="Asia/Yekaterinburg"))
    assert starts == datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)


def test_config_timezone_wins_over_arena_timezone() -> None:
    """Конфиг задачи остаётся главным: явная таймзона не затирается ареной."""
    starts = _starts_at_utc(_job(config={"timezone": "Europe/Samara"}, arena_timezone="Asia/Yekaterinburg"))
    assert starts == datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)


def test_no_timezone_anywhere_defaults_to_minsk() -> None:
    """Ни конфига, ни арены — прежний дефолт Europe/Minsk (19:00 → 16:00 UTC)."""
    starts = _starts_at_utc(_job())
    assert starts == datetime(2026, 1, 15, 16, 0, tzinfo=timezone.utc)


def test_job_from_row_reads_arena_timezone() -> None:
    """Хранилище приносит таймзону арены в джобу (list_due SELECT ap.timezone AS arena_timezone)."""
    row = SimpleNamespace(
        id=1,
        arena_id=99,
        parser_key="fake",
        is_enabled=True,
        cadence="daily",
        next_run_at=_NOW,
        last_run_at=None,
        config={},
        notes=None,
        arena_timezone="Europe/Moscow",
    )
    job = job_from_row(row)
    assert job.arena_timezone == "Europe/Moscow"
    # Строки без таймзоны (старый SELECT, джоба без профиля) не ломают хранилище.
    assert job_from_row(SimpleNamespace(**{**row.__dict__, "arena_timezone": None})).arena_timezone is None
