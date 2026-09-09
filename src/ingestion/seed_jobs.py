"""Idempotent Minsk ice_parser_jobs seed from census YAML + parser specs.

One arena = one job. Enable only ready MK specs without a BY-egress blocker.
TASK-071's Minsk Arena row is updated in place (unique arena_id).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.jobs import config_requires_by_egress
from src.ingestion.seed_config import saleframe_defaults_for

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = REPO_ROOT / "data/minsk-parser-registry.yaml"
DEFAULT_PARSERS_DIR = REPO_ROOT / "data/parsers"
DEFAULT_FIXTURES_DIR = REPO_ROOT / "data/fixtures"

SKIP_TARGETS = frozenset({"not_ice", "training_only"})
SKIP_STATUSES = frozenset({"skipped"})
DISABLED_STATUSES = frozenset({"blocked", "unknown", "partial"})
READY_STATUSES = frozenset({"ready", "ok"})

_HEADER = re.compile(r"^-\s*(arena_id|parser_key|cadence|requires_by_egress):\s*(.+?)\s*$", re.M)
_JSON_FENCE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)
_SCALAR_TRUE = frozenset({"true", "yes", "1"})
_SCALAR_FALSE = frozenset({"false", "no", "0"})
_SCALAR_NULL = frozenset({"null", "~", "none", ""})


@dataclass(frozen=True)
class JobSeed:
    arena_id: int
    parser_key: str
    cadence: str
    is_enabled: bool
    config: dict[str, Any]
    notes: str | None = None


@dataclass
class SeedReport:
    inserted: int = 0
    updated: int = 0
    skipped_missing_arena: int = 0


@dataclass(frozen=True)
class _SpecDraft:
    stem: str
    arena_id: int
    parser_key: str
    cadence: str
    requires_by_egress: bool
    config: dict[str, Any]


def _unquote(raw: str) -> Any:
    value = raw.strip()
    if value[:1] in {"'", '"'} and value[-1:] == value[:1] and len(value) >= 2:
        return value[1:-1]
    lowered = value.lower()
    if lowered in _SCALAR_NULL:
        return None
    if lowered in _SCALAR_TRUE:
        return True
    if lowered in _SCALAR_FALSE:
        return False
    try:
        return int(value)
    except ValueError:
        return value


def _parse_yaml_list(text: str) -> list[dict[str, Any]]:
    """Subset YAML loader for the Minsk census (list of mappings, nested lists)."""
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        lines.append(stripped)
    if not lines:
        return []
    items: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("- "):
            i += 1
            continue
        item, i = _parse_mapping_item(lines, i, item_indent=0)
        items.append(item)
    return items


def _parse_mapping_item(lines: list[str], i: int, *, item_indent: int) -> tuple[dict[str, Any], int]:
    line = lines[i]
    body = line[item_indent + 2 :]
    mapping: dict[str, Any] = {}
    if ":" in body:
        key, _, rest = body.partition(":")
        mapping[key.strip()] = _unquote(rest) if rest.strip() else _pending()
    i += 1
    child_indent = item_indent + 2
    while i < len(lines):
        nxt = lines[i]
        indent = len(nxt) - len(nxt.lstrip(" "))
        if indent < child_indent:
            break
        if nxt.lstrip().startswith("- ") and indent == child_indent:
            break
        if indent > child_indent and mapping:
            # nested block continues previous key
            last_key = next(reversed(mapping))
            nested, i = _parse_nested(lines, i, indent)
            mapping[last_key] = nested
            continue
        key, _, rest = nxt.strip().partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest:
            mapping[key] = _unquote(rest)
            i += 1
            continue
        nested, i = _parse_nested(lines, i + 1, child_indent + 2)
        mapping[key] = nested
    return mapping, i


def _pending() -> None:
    return None


def _parse_nested(lines: list[str], i: int, expected_indent: int) -> tuple[Any, int]:
    if i >= len(lines):
        return [], i
    indent = len(lines[i]) - len(lines[i].lstrip(" "))
    if indent < expected_indent:
        return [], i
    if lines[i].lstrip().startswith("- "):
        items: list[Any] = []
        list_indent = indent
        while i < len(lines):
            nxt = lines[i]
            nxt_indent = len(nxt) - len(nxt.lstrip(" "))
            if nxt_indent < list_indent:
                break
            if not nxt.lstrip().startswith("- ") or nxt_indent != list_indent:
                break
            body = nxt[list_indent + 2 :]
            if ":" in body:
                item, i = _parse_mapping_item(lines, i, item_indent=list_indent)
                items.append(item)
            else:
                items.append(_unquote(body))
                i += 1
        return items, i
    mapping: dict[str, Any] = {}
    map_indent = indent
    while i < len(lines):
        nxt = lines[i]
        nxt_indent = len(nxt) - len(nxt.lstrip(" "))
        if nxt_indent < map_indent:
            break
        if nxt.lstrip().startswith("- "):
            break
        key, _, rest = nxt.strip().partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest:
            mapping[key] = _unquote(rest)
            i += 1
        else:
            nested, i = _parse_nested(lines, i + 1, map_indent + 2)
            mapping[key] = nested
    return mapping, i


def load_minsk_parser_registry(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or DEFAULT_REGISTRY_PATH
    return _parse_yaml_list(target.read_text(encoding="utf-8"))


def _parse_spec(path: Path) -> _SpecDraft | None:
    text = path.read_text(encoding="utf-8")
    headers: dict[str, str] = {}
    for match in _HEADER.finditer(text):
        headers[match.group(1)] = match.group(2).strip()
    parser_key = headers.get("parser_key")
    arena_raw = headers.get("arena_id")
    if not parser_key or not arena_raw:
        return None
    cadence = headers.get("cadence", "daily").strip()
    if cadence not in {"hourly", "daily", "weekly"}:
        cadence = "daily"
    by_raw = headers.get("requires_by_egress", "false")
    requires_by = str(by_raw).strip().lower() in _SCALAR_TRUE
    config: dict[str, Any] = {}
    fence = _JSON_FENCE.search(text)
    if fence:
        config = json.loads(fence.group(1))
    if "requires_by_egress" not in config:
        config["requires_by_egress"] = requires_by
    return _SpecDraft(
        stem=path.stem,
        arena_id=int(arena_raw),
        parser_key=parser_key,
        cadence=cadence,
        requires_by_egress=requires_by,
        config=config,
    )


def load_minsk_parser_specs(parsers_dir: Path | None = None) -> list[_SpecDraft]:
    directory = parsers_dir or DEFAULT_PARSERS_DIR
    drafts: list[_SpecDraft] = []
    for path in sorted(directory.glob("minsk-*.md")):
        draft = _parse_spec(path)
        if draft is not None:
            drafts.append(draft)
    return drafts


def _fixture_expected(fixtures_dir: Path, stem: str) -> bool:
    return (fixtures_dir / stem / "expected.json").is_file()


def _job_enabled(spec: _SpecDraft, entry: dict[str, Any] | None, *, fixture_ok: bool) -> bool:
    if spec.requires_by_egress or config_requires_by_egress(spec.config):
        return False
    if not fixture_ok:
        return False
    if entry is None:
        return True
    target = str(entry.get("target") or "")
    if target in SKIP_TARGETS:
        return False
    status = str(entry.get("parser_status") or "")
    if status in SKIP_STATUSES or status in DISABLED_STATUSES:
        return False
    if status and status not in READY_STATUSES:
        return False
    return True


def build_minsk_job_seeds(
    *,
    registry_path: Path | None = None,
    parsers_dir: Path | None = None,
    fixtures_dir: Path | None = None,
) -> list[JobSeed]:
    fixtures = fixtures_dir or DEFAULT_FIXTURES_DIR
    registry = {int(item["arena_id"]): item for item in load_minsk_parser_registry(registry_path) if "arena_id" in item}
    seeds: list[JobSeed] = []
    for spec in load_minsk_parser_specs(parsers_dir):
        entry = registry.get(spec.arena_id)
        if entry is not None:
            target = str(entry.get("target") or "")
            status = str(entry.get("parser_status") or "")
            if target in SKIP_TARGETS or status in SKIP_STATUSES:
                continue
        fixture_ok = _fixture_expected(fixtures, spec.stem)
        config = dict(spec.config)
        defaults = saleframe_defaults_for(spec.parser_key)
        if defaults is not None:
            merged = dict(defaults)
            merged.update(config)
            config = merged
        enabled = _job_enabled(spec, entry, fixture_ok=fixture_ok)
        seeds.append(
            JobSeed(
                arena_id=spec.arena_id,
                parser_key=spec.parser_key,
                cadence=spec.cadence,
                is_enabled=enabled,
                config=config,
                notes=f"TASK-065 seed: {spec.stem} / {spec.parser_key}",
            )
        )
    return seeds


async def upsert_ice_parser_jobs(
    session: AsyncSession,
    seeds: list[JobSeed],
    *,
    now: datetime | None = None,
) -> SeedReport:
    """Insert or update one ice_parser_jobs row per arena_id. Never duplicates."""
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    report = SeedReport()
    for seed in seeds:
        exists_arena = (
            await session.execute(text("SELECT 1 FROM arenas WHERE id = :id"), {"id": seed.arena_id})
        ).scalar()
        if exists_arena is None:
            report.skipped_missing_arena += 1
            continue
        existing = (
            await session.execute(
                text("SELECT id FROM ice_parser_jobs WHERE arena_id = :id"),
                {"id": seed.arena_id},
            )
        ).scalar()
        payload = {
            "arena_id": seed.arena_id,
            "parser_key": seed.parser_key,
            "is_enabled": seed.is_enabled,
            "cadence": seed.cadence,
            "config": json.dumps(seed.config, ensure_ascii=False),
            "notes": seed.notes,
        }
        if existing is None:
            await session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs (
                        arena_id, parser_key, is_enabled, cadence, next_run_at, config, notes
                    ) VALUES (
                        :arena_id, :parser_key, :is_enabled, :cadence, :next_run_at,
                        CAST(:config AS jsonb), :notes
                    )
                    """
                ),
                {**payload, "next_run_at": clock},
            )
            report.inserted += 1
        else:
            await session.execute(
                text(
                    """
                    UPDATE ice_parser_jobs
                    SET parser_key = :parser_key,
                        is_enabled = :is_enabled,
                        cadence = :cadence,
                        config = CAST(:config AS jsonb),
                        notes = :notes
                    WHERE arena_id = :arena_id
                    """
                ),
                payload,
            )
            report.updated += 1
    return report
