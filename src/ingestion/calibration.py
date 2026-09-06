"""TASK-066: gold set vs adapter output in canonical ice_sessions shape.

Compare extract → normalize → validate drafts to human-verified slots.
Never score widget HTML. TASK-062 can print ``metrics_for_digest``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable

from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.parsers import default_registry
from src.ingestion.seed_config import MINSK_ARENA_SALEFRAME_CONFIG, PARSER_KEY_MINSK_ARENA
from src.ingestion.types import CanonicalSlotDraft, ParserJob
from src.ingestion.validate import IceSessionValidator

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / ".ai/data/fixtures"
MANIFEST_PATH = REPO_ROOT / ".ai/data/calibration/manifest.json"
_NOW_FALLBACK = datetime(2026, 8, 30, 6, 0, tzinfo=timezone.utc)

SCORE_FLOORS: dict[str, dict[str, float]] = {
    "overall": {
        "recall": 0.95,
        "precision": 1.0,
        "price_accuracy": 1.0,
        "kind_accuracy": 1.0,
    },
    "default": {
        "recall": 1.0,
        "precision": 1.0,
        "price_accuracy": 1.0,
        "kind_accuracy": 1.0,
    },
    "minsk-diamond": {
        "recall": 1.0,
        "precision": 1.0,
        "price_accuracy": 1.0,
        "kind_accuracy": 1.0,
    },
}


@dataclass(frozen=True)
class GoldSlot:
    local_date: date
    starts_at_local: time
    ends_at_local: time
    kind: str
    price_adult_minor: int | None
    price_child_minor: int | None
    price_rental_minor: int | None
    session_label: str | None = None
    ambiguous: bool = False


@dataclass(frozen=True)
class PredictedSlot:
    local_date: date
    starts_at_local: time
    ends_at_local: time
    kind: str
    price_adult_minor: int | None
    price_child_minor: int | None
    price_rental_minor: int | None
    session_label: str | None = None


@dataclass(frozen=True)
class SlotMetrics:
    recall: float
    precision: float
    price_accuracy: float
    kind_accuracy: float
    gold_count: int
    predicted_count: int
    true_positives: int
    false_negatives: int
    false_positives: int
    price_matches: int = 0
    kind_matches: int = 0
    excluded_ambiguous: int = 0


@dataclass(frozen=True)
class GoldItem:
    source_id: str
    fixture_dir: Path
    gold_path: Path
    parser_key: str
    source_files: tuple[str, ...]
    scoring: str
    now: datetime
    extra_config: dict[str, Any]


@dataclass(frozen=True)
class GoldManifest:
    items: tuple[GoldItem, ...]


@dataclass(frozen=True)
class SourceScore:
    source_id: str
    parser_key: str
    metrics: SlotMetrics
    scoring: str


@dataclass(frozen=True)
class CalibrationReport:
    sources: tuple[SourceScore, ...]
    overall: SlotMetrics


def _hhmm(value: str | time) -> time:
    if isinstance(value, time):
        return time(value.hour, value.minute)
    hour, minute = (int(part) for part in str(value).split(":")[:2])
    return time(hour, minute)


def _slot_key(slot: GoldSlot | PredictedSlot | CanonicalSlotDraft) -> tuple[str, str, str]:
    local_date = slot.local_date.isoformat() if isinstance(slot.local_date, date) else str(slot.local_date)
    start = slot.starts_at_local.strftime("%H:%M") if isinstance(slot.starts_at_local, time) else str(slot.starts_at_local)
    label = slot.session_label or ""
    return (local_date, start, label)


def _ratio(num: int, den: int) -> float:
    if den <= 0:
        return 1.0
    return num / den


def compare_slots(gold: Iterable[GoldSlot], predicted: Iterable[PredictedSlot]) -> SlotMetrics:
    gold_list = list(gold)
    ambiguous_keys = {_slot_key(slot) for slot in gold_list if slot.ambiguous}
    scored_gold = [slot for slot in gold_list if not slot.ambiguous]
    gold_map = {_slot_key(slot): slot for slot in scored_gold}
    pred_map = {_slot_key(slot): slot for slot in predicted if _slot_key(slot) not in ambiguous_keys}
    matched_keys = set(gold_map) & set(pred_map)
    extra = set(pred_map) - set(gold_map)
    tp = len(matched_keys)
    fn = len(set(gold_map) - set(pred_map))
    fp = len(extra)
    excluded = len(ambiguous_keys)
    price_ok = 0
    kind_ok = 0
    for key in matched_keys:
        g = gold_map[key]
        p = pred_map[key]
        if (
            p.price_adult_minor == g.price_adult_minor
            and p.price_child_minor == g.price_child_minor
            and p.price_rental_minor == g.price_rental_minor
        ):
            price_ok += 1
        if p.kind == g.kind:
            kind_ok += 1
    gold_count = len(gold_map)
    pred_count = len(pred_map)
    return SlotMetrics(
        recall=_ratio(tp, gold_count),
        precision=_ratio(tp, pred_count),
        price_accuracy=_ratio(price_ok, tp),
        kind_accuracy=_ratio(kind_ok, tp),
        gold_count=gold_count,
        predicted_count=pred_count,
        true_positives=tp,
        false_negatives=fn,
        false_positives=fp,
        price_matches=price_ok,
        kind_matches=kind_ok,
        excluded_ambiguous=excluded,
    )


def merge_metrics(rows: Iterable[SlotMetrics]) -> SlotMetrics:
    items = list(rows)
    if not items:
        return compare_slots([], [])
    tp = sum(row.true_positives for row in items)
    fn = sum(row.false_negatives for row in items)
    fp = sum(row.false_positives for row in items)
    gold_count = sum(row.gold_count for row in items)
    pred_count = sum(row.predicted_count for row in items)
    price_ok = sum(row.price_matches for row in items)
    kind_ok = sum(row.kind_matches for row in items)
    return SlotMetrics(
        recall=_ratio(tp, gold_count),
        precision=_ratio(tp, pred_count),
        price_accuracy=_ratio(price_ok, tp),
        kind_accuracy=_ratio(kind_ok, tp),
        gold_count=gold_count,
        predicted_count=pred_count,
        true_positives=tp,
        false_negatives=fn,
        false_positives=fp,
        price_matches=price_ok,
        kind_matches=kind_ok,
        excluded_ambiguous=sum(row.excluded_ambiguous for row in items),
    )


def score_source(source_id: str, metrics: SlotMetrics, *, parser_key: str = "", scoring: str = "adapter") -> SourceScore:
    return SourceScore(source_id=source_id, parser_key=parser_key, metrics=metrics, scoring=scoring)


def gold_slots_from_expected(payload: dict[str, Any]) -> list[GoldSlot]:
    slots: list[GoldSlot] = []
    for row in payload.get("sessions") or []:
        slots.append(
            GoldSlot(
                local_date=date.fromisoformat(str(row["local_date"])[:10]),
                starts_at_local=_hhmm(row["starts_at_local"]),
                ends_at_local=_hhmm(row["ends_at_local"]),
                kind=str(row["kind"]),
                price_adult_minor=row.get("price_adult_minor"),
                price_child_minor=row.get("price_child_minor"),
                price_rental_minor=row.get("price_rental_minor"),
                session_label=row.get("session_label"),
                ambiguous=bool(row.get("ambiguous") or row.get("exclude_from_scoring")),
            )
        )
    return slots


def predicted_from_drafts(drafts: Iterable[CanonicalSlotDraft]) -> list[PredictedSlot]:
    return [
        PredictedSlot(
            local_date=draft.local_date,
            starts_at_local=draft.starts_at_local,
            ends_at_local=draft.ends_at_local,
            kind=draft.kind,
            price_adult_minor=draft.price_adult_minor,
            price_child_minor=draft.price_child_minor,
            price_rental_minor=draft.price_rental_minor,
            session_label=draft.session_label,
        )
        for draft in drafts
    ]


def _parse_now(raw: str | None) -> datetime:
    if not raw:
        return _NOW_FALLBACK
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def load_gold_manifest(path: Path | None = None) -> GoldManifest:
    payload = json.loads((path or MANIFEST_PATH).read_text(encoding="utf-8"))
    items: list[GoldItem] = []
    for row in payload["items"]:
        source_id = str(row["source_id"])
        fixture_dir = REPO_ROOT / str(row["fixture_dir"])
        gold_path = fixture_dir / str(row.get("gold_file") or "expected.json")
        items.append(
            GoldItem(
                source_id=source_id,
                fixture_dir=fixture_dir,
                gold_path=gold_path,
                parser_key=str(row["parser_key"]),
                source_files=tuple(row.get("source_files") or ()),
                scoring=str(row.get("scoring") or "adapter"),
                now=_parse_now(row.get("now")),
                extra_config=dict(row.get("job_config") or {}),
            )
        )
    return GoldManifest(items=tuple(items))


def _job_for(item: GoldItem) -> ParserJob:
    config: dict[str, Any] = {
        "timezone": "Europe/Minsk",
        "kind": "public_skate",
        "prices_already_minor": True,
        "fixture_dir": str(item.fixture_dir),
        "requires_by_egress": item.scoring == "blocked_empty",
    }
    if item.parser_key == PARSER_KEY_MINSK_ARENA:
        config = dict(MINSK_ARENA_SALEFRAME_CONFIG)
        config["fixture_dir"] = str(item.fixture_dir)
    config.update(item.extra_config)
    gold = json.loads(item.gold_path.read_text(encoding="utf-8"))
    arena_id = int(gold.get("arena_id") or 0)
    return ParserJob(
        id=arena_id or 1,
        arena_id=arena_id or 1,
        parser_key=item.parser_key,
        is_enabled=item.scoring == "adapter",
        cadence="daily",
        next_run_at=item.now,
        last_run_at=None,
        config=config,
    )


async def _predict(item: GoldItem) -> list[PredictedSlot]:
    parser = default_registry().get(item.parser_key)
    if parser is None:
        return []
    job = _job_for(item)
    extraction = await parser.extract(job)
    drafts = IceSessionNormalizer().normalize(extraction, job, now=item.now)
    validated = IceSessionValidator().validate(drafts)
    return predicted_from_drafts(validated)


async def run_calibration(*, manifest: GoldManifest | None = None) -> CalibrationReport:
    gold_manifest = manifest or load_gold_manifest()
    scores: list[SourceScore] = []
    for item in gold_manifest.items:
        payload = json.loads(item.gold_path.read_text(encoding="utf-8"))
        gold = gold_slots_from_expected(payload)
        predicted = await _predict(item)
        metrics = compare_slots(gold, predicted)
        scores.append(
            score_source(item.source_id, metrics, parser_key=item.parser_key, scoring=item.scoring)
        )
    return CalibrationReport(sources=tuple(scores), overall=merge_metrics(row.metrics for row in scores))


def _fmt(metrics: SlotMetrics) -> str:
    return (
        f"recall={metrics.recall:.4f} precision={metrics.precision:.4f} "
        f"price={metrics.price_accuracy:.4f} kind={metrics.kind_accuracy:.4f} "
        f"gold={metrics.gold_count} pred={metrics.predicted_count}"
    )


def format_calibration_report(report: CalibrationReport) -> str:
    lines = ["Ice extract calibration (canonical ice_sessions)", f"overall  {_fmt(report.overall)}"]
    width = max(len(row.source_id) for row in report.sources) if report.sources else 0
    for row in report.sources:
        lines.append(f"  {row.source_id.ljust(width)}  {_fmt(row.metrics)}")
    return "\n".join(lines)


def _metrics_dict(metrics: SlotMetrics) -> dict[str, float | int]:
    return {
        "recall": metrics.recall,
        "precision": metrics.precision,
        "price_accuracy": metrics.price_accuracy,
        "kind_accuracy": metrics.kind_accuracy,
        "gold_count": metrics.gold_count,
        "predicted_count": metrics.predicted_count,
        "true_positives": metrics.true_positives,
        "false_negatives": metrics.false_negatives,
        "false_positives": metrics.false_positives,
        "excluded_ambiguous": metrics.excluded_ambiguous,
    }


def metrics_for_digest(report: CalibrationReport) -> dict[str, Any]:
    """Hook for TASK-062 weekly data-health digest. Numbers only — no bot copy."""
    return {
        "overall": _metrics_dict(report.overall),
        "by_source": {row.source_id: _metrics_dict(row.metrics) for row in report.sources},
    }


def assert_calibration_floors(report: CalibrationReport) -> None:
    _assert_floors("overall", report.overall, SCORE_FLOORS["overall"])
    for row in report.sources:
        floors = SCORE_FLOORS.get(row.source_id, SCORE_FLOORS["default"])
        _assert_floors(row.source_id, row.metrics, floors)


def _assert_floors(name: str, metrics: SlotMetrics, floors: dict[str, float]) -> None:
    for key, floor in floors.items():
        value = float(getattr(metrics, key))
        assert value + 1e-12 >= floor, f"{name} {key} {value:.4f} below floor {floor:.4f}"


async def _async_main(*, check: bool) -> int:
    report = await run_calibration()
    print(format_calibration_report(report))
    print(json.dumps(metrics_for_digest(report), ensure_ascii=False, indent=2))
    if check:
        assert_calibration_floors(report)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score Minsk MK adapters against the calibration gold set.")
    parser.add_argument("--check", action="store_true", help="exit non-zero if a metric drops below SCORE_FLOORS")
    args = parser.parse_args(argv)
    return asyncio.run(_async_main(check=args.check))


if __name__ == "__main__":
    raise SystemExit(main())
