"""TASK-329 AC3/AC6: восстановление волн по ice_scrape_runs, dry-run на фикстуре."""
from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from src.application.schedule_wave_backfill import RunPoint, detect_backfill_waves, is_growth

MINSK = ZoneInfo("Europe/Minsk")
SINCE = datetime(2026, 10, 6, tzinfo=MINSK)


def t(day: int, hour: int = 15, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=MINSK)


def runs(job_id: int, arena_id: int, points: list[tuple[datetime, int]], status: str = "ok") -> list[RunPoint]:
    return [
        RunPoint(
            run_id=job_id * 1000 + i,
            job_id=job_id,
            arena_id=arena_id,
            finished_at=moment,
            status=status if slots else "empty",
            slots_found=slots,
        )
        for i, (moment, slots) in enumerate(points)
    ]


@pytest.mark.parametrize(
    ("prev", "cur", "expected"),
    [
        (0, 1, True),  # 0 → N
        (0, 0, False),
        (10, 13, True),  # +3, 30%
        (10, 12, False),  # +2, 20%
        (3, 4, False),  # +1, 33%
        (5, 7, True),  # +2, 40%
        (10, 9, False),
    ],
)
def test_growth_rule(prev: int, cur: int, expected: bool) -> None:
    assert is_growth(prev, cur) is expected


def test_detector_merges_within_six_hours_and_respects_since() -> None:
    points = [
        (t(4), 0),
        (t(5), 7),  # до since — не волна
        (t(6), 0),
        (t(9, 15), 7),  # волна
        (t(9, 16), 0),
        (t(9, 17), 7),  # 2 ч после — сливается
        (t(10), 7),
        (t(16, 14), 7),
        (t(16, 15), 12),  # +5, 71% — волна
    ]
    waves = detect_backfill_waves(runs(1, 5, points), since=SINCE, until=t(24))
    assert waves == {5: [t(9, 15), t(16, 15)]}


def test_detector_skips_error_runs_and_keeps_jobs_apart() -> None:
    series = runs(1, 5, [(t(7), 0), (t(8), 6)]) + [
        RunPoint(run_id=99, job_id=1, arena_id=5, finished_at=t(8, 18), status="error", slots_found=0),
    ]
    # второе задание того же катка (ОХМ) с другим масштабом — не путается с первым
    series += runs(2, 5, [(t(7, 1), 40), (t(8, 1), 41), (t(12, 1), 41)])
    waves = detect_backfill_waves(series, since=SINCE, until=t(24))
    assert waves == {5: [t(8)]}


def test_detector_stops_at_live_start_per_arena() -> None:
    series = runs(1, 5, [(t(7), 0), (t(8), 6), (t(14), 0), (t(15), 6)])
    series += runs(2, 6, [(t(7), 0), (t(8), 6), (t(14), 0), (t(15), 6)])
    waves = detect_backfill_waves(series, since=SINCE, until=t(24), until_by_arena={5: t(10)})
    assert waves == {5: [t(8)], 6: [t(8), t(15)]}


def _load_script():
    path = Path(__file__).resolve().parents[2] / "scripts" / "backfill_schedule_waves.py"
    spec = importlib.util.spec_from_file_location("backfill_schedule_waves_t329", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


async def _arena_with_job(db_session) -> tuple[int, int]:
    cid = (await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))).scalar()
    if cid is None:
        cid = (
            await db_session.execute(
                text(
                    """
                    INSERT INTO cities (name, country, price_group, is_active)
                    VALUES (:n, 'BY', 'BY_BASE', true) RETURNING id
                    """
                ),
                {"n": f"RunCity-{uuid.uuid4().hex[:6]}"},
            )
        ).scalar_one()
    arena_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                VALUES (:cid, :n, 'ул. Журнальная, 1', true, true) RETURNING id
                """
            ),
            {"cid": int(cid), "n": f"Журнал {uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    job_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                VALUES (:a, :k, false, 'daily', now(), CAST(:cfg AS jsonb)) RETURNING id
                """
            ),
            {"a": arena_id, "k": f"t329_{uuid.uuid4().hex[:6]}", "cfg": json.dumps({})},
        )
    ).scalar_one()
    return int(arena_id), int(job_id)


async def _run_row(db_session, job_id: int, arena_id: int, moment: datetime, slots: int) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO ice_scrape_runs (job_id, arena_id, started_at, finished_at, status, slots_found)
            VALUES (:j, :a, :t, :t, :s, :n)
            """
        ),
        {"j": job_id, "a": arena_id, "t": moment, "s": "ok" if slots else "empty", "n": slots},
    )


@pytest.mark.asyncio
async def test_script_dry_run_prints_waves_and_writes_nothing(db_session) -> None:
    script = _load_script()
    arena_id, job_id = await _arena_with_job(db_session)
    for day in (9, 16, 23):  # три пятницы: 0 → 8 слотов
        await _run_row(db_session, job_id, arena_id, t(day - 1, 12), 0)
        await _run_row(db_session, job_id, arena_id, t(day, 15), 8)
    lines: list[str] = []
    levels = await script.run(
        db_session, since=SINCE, now=t(24, 20).astimezone(timezone.utc), apply=False, out=lines.append
    )
    mine = [line for line in lines if line.lstrip().startswith(f"{arena_id} ")]
    assert len(mine) == 1
    assert "waves=3 promise=day date=2026-10-30 week=next" in mine[0]
    assert "пт 09.10 15:00, пт 16.10 15:00, пт 23.10 15:00" in mine[0]
    assert levels["day"] >= 1
    assert lines[-1].startswith("dry-run")
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM ice_schedule_waves WHERE arena_id = :a"), {"a": arena_id}
        )
    ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_script_apply_is_idempotent_and_stops_at_seed(db_session) -> None:
    script = _load_script()
    arena_id, job_id = await _arena_with_job(db_session)
    for day in (9, 16, 23):
        await _run_row(db_session, job_id, arena_id, t(day - 1, 12), 0)
        await _run_row(db_session, job_id, arena_id, t(day, 15), 8)
    await db_session.execute(
        text("INSERT INTO ice_schedule_waves (arena_id, detected_at, source) VALUES (:a, :t, 'seed')"),
        {"a": arena_id, "t": t(20)},
    )
    now = t(24, 20).astimezone(timezone.utc)
    for _ in range(2):
        await script.run(db_session, since=SINCE, now=now, apply=True, out=lambda _line: None)
    rows = (
        await db_session.execute(
            text(
                """
                SELECT detected_at, source, horizon_before, horizon_after FROM ice_schedule_waves
                WHERE arena_id = :a ORDER BY detected_at
                """
            ),
            {"a": arena_id},
        )
    ).all()
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        (t(9, 15), "backfill", None, None),
        (t(16, 15), "backfill", None, None),
        (t(20), "seed", None, None),
    ]
