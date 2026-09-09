"""TASK-065: idempotent import of Minsk ice_parser_jobs from registry + specs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from src.ingestion.jobs import InMemoryParserJobStore, job_from_row
from src.ingestion.parsers import ParserRegistry
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import InMemoryScrapeRunRecorder
from src.ingestion.seed_config import MINSK_ARENA_SALEFRAME_CONFIG, PARSER_KEY_MINSK_ARENA
from src.ingestion.seed_jobs import (
    REPO_ROOT,
    JobSeed,
    build_minsk_job_seeds,
    upsert_ice_parser_jobs,
)
from tests.ingestion.fakes import RecordingParser

_NOW = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
_FIXTURE_REGISTRY = """
- arena_id: {ready_id}
  name: "Ready Rink"
  target: mass_skating
  parser_status: ready
  extractor: ready_html_v1
  sources:
    - url: https://ready.example/ice
      role: schedule

- arena_id: {by_id}
  name: "BY Blocked Rink"
  target: mass_skating
  parser_status: blocked
  extractor: by_html_v1
  blockers:
    - "geo_ip_nginx needs BY egress"
  sources:
    - url: https://by.example/ice
      role: schedule
      http_status: 403
      fetch_ok: false

- arena_id: {skip_id}
  name: "Лыжероллерная трасса"
  target: not_ice
  parser_status: skipped
  extractor: null
  blockers:
    - "not a mass-skating target (not_ice)"

- arena_id: {train_id}
  name: "JUSTSKATE"
  target: training_only
  parser_status: skipped
  extractor: null
"""

_READY_SPEC = """
# Parser spec: Ready Rink

- arena_id: {arena_id}
- parser_key: ready_html_v1
- cadence: daily
- requires_by_egress: false

## Sources

- job.config JSON (черновик):

```json
{{
  "url": "https://ready.example/ice",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "requires_by_egress": false
}}
```
"""

_BY_SPEC = """
# Parser spec: BY Blocked Rink

- arena_id: {arena_id}
- parser_key: by_html_v1
- cadence: weekly
- requires_by_egress: true

## Sources

- job.config JSON (черновик):

