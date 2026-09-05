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


@dataclass
class ParserJob:
    """Schedule row the scheduler hands to a strategy. ``config`` is job.config jsonb."""

    id: int
    arena_id: int
    parser_key: str
    is_enabled: bool
    cadence: str
    next_run_at: datetime
    last_run_at: datetime | None
    config: dict[str, Any]
    notes: str | None = None


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
    external_url: str | None = None


@dataclass
class Extraction:
    arena_id: int
    parser_key: str
    snapshot: Any
    slots: list[ExtractedSlot] = field(default_factory=list)
    observed_at: datetime | None = None


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
    external_url: str | None = None
    source_id: str | None = None
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
