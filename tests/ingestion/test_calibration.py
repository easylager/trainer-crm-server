"""TASK-066: gold set vs adapter output in canonical ice_sessions shape."""
from __future__ import annotations

import json
from datetime import date, time

import pytest

from src.ingestion.calibration import (
    CalibrationReport,
    GoldSlot,
    PredictedSlot,
    SCORE_FLOORS,
    assert_calibration_floors,
    compare_slots,
    format_calibration_report,
    load_gold_manifest,
    metrics_for_digest,
    run_calibration,
    score_source,
)

_GOLD = [
    GoldSlot(
        local_date=date(2026, 9, 6),
        starts_at_local=time(17, 0),
        ends_at_local=time(17, 45),
        kind="public_skate",
        price_adult_minor=850,
        price_child_minor=600,
        price_rental_minor=None,
        session_label=None,
    ),
    GoldSlot(
        local_date=date(2026, 9, 6),
        starts_at_local=time(19, 0),
        ends_at_local=time(19, 45),
        kind="public_skate",
        price_adult_minor=850,
        price_child_minor=600,
        price_rental_minor=None,
        session_label=None,
    ),
]


def _pred(**overrides) -> PredictedSlot:
    base = dict(
        local_date=date(2026, 9, 6),
        starts_at_local=time(17, 0),
        ends_at_local=time(17, 45),
        kind="public_skate",
        price_adult_minor=850,
        price_child_minor=600,
        price_rental_minor=None,
        session_label=None,
    )
    base.update(overrides)
    return PredictedSlot(**base)


def test_perfect_extract_scores_one() -> None:
    predicted = [
        _pred(),
        _pred(starts_at_local=time(19, 0), ends_at_local=time(19, 45)),
    ]
    metrics = compare_slots(_GOLD, predicted)
    assert metrics.recall == 1.0
    assert metrics.precision == 1.0
    assert metrics.price_accuracy == 1.0
    assert metrics.kind_accuracy == 1.0
    assert metrics.gold_count == 2
    assert metrics.predicted_count == 2


def test_missing_slot_lowers_recall_not_precision() -> None:
    metrics = compare_slots(_GOLD, [_pred()])
    assert metrics.recall == 0.5
    assert metrics.precision == 1.0
    assert metrics.false_negatives == 1
    assert metrics.false_positives == 0


def test_extra_slot_lowers_precision_not_recall() -> None:
    predicted = [
        _pred(),
        _pred(starts_at_local=time(19, 0), ends_at_local=time(19, 45)),
        _pred(starts_at_local=time(21, 0), ends_at_local=time(21, 45)),
    ]
    metrics = compare_slots(_GOLD, predicted)
    assert metrics.recall == 1.0
    assert metrics.precision == pytest.approx(2 / 3)
    assert metrics.false_positives == 1


def test_wrong_price_or_kind_on_matched_slot() -> None:
    predicted = [
        _pred(price_child_minor=999),
        _pred(starts_at_local=time(19, 0), ends_at_local=time(19, 45), kind="open_ice"),
    ]
    metrics = compare_slots(_GOLD, predicted)
    assert metrics.recall == 1.0
    assert metrics.precision == 1.0
    assert metrics.price_accuracy == 0.5
    assert metrics.kind_accuracy == 0.5


def test_ambiguous_gold_slots_are_excluded_from_scoring() -> None:
    gold = [
        _GOLD[0],
        GoldSlot(
            local_date=date(2026, 9, 7),
            starts_at_local=time(11, 0),
            ends_at_local=time(12, 0),
            kind="public_skate",
            price_adult_minor=None,
            price_child_minor=None,
            price_rental_minor=None,
            session_label=None,
            ambiguous=True,
        ),
    ]
    predicted = [_pred(), _pred(local_date=date(2026, 9, 7), starts_at_local=time(11, 0))]
    metrics = compare_slots(gold, predicted)
    assert metrics.gold_count == 1
    assert metrics.recall == 1.0
    assert metrics.precision == 1.0
    assert metrics.excluded_ambiguous == 1


def test_empty_blocked_terminal_scores_perfect() -> None:
    metrics = compare_slots([], [])
    assert metrics.recall == 1.0
    assert metrics.precision == 1.0
    assert metrics.price_accuracy == 1.0
    assert metrics.kind_accuracy == 1.0
    assert metrics.gold_count == 0


def test_gold_manifest_covers_minsk_mk_pilot() -> None:
    manifest = load_gold_manifest()
    ids = {item.source_id for item in manifest.items}
    assert ids == {
        "minsk-arena",
        "minsk-zamok",
        "minsk-chizhovka",
        "minsk-ledby",
        "minsk-diamond",
        "minsk-junost",
        "minsk-ledlife",
    }
    for item in manifest.items:
        assert item.gold_path.is_file(), item.source_id
        for name in item.source_files:
            assert (item.fixture_dir / name).is_file(), f"{item.source_id} missing snapshot {name}"
        payload = json.loads(item.gold_path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == "canonical-slot-v1"
        assert "sessions" in payload
        assert payload.get("timezone") == "Europe/Minsk"


def test_ledby_gold_drops_oxm_column() -> None:
    """expected.json must not treat ОТРАБОТКА column times as public_skate (spec)."""
    item = next(row for row in load_gold_manifest().items if row.source_id == "minsk-ledby")
    sessions = json.loads(item.gold_path.read_text(encoding="utf-8"))["sessions"]
    keys = {(row["local_date"], row["starts_at_local"]) for row in sessions}
    oxm_times = {
        ("2026-09-01", "13:00"),
        ("2026-09-02", "13:00"),
        ("2026-09-03", "12:00"),
        ("2026-09-04", "12:00"),
        ("2026-09-07", "13:00"),
        ("2026-09-08", "13:00"),
        ("2026-09-09", "17:45"),
        ("2026-09-10", "12:00"),
        ("2026-09-11", "12:45"),
    }
    assert keys.isdisjoint(oxm_times)
    assert len(sessions) == 12


@pytest.mark.asyncio
async def test_calibration_run_reports_per_source_and_overall() -> None:
    report = await run_calibration()
    assert {row.source_id for row in report.sources} == {
        item.source_id for item in load_gold_manifest().items
    }
    text = format_calibration_report(report)
    digest = metrics_for_digest(report)
    assert "recall" in text and "precision" in text
    assert digest["overall"]["recall"] == report.overall.recall
    assert digest["overall"]["precision"] == report.overall.precision
    assert digest["overall"]["price_accuracy"] == report.overall.price_accuracy
    assert digest["overall"]["kind_accuracy"] == report.overall.kind_accuracy
    assert set(digest["by_source"]) == {row.source_id for row in report.sources}
    assert_calibration_floors(report)
    for row in report.sources:
        if row.source_id == "minsk-diamond":
            assert row.metrics.recall >= SCORE_FLOORS["minsk-diamond"]["recall"]
            continue
        assert row.metrics.recall == 1.0, row.source_id
        assert row.metrics.precision == 1.0, row.source_id
        assert row.metrics.price_accuracy == 1.0, row.source_id
        assert row.metrics.kind_accuracy == 1.0, row.source_id


def test_calibration_cli_prints_digest_json(capsys) -> None:
    from src.ingestion.calibration import main

    assert main([]) == 0
    captured = capsys.readouterr().out
    assert "recall=" in captured
    assert '"by_source"' in captured
    assert "minsk-arena" in captured
    metrics = compare_slots(_GOLD, [_pred()])
    report = CalibrationReport(sources=(score_source("minsk-arena", metrics),), overall=metrics)
    with pytest.raises(AssertionError, match="recall"):
        assert_calibration_floors(report)