```json
{{
  "url": "https://by.example/ice",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "requires_by_egress": true
}}
```
"""


def _write_census(tmp_path: Path, *, ready_id: int, by_id: int, skip_id: int, train_id: int) -> tuple[Path, Path, Path]:
    registry = tmp_path / "minsk-parser-registry.yaml"
    registry.write_text(
        _FIXTURE_REGISTRY.format(ready_id=ready_id, by_id=by_id, skip_id=skip_id, train_id=train_id),
        encoding="utf-8",
    )
    parsers = tmp_path / "parsers"
    parsers.mkdir()
    (parsers / "minsk-ready.md").write_text(_READY_SPEC.format(arena_id=ready_id), encoding="utf-8")
    (parsers / "minsk-blocked.md").write_text(_BY_SPEC.format(arena_id=by_id), encoding="utf-8")
    fixtures = tmp_path / "fixtures"
    (fixtures / "minsk-ready").mkdir(parents=True)
    (fixtures / "minsk-ready" / "expected.json").write_text('{"sessions":[{"kind":"public_skate"}]}', encoding="utf-8")
    (fixtures / "minsk-blocked").mkdir()
    (fixtures / "minsk-blocked" / "expected.json").write_text(
        '{"sessions":[],"blocked_without_by_egress":true}',
        encoding="utf-8",
    )
    return registry, parsers, fixtures


def test_ready_spec_seeds_enabled_job_with_spec_url(tmp_path: Path) -> None:
    """AC-001: spec with parser_key becomes a job; URL comes from spec, not the scheduler."""
    registry, parsers, fixtures = _write_census(tmp_path, ready_id=101, by_id=102, skip_id=103, train_id=104)
    seeds = build_minsk_job_seeds(registry_path=registry, parsers_dir=parsers, fixtures_dir=fixtures)
    by_key = {seed.parser_key: seed for seed in seeds}
    ready = by_key["ready_html_v1"]
    assert ready.arena_id == 101
    assert ready.is_enabled is True
    assert ready.config["url"] == "https://ready.example/ice"
    sched_src = Path("src/ingestion/scheduler.py").read_text(encoding="utf-8")
    assert "ready.example" not in sched_src
    assert "saleframe.minskarena.by" not in sched_src


def test_requires_by_egress_seed_is_disabled(tmp_path: Path) -> None:
    """AC-002: BY-egress jobs are created disabled."""
    registry, parsers, fixtures = _write_census(tmp_path, ready_id=101, by_id=102, skip_id=103, train_id=104)
    seeds = build_minsk_job_seeds(registry_path=registry, parsers_dir=parsers, fixtures_dir=fixtures)
    by_job = next(seed for seed in seeds if seed.parser_key == "by_html_v1")
    assert by_job.is_enabled is False
    assert by_job.config["requires_by_egress"] is True


@pytest.mark.asyncio
async def test_disabled_by_egress_seed_is_not_run_by_scheduler(tmp_path: Path) -> None:
    """AC-002: scheduler never extracts a disabled BY-egress job."""
    registry, parsers, fixtures = _write_census(tmp_path, ready_id=101, by_id=102, skip_id=103, train_id=104)
    seed = next(
        item
        for item in build_minsk_job_seeds(registry_path=registry, parsers_dir=parsers, fixtures_dir=fixtures)
        if item.parser_key == "by_html_v1"
    )
    recording = RecordingParser()
    job = job_from_row(
        type(
            "Row",
            (),
            {
                "id": 9,
                "arena_id": seed.arena_id,
                "parser_key": recording.parser_key,
                "is_enabled": seed.is_enabled,
                "cadence": seed.cadence,
                "next_run_at": _NOW - timedelta(hours=1),
                "last_run_at": None,
                "config": seed.config,
                "notes": seed.notes,
            },
        )()
    )
    store = InMemoryParserJobStore([job])
    recorder = InMemoryScrapeRunRecorder()
    registry_obj = ParserRegistry()
    registry_obj.register(recording)
    await IceIngestScheduler(store=store, recorder=recorder, registry=registry_obj).run_due(_NOW)
    assert recording.seen_configs == []
    assert recorder.runs == []


def test_skip_arenas_do_not_get_enabled_jobs(tmp_path: Path) -> None:
    """AC-004: not-MK / skipped census rows never become enabled jobs."""
    registry, parsers, fixtures = _write_census(tmp_path, ready_id=101, by_id=102, skip_id=103, train_id=104)
    seeds = build_minsk_job_seeds(registry_path=registry, parsers_dir=parsers, fixtures_dir=fixtures)
    enabled_ids = {seed.arena_id for seed in seeds if seed.is_enabled}
    all_ids = {seed.arena_id for seed in seeds}
    assert 103 not in enabled_ids
    assert 104 not in enabled_ids
    assert 103 not in all_ids
    assert 104 not in all_ids


def test_real_minsk_registry_seeds_spec_jobs() -> None:
    """AC-001 against the on-disk Minsk census + parser specs."""
    seeds = build_minsk_job_seeds()
    by_key = {seed.parser_key: seed for seed in seeds}

    arena = by_key[PARSER_KEY_MINSK_ARENA]
    assert arena.is_enabled is True
    assert arena.config["url"] == MINSK_ARENA_SALEFRAME_CONFIG["url"]
    assert arena.config["service_id"] == 55
    assert arena.config["prices_already_minor"] is True
    assert arena.cadence == "daily"

    oval = by_key["minskarena_speed_oval_v1"]
    assert oval.is_enabled is True
    assert oval.arena_id == 115
    assert oval.config["service_id"] == 139
    assert oval.config["rental_service_id"] == 138
    assert oval.config["adult_zone_id"] == 1008

    assert by_key["zamok_html_v1"].is_enabled is True
    assert by_key["zamok_html_v1"].config["url"] == "https://tczamok.by/entertainments/ice-rink"
    assert by_key["chizhovka_html_v1"].is_enabled is True
    assert "schedule_url" in by_key["chizhovka_html_v1"].config
    assert by_key["ledby_html_v1"].is_enabled is True

    junost = by_key["junost_origin_html_v1"]
    ledlife = by_key["ledlife_origin_html_v1"]
    assert junost.is_enabled is False
    assert ledlife.is_enabled is False
    assert junost.config["requires_by_egress"] is True
    assert ledlife.config["requires_by_egress"] is True

    enabled_ids = {seed.arena_id for seed in seeds if seed.is_enabled}
    assert 12 not in enabled_ids
    assert 13 not in enabled_ids
    assert 14 not in enabled_ids
    assert 9 not in enabled_ids


async def _insert_arena(db_session, name: str) -> int:
    city = (await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))).scalar()
    if city is None:
        pytest.skip("need seed cities")
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                    VALUES (:cid, :name, 'ул. Тестовая, 1', true, true)
                    RETURNING id
                    """
                ),
                {"cid": int(city), "name": name},
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_upsert_import_is_idempotent_per_arena(db_session, tmp_path: Path) -> None:
    """AC-001 + AC-003: import writes one row per spec; a second pass does not duplicate."""
    ready_id = await _insert_arena(db_session, "Лёд-065-ready")
    by_id = await _insert_arena(db_session, "Лёд-065-by")
    skip_id = await _insert_arena(db_session, "Лёд-065-skip")
    train_id = await _insert_arena(db_session, "Лёд-065-train")
    await db_session.flush()
    registry, parsers, fixtures = _write_census(
        tmp_path, ready_id=ready_id, by_id=by_id, skip_id=skip_id, train_id=train_id
    )
    seeds = build_minsk_job_seeds(registry_path=registry, parsers_dir=parsers, fixtures_dir=fixtures)
    first = await upsert_ice_parser_jobs(db_session, seeds, now=_NOW)
    second = await upsert_ice_parser_jobs(db_session, seeds, now=_NOW + timedelta(hours=1))
    await db_session.flush()

    rows = (
        await db_session.execute(
            text(
                """
                SELECT arena_id, parser_key, is_enabled, cadence, config
                FROM ice_parser_jobs
                WHERE arena_id IN (:a, :b)
                ORDER BY arena_id
                """
            ),
            {"a": ready_id, "b": by_id},
        )
    ).fetchall()
    assert first.inserted >= 2
    assert second.inserted == 0
    assert second.updated >= 2
    assert len(rows) == 2
    by_arena = {int(row.arena_id): row for row in rows}
    assert by_arena[ready_id].parser_key == "ready_html_v1"
    assert by_arena[ready_id].is_enabled is True
    assert by_arena[ready_id].config["url"] == "https://ready.example/ice"
    assert by_arena[by_id].is_enabled is False
    assert by_arena[by_id].config["requires_by_egress"] is True
    skip_count = (
        await db_session.execute(
            text("SELECT count(*) FROM ice_parser_jobs WHERE arena_id IN (:s, :t)"),
            {"s": skip_id, "t": train_id},
        )
    ).scalar_one()
    assert int(skip_count) == 0


