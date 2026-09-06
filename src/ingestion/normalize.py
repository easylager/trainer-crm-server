"""Transform Extraction → CanonicalSlotDraft. Shared across every arena adapter."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from src.application.ice_session_use_cases import (
    DEFAULT_ARENA_TZ,
    STATUS_ACTIVE,
    compute_session_datetimes,
    parse_hhmm,
)
from src.ingestion.types import (
    PARSER_KIND_OPEN_ICE,
    PARSER_KIND_PUBLIC_SKATE,
    CanonicalSlotDraft,
    Extraction,
    ParserJob,
)

_AMOUNT = re.compile(r"(\d+(?:[.,]\d+)?)")
_KOPECK = re.compile(r"коп", re.IGNORECASE)


def parse_price_to_minor(value: Any, *, already_minor: bool) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value) if already_minor else int(value) * 100
    if isinstance(value, float):
        if already_minor:
            return int(round(value))
        return int(round(Decimal(str(value)) * 100))
    text = str(value).strip()
    if not text:
        return None
    match = _AMOUNT.search(text.replace(" ", ""))
    if match is None:
        return None
    try:
        amount = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    if already_minor or _KOPECK.search(text):
        return int(round(amount))
    return int(round(amount * 100))


def map_parser_kind(raw: str) -> str | None:
    key = (raw or "").strip().lower()
    if key in {PARSER_KIND_PUBLIC_SKATE, "mk", "мк", "ма", "ба"}:
        return PARSER_KIND_PUBLIC_SKATE
    if key == PARSER_KIND_OPEN_ICE:
        return PARSER_KIND_OPEN_ICE
    if "свободн" in key:
        return PARSER_KIND_OPEN_ICE
    if "массов" in key:
        return PARSER_KIND_PUBLIC_SKATE
    return None


def _as_date(value: str | date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def _as_time(value: str | time) -> time:
    if isinstance(value, time):
        return time(value.hour, value.minute)
    return parse_hhmm(str(value))


def _truthy_minor_flag(config: dict[str, Any]) -> bool:
    raw = config.get("prices_already_minor", False)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes"}
    return bool(raw)


class IceSessionNormalizer:
    def normalize(
        self,
        extraction: Extraction,
        job: ParserJob,
        *,
        now: datetime,
    ) -> list[CanonicalSlotDraft]:
        config = job.config or {}
        tz_name = str(config.get("timezone") or DEFAULT_ARENA_TZ)
        currency = str(config.get("currency_code") or "BYN")
        already_minor = _truthy_minor_flag(config)
        default_duration = int(config.get("default_duration_minutes") or 60)
        observed = extraction.observed_at or now
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)

        merged: dict[tuple[date, time], dict[str, Any]] = {}
        for raw in extraction.slots:
            kind = map_parser_kind(raw.kind_raw)
            if kind is None:
                continue
            local_date = _as_date(raw.local_date)
            starts_at_local = _as_time(raw.starts_at_local)
            key = (local_date, starts_at_local)
            bucket = merged.setdefault(
                key,
                {
                    "kind": kind,
                    "ends_at_local": raw.ends_at_local,
                    "price_adult_minor": None,
                    "price_child_minor": None,
                    "price_rental_minor": None,
                    "source_id": raw.source_id,
                    "session_label": raw.session_label,
                    "age_note": raw.age_note,
                    "external_url": raw.external_url,
                },
            )
            adult = parse_price_to_minor(raw.price_adult, already_minor=already_minor)
            child = parse_price_to_minor(raw.price_child, already_minor=already_minor)
            rental = parse_price_to_minor(raw.price_rental, already_minor=already_minor)
            if adult is not None:
                bucket["price_adult_minor"] = adult
            if child is not None:
                bucket["price_child_minor"] = child
            if rental is not None:
                bucket["price_rental_minor"] = rental
            if raw.ends_at_local and not bucket["ends_at_local"]:
                bucket["ends_at_local"] = raw.ends_at_local
            if raw.age_note and not bucket["age_note"]:
                bucket["age_note"] = raw.age_note
            if raw.source_id and not bucket["source_id"]:
                bucket["source_id"] = raw.source_id

        drafts: list[CanonicalSlotDraft] = []
        for (local_date, starts_at_local), bucket in sorted(merged.items()):
            duration = default_duration
            end_raw = bucket["ends_at_local"]
            if end_raw:
                end_local = _as_time(end_raw)
                start_minutes = starts_at_local.hour * 60 + starts_at_local.minute
                end_minutes = end_local.hour * 60 + end_local.minute
                span = end_minutes - start_minutes
                if span <= 0:
                    span += 24 * 60
                duration = span
            parts = compute_session_datetimes(
                local_date=local_date,
                starts_at_local=starts_at_local,
                duration_minutes=duration,
                tz_name=tz_name,
            )
            if parts.ends_at_utc <= now:
                continue
            drafts.append(
                CanonicalSlotDraft(
                    arena_id=job.arena_id,
                    kind=bucket["kind"],
                    starts_at_utc=parts.starts_at_utc,
                    ends_at_utc=parts.ends_at_utc,
                    local_date=parts.local_date,
                    starts_at_local=parts.starts_at_local,
                    ends_at_local=parts.ends_at_local,
                    price_adult_minor=bucket["price_adult_minor"],
                    price_child_minor=bucket["price_child_minor"],
                    price_rental_minor=bucket["price_rental_minor"],
                    currency_code=currency,
                    status=STATUS_ACTIVE,
                    observed_at=observed,
                    valid_until=parts.ends_at_utc,
                    session_label=bucket["session_label"],
                    age_note=bucket["age_note"],
                    external_url=bucket["external_url"],
                    source_id=bucket["source_id"],
                    parser_job_id=job.id,
                    scrape_run_id=None,
                )
            )
        return drafts
