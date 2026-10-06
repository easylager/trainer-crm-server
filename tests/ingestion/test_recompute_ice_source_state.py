"""TASK-178 п.2: разовый пересчёт состояния источников по истории ice_scrape_runs."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from src.ingestion.freshness import replay_source_state
from src.ingestion.types import ScrapeRunRecord, SourceState

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "recompute_ice_source_state.py"
_NOW = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


def _load_mod():
    spec = importlib.util.spec_from_file_location("recompute_ice_source_state", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _rec(status: str, at: datetime, *, slots: int = 0, dropped: int = 0, code: str | None = None):
    return ScrapeRunRecord(
        job_id=1,
        arena_id=1,
        parser_key="",
        status=status,
        slot_count=slots,
        slots_dropped=dropped,
        error_message=None,
        started_at=at,
        finished_at=at,
        error_code=code,
    )


def test_replay_ignores_input_order_and_keeps_series_through_empty_storefront() -> None:
    runs = [
        _rec("empty", _NOW - timedelta(hours=1), dropped=7),
        _rec("error", _NOW - timedelta(hours=3), code="extract_error"),
        _rec("ok", _NOW - timedelta(hours=5), slots=4),
        _rec("error", _NOW - timedelta(hours=2), code="extract_error"),
    ]
    st = replay_source_state(runs, shown_sessions=0)
    assert st.last_ok_at == _NOW - timedelta(hours=5)
    assert st.failure_streak == 2
    assert st.failing_since == _NOW - timedelta(hours=3)
    assert st.last_error_code == "empty_after_filter"
    assert replay_source_state([], shown_sessions=0, start=SourceState(failure_streak=1)).failure_streak == 1


async def _job(db_session, arena_id: int, key: str, *, alert_state: str, streak: int = 0) -> int:
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at,
                        config, created_at, alert_state, failure_streak)
                    VALUES (:aid, :key, true, 'daily', :next, '{}'::jsonb, :created, :alert, :streak)
                    RETURNING id
                    """
                ),
                {
                    "aid": arena_id,
                    "key": key,
                    "next": _NOW + timedelta(hours=1),
                    "created": _NOW - timedelta(days=30),
                    "alert": alert_state,
                    "streak": streak,
                },
            )
        ).scalar_one()
    )


async def _runs(db_session, job_id: int, arena_id: int, rows: list[tuple[str, datetime, int, int]]) -> None:
    for status, at, found, dropped in rows:
        await db_session.execute(
            text(
                """
                INSERT INTO ice_scrape_runs (job_id, arena_id, started_at, finished_at, status,
                    slots_found, slots_dropped)
                VALUES (:jid, :aid, :at, :at, :status, :found, :dropped)
                """
            ),
            {"jid": job_id, "aid": arena_id, "at": at, "status": status, "found": found, "dropped": dropped},
        )


@pytest.mark.asyncio
async def test_plan_flips_never_ok_source_and_clears_healthy_one(db_session) -> None:
    mod = _load_mod()
    await db_session.execute(text("UPDATE ice_parser_jobs SET is_enabled = false, alert_state = 'ok'"))
    city = (
        await db_session.execute(
            text(
                "INSERT INTO cities (name, country, price_group, is_active, sort_order) "
                "VALUES ('RecomputeCity', 'BY', 'BY_BASE', true, 9320) RETURNING id"
            )
        )
    ).scalar_one()
    arenas = []
    for name in ("Витебск-тест", "Брест-тест"):
        arenas.append(
            int(
                (
                    await db_session.execute(
                        text(
                            "INSERT INTO arenas (city_id, name, address, is_active, is_confirmed) "
                            "VALUES (:cid, :n, 'ул. 1', true, true) RETURNING id"
                        ),
                        {"cid": city, "n": name},
                    )
                ).scalar_one()
            )
        )
    # «Витебск»: на сайте только прошлый сезон — каждые 45 мин empty, ни одного ok.
    vitebsk = await _job(db_session, arenas[0], "recompute_vitebsk_v1", alert_state="ok")
    await _runs(
        db_session,
        vitebsk,
        arenas[0],
        [("empty", _NOW - timedelta(hours=h), 0, 7) for h in range(1, 20, 2)],
    )
    # «Брест»: все прогоны ok, свежий — 30 минут назад; alert_state застрял в failing.
    brest = await _job(db_session, arenas[1], "recompute_brest_v1", alert_state="failing", streak=3)
    await _runs(
        db_session,
        brest,
        arenas[1],
        [("ok", _NOW - timedelta(minutes=30 + 45 * i), 12, 0) for i in range(5)],
    )

    plans = {p.row.job_id: p for p in await mod.build_plan(db_session, now=_NOW)}
    assert plans[vitebsk].alert_after == "failing"
    assert plans[vitebsk].state.last_error_code == "empty_after_filter"
    assert (plans[vitebsk].ok_7d, plans[vitebsk].runs_7d) == (0, 10)
    assert plans[brest].alert_after == "ok"
    assert plans[brest].state.failure_streak == 0
    assert (plans[brest].ok_7d, plans[brest].runs_7d) == (5, 5)

    await mod.apply_plan(db_session, list(plans.values()), silent=True)
    rows = {
        int(r.id): r
        for r in (
            await db_session.execute(
                text(
                    "SELECT id, alert_state, alert_sent_at, failure_streak, last_error_code, last_ok_at "
                    "FROM ice_parser_jobs WHERE id IN (:a, :b)"
                ),
                {"a": vitebsk, "b": brest},
            )
        )
    }
    assert (rows[vitebsk].alert_state, rows[vitebsk].alert_sent_at) == ("failing", None)
    assert rows[vitebsk].last_error_code == "empty_after_filter"
    assert (rows[brest].alert_state, rows[brest].failure_streak) == ("ok", 0)
    assert rows[brest].last_ok_at == _NOW - timedelta(minutes=30)