@pytest.mark.asyncio
async def test_existing_minsk_arena_job_is_updated_not_duplicated(db_session) -> None:
    """EDGE-001: TASK-071 unique arena_id seed is upserted, not a second row."""
    arena_id = await _insert_arena(db_session, "Минск Арена")
    await db_session.execute(
        text(
            """
            INSERT INTO ice_parser_jobs
                (arena_id, parser_key, is_enabled, cadence, next_run_at, config, notes)
            VALUES
                (:aid, :pkey, true, 'daily', :next_run, CAST(:cfg AS jsonb), 'TASK-071 seed')
            """
        ),
        {
            "aid": arena_id,
            "pkey": PARSER_KEY_MINSK_ARENA,
            "next_run": _NOW,
            "cfg": '{"url": "https://stale.example/old", "service_id": 55}',
        },
    )
    await db_session.flush()

    seed = JobSeed(
        arena_id=arena_id,
        parser_key=PARSER_KEY_MINSK_ARENA,
        cadence="daily",
        is_enabled=True,
        config=dict(MINSK_ARENA_SALEFRAME_CONFIG),
        notes="TASK-065 seed: Minsk Arena saleframe/55",
    )
    report = await upsert_ice_parser_jobs(db_session, [seed], now=_NOW)
    await db_session.flush()
    rows = (
        await db_session.execute(
            text("SELECT parser_key, config, notes FROM ice_parser_jobs WHERE arena_id = :aid"),
            {"aid": arena_id},
        )
    ).fetchall()
    assert report.inserted == 0
    assert report.updated == 1
    assert len(rows) == 1
    assert rows[0].config["url"] == MINSK_ARENA_SALEFRAME_CONFIG["url"]
    assert rows[0].config["api_host"] == "https://abws.minskarena.by"


def test_repo_paths_point_at_canonical_minsk_arena_spec() -> None:
    assert (REPO_ROOT / "data/parsers/minsk-arena.md").is_file()
    assert (REPO_ROOT / "data/minsk-parser-registry.yaml").is_file()
    assert not (REPO_ROOT / "data/parsers/minsk-minskarena.md").exists()
