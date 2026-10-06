"""Shared ingestion types. Parsers extract; they never INSERT into ice_sessions."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

RUN_STATUS_OK = "ok"
RUN_STATUS_EMPTY = "empty"
RUN_STATUS_ERROR = "error"
RUN_STATUS_BLOCKED = "blocked"
RUN_STATUSES = (
    RUN_STATUS_OK,
    RUN_STATUS_EMPTY,
    RUN_STATUS_ERROR,
    RUN_STATUS_BLOCKED,
)

CADENCE_HOURLY = "hourly"
CADENCE_DAILY = "daily"
CADENCE_WEEKLY = "weekly"
CADENCES = (CADENCE_HOURLY, CADENCE_DAILY, CADENCE_WEEKLY)

PARSER_KIND_PUBLIC_SKATE = "public_skate"
PARSER_KIND_OPEN_ICE = "open_ice"
PARSER_KINDS = (PARSER_KIND_PUBLIC_SKATE, PARSER_KIND_OPEN_ICE)

ALERT_STATE_OK = "ok"
ALERT_STATE_FAILING = "failing"


@dataclass(frozen=True)
class SourceState:
    """Состояние источника арены — колонки ice_parser_jobs из миграции 0211 (TASK-146).

    Правила переходов — в src/ingestion/freshness.py, алертные поля ведёт alerts.
    """

    last_ok_at: datetime | None = None
    last_ok_slot_count: int | None = None
    failing_since: datetime | None = None
    failure_streak: int = 0
    last_error_code: str | None = None
    last_error_summary: str | None = None
    alert_state: str = ALERT_STATE_OK
    alert_sent_at: datetime | None = None


@dataclass
class ParserJob:
    """Schedule row the scheduler hands to a strategy. ``config`` is job.config jsonb.

    ``arena_timezone`` — arena_profiles.timezone (TASK-196): нормализатор берёт его,
    если в конфиге задачи нет своей таймзоны. None (арена без профиля/таймзоны,
    джоба, собранная руками в тесте) → дефолт Europe/Minsk.
    """

    id: int
    arena_id: int
    parser_key: str
    is_enabled: bool
    cadence: str
    next_run_at: datetime
    last_run_at: datetime | None
    config: dict[str, Any]
    notes: str | None = None
    state: SourceState = field(default_factory=SourceState)
    arena_timezone: str | None = None


@dataclass
class ExtractedSlot:
    """Source-shaped slot. Prices may be strings or already-minor ints."""

    local_date: str | date
    starts_at_local: str | time
    kind_raw: str
    ends_at_local: str | time | None = None
    price_adult: Any = None
    price_child: Any = None
    price_rental: Any = None
    source_id: str | None = None
    session_label: str | None = None
    age_note: str | None = None
    capacity_note: str | None = None
    external_url: str | None = None


@dataclass
class Extraction:
    arena_id: int
    parser_key: str
    snapshot: Any
    slots: list[ExtractedSlot] = field(default_factory=list)
    observed_at: datetime | None = None
    schedule_basis: str | None = None


@dataclass(frozen=True)
class CanonicalSlotDraft:
    """Same columns as TASK-050 ice_sessions. Publication is TASK-061."""

    arena_id: int
    kind: str
    starts_at_utc: datetime
    ends_at_utc: datetime
    local_date: date
    starts_at_local: time
    ends_at_local: time
    price_adult_minor: int | None
    price_child_minor: int | None
    price_rental_minor: int | None
    currency_code: str
    status: str
    observed_at: datetime
    valid_until: datetime | None
    session_label: str | None = None
    age_note: str | None = None
    capacity_note: str | None = None
    external_url: str | None = None
    source_id: str | None = None
    schedule_basis: str = "live"
    parser_job_id: int | None = None
    scrape_run_id: int | None = None


@dataclass(frozen=True)
class ScrapeRunRecord:
    job_id: int
    arena_id: int
    parser_key: str
    status: str
    slot_count: int
    slots_dropped: int
    error_message: str | None
    started_at: datetime
    finished_at: datetime
    snapshot: Any = None
    persisted_id: int | None = None
    http_status: int | None = None
    error_code: str | None = None
    # TASK-187: окно публикации (только в памяти, в ice_scrape_runs не пишется).
    # None → дефолты publish_horizon (14 дней, Europe/Minsk).
    publish_horizon_days: int | None = None
    publish_timezone: str | None = None
