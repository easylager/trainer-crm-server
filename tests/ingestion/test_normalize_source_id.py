"""Regression: over-long adapter-supplied text must never crash publish.

Root cause (prod incident, 2026-09-21): Ozerki's Google Calendar recurring
events give each instance a long composite id; "<rink_code>:<id>" overflowed
ice_sessions.source_id (varchar(64)) and crashed the publish INSERT, which
took the whole ice-ingest scheduler tick down. Migration 0204 widened the
column to 160; this test guards the code-level safety net independently of
column width.

A follow-up audit (same day) found the same bug class was still open for
session_label/age_note/external_url — adapters read unbounded text straight
from third-party widget APIs (e.g. an event title) with no cap before it hit
those fixed-width columns. Generalized the guard to all of them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.ingestion.normalize import (
    IceSessionNormalizer,
    _AGE_NOTE_MAX_LEN,
    _SESSION_LABEL_MAX_LEN,
    _SOURCE_ID_MAX_LEN,
    _clip_text,
    _safe_external_url,
    _safe_source_id,
)
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob

_NOW = datetime(2026, 9, 22, 0, 0, tzinfo=timezone.utc)


def test_safe_source_id_passes_through_short_values() -> None:
    assert _safe_source_id("little:abc123") == "little:abc123"
    assert _safe_source_id(None) is None


def test_safe_source_id_hashes_oversized_values_deterministically() -> None:
    raw = "little:" + "6cp32oph6lhjcbb664qj2b9kckq68bb2c4p6cb9l68pj8o9oc8p34c9o70" * 3
    capped = _safe_source_id(raw)
    assert capped is not None
    assert len(capped) <= _SOURCE_ID_MAX_LEN
    assert capped == _safe_source_id(raw)  # stable across calls, so dedup still works


def test_clip_text_passes_through_short_values() -> None:
    assert _clip_text("Малая арена", 128) == "Малая арена"
    assert _clip_text(None, 128) is None


def test_clip_text_truncates_oversized_values() -> None:
    long_title = "Новогоднее массовое катание " * 10  # well over 128 chars
    clipped = _clip_text(long_title, 128)
    assert clipped is not None
    assert len(clipped) == 128
    assert clipped.endswith("…")


def test_safe_external_url_drops_oversized_values_instead_of_breaking_them() -> None:
    long_url = "https://example.test/" + "a" * 600
    assert _safe_external_url(long_url) is None
    assert _safe_external_url("https://example.test/ok") == "https://example.test/ok"


def test_normalizer_caps_oversized_source_id_from_adapter() -> None:
    job = ParserJob(
        id=1,
        arena_id=101,
        parser_key="ozerki_gcal_v1",
        is_enabled=True,
        cadence="hourly",
        next_run_at=_NOW,
        last_run_at=None,
        config={"timezone": "Europe/Moscow", "currency_code": "RUB"},
    )
    long_event_id = "6cp32oph6lhjcbb664qj2b9kckq68bb2c4p6cb9l68pj8o9oc8p34c9o70" * 3
    extraction = Extraction(
        arena_id=job.arena_id,
        parser_key=job.parser_key,
        snapshot={},
        slots=[
            ExtractedSlot(
                local_date="2026-09-22",
                starts_at_local="09:00",
                ends_at_local="10:00",
                kind_raw="public_skate",
                price_adult=40000,
                source_id=f"little:{long_event_id}",
            )
        ],
    )
    drafts = IceSessionNormalizer().normalize(extraction, job, now=_NOW)
    assert len(drafts) == 1
    source_id = drafts[0].source_id
    assert source_id is not None
    assert len(source_id) <= _SOURCE_ID_MAX_LEN
    assert source_id != f"little:{long_event_id}"  # actually capped, not coincidentally short


def test_normalizer_caps_oversized_session_label_and_age_note_from_adapter() -> None:
    job = ParserJob(
        id=1,
        arena_id=102,
        parser_key="some_widget_v1",
        is_enabled=True,
        cadence="hourly",
        next_run_at=_NOW,
        last_run_at=None,
        config={"timezone": "Europe/Moscow", "currency_code": "RUB"},
    )
    long_title = "Новогоднее массовое катание с Дедом Морозом " * 6
    long_note = "0+ " * 100
    extraction = Extraction(
        arena_id=job.arena_id,
        parser_key=job.parser_key,
        snapshot={},
        slots=[
            ExtractedSlot(
                local_date="2026-09-22",
                starts_at_local="09:00",
                ends_at_local="10:00",
                kind_raw="public_skate",
                price_adult=40000,
                session_label=long_title,
                age_note=long_note,
            )
        ],
    )
    drafts = IceSessionNormalizer().normalize(extraction, job, now=_NOW)
    assert len(drafts) == 1
    assert drafts[0].session_label is not None
    assert len(drafts[0].session_label) <= _SESSION_LABEL_MAX_LEN
    assert drafts[0].age_note is not None
    assert len(drafts[0].age_note) <= _AGE_NOTE_MAX_LEN
