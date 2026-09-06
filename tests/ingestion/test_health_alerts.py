"""TASK-062: silent-source alerts, stale facts, city tier share, weekly digest."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from src.application.admin_analytics_use_cases import get_admin_product_analytics
from src.application.arena_profile import ensure_arena_profile
from src.ingestion.health import (
    DEFAULT_SILENCE_MULTIPLES,
    DEFAULT_STALE_SHARE_THRESHOLD,
    calibration_summary,
    city_booking_density,
    city_tier_shares,
    detect_silent_jobs,
    ice_health_snapshot,
    silence_threshold,
    stale_session_share_by_city,
)
from src.ingestion.alerts import (
    format_silent_sources_alert,
    format_weekly_digest,
    price_totals_grouped_by_currency,
)
from src.ingestion.types import RUN_STATUS_EMPTY, RUN_STATUS_OK
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id

_NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]


async def _city(db_session, name: str) -> int:
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO cities (name, country, price_group, is_active, sort_order)
                    VALUES (:name, 'BY', 'BY_BASE', true, 9100)
                    RETURNING id
                    """
                ),
                {"name": name},
            )
        ).scalar_one()
    )


async def _arena(db_session, city_id: int, name: str, *, phone: str | None = None) -> int:
    arena_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                    VALUES (:cid, :name, 'ул. Тестовая, 1', true, true)
                    RETURNING id
                    """
                ),
                {"cid": city_id, "name": name},
            )
        ).scalar_one()
    )
    await ensure_arena_profile(db_session, arena_id, city_id=city_id, name=name)
    if phone:
        await db_session.execute(
            text("UPDATE arena_profiles SET phone = :phone WHERE arena_id = :id"),
            {"phone": phone, "id": arena_id},
        )
    return arena_id


async def _job_row(
    db_session,
    arena_id: int,
    parser_key: str,
    *,
    cadence: str = "daily",
    enabled: bool = True,
    config: dict | None = None,
    created_at: datetime | None = None,
) -> int:
    created = created_at or (_NOW - timedelta(days=14))
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs
                        (arena_id, parser_key, is_enabled, cadence, next_run_at, config, created_at)
                    VALUES
                        (:aid, :pkey, :en, :cadence, :next_run, CAST(:config AS jsonb), :created)
                    RETURNING id
                    """
                ),
                {
                    "aid": arena_id,
                    "pkey": parser_key,
                    "en": enabled,
                    "cadence": cadence,
                    "next_run": _NOW,
                    "config": json.dumps(config or {}),
                    "created": created,
                },
            )
        ).scalar_one()
    )


async def _insert_run(
    db_session,
    job_id: int,
    arena_id: int,
    *,
    status: str,
    finished_at: datetime,
) -> int:
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_scrape_runs (
                        job_id, arena_id, started_at, finished_at, status
                    ) VALUES (
                        :job_id, :arena_id, :started, :finished, :status
                    )
                    RETURNING id
                    """
                ),
                {
                    "job_id": job_id,
                    "arena_id": arena_id,
                    "started": finished_at - timedelta(seconds=5),
                    "finished": finished_at,
                    "status": status,
                },
            )
        ).scalar_one()
    )


async def _insert_session(
    db_session,
    arena_id: int,
    *,
    starts_at: datetime,
    ends_at: datetime | None = None,
    valid_until: datetime | None = None,
    currency: str = "BYN",
    source_id: str | None = None,
    observed_at: datetime | None = None,
    price_adult_minor: int | None = None,
) -> int:
    ends = ends_at or (starts_at + timedelta(minutes=45))
    local_date = starts_at.astimezone(timezone.utc).date()
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_sessions (
                        arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                        starts_at_local, ends_at_local, currency_code, status,
                        valid_until, source_id, observed_at, price_adult_minor
                    ) VALUES (
                        :aid, 'public_skate', :starts, :ends, :ldate,
                        :stime, :etime, :cur, 'active',
                        :vu, :sid, :obs, :price
                    )
                    RETURNING id
                    """
                ),
                {
                    "aid": arena_id,
                    "starts": starts_at,
                    "ends": ends,
                    "ldate": local_date,
                    "stime": starts_at.timetz().replace(tzinfo=None),
                    "etime": ends.timetz().replace(tzinfo=None),
                    "cur": currency,
                    "vu": valid_until,
                    "sid": source_id,
                    "obs": observed_at,
                    "price": price_adult_minor,
                },
            )
        ).scalar_one()
    )


# ── AC-001 / EDGE-001 ─────────────────────────────────────────────────────


def test_default_silence_threshold_is_cadence_times_two() -> None:
    assert silence_threshold("hourly", {}) == timedelta(hours=2)
    assert silence_threshold("daily", {}) == timedelta(days=2)
    assert silence_threshold("weekly", {}) == timedelta(weeks=2)
    assert DEFAULT_SILENCE_MULTIPLES == 2


def test_per_job_silence_hours_override_for_seasonal_rink() -> None:
    """EDGE-001: monthly/seasonal source must not use the 2×daily default."""
    assert silence_threshold("daily", {"silence_ok_hours": 720}) == timedelta(hours=720)
    assert silence_threshold("weekly", {"silence_ok_multiples": 4}) == timedelta(weeks=4)


@pytest.mark.asyncio
async def test_silent_job_with_empty_runs_and_no_errors_raises_alert(db_session) -> None:
    """AC-001: no valid ok longer than threshold still alerts even if runs did not error."""
    city_id = await _city(db_session, "IceHealth-silent")
    arena_id = await _arena(db_session, city_id, "Каток-тихий")
    job_id = await _job_row(db_session, arena_id, "silent_v1", cadence="daily")
    await _insert_run(
        db_session, job_id, arena_id, status=RUN_STATUS_EMPTY, finished_at=_NOW - timedelta(hours=1)
    )
    await _insert_run(
        db_session, job_id, arena_id, status=RUN_STATUS_EMPTY, finished_at=_NOW - timedelta(hours=25)
    )
    await _insert_run(
        db_session,
        job_id,
        arena_id,
        status=RUN_STATUS_OK,
        finished_at=_NOW - timedelta(days=3),
    )
    await db_session.flush()

    silent = await detect_silent_jobs(db_session, now=_NOW)
    by_job = {row.job_id: row for row in silent}
    assert job_id in by_job
    row = by_job[job_id]
    assert row.last_ok_at == _NOW - timedelta(days=3)
    assert row.success_rate_7d is not None
    assert row.success_rate_30d is not None
    text_body = format_silent_sources_alert(silent)
    assert "Каток-тихий" in text_body
    assert "7д" in text_body or "7d" in text_body.lower() or "%" in text_body


@pytest.mark.asyncio
async def test_recent_ok_is_not_silent(db_session) -> None:
    city_id = await _city(db_session, "IceHealth-fresh")
    arena_id = await _arena(db_session, city_id, "Каток-свежий")
    job_id = await _job_row(db_session, arena_id, "fresh_v1")
    await _insert_run(
        db_session, job_id, arena_id, status=RUN_STATUS_OK, finished_at=_NOW - timedelta(hours=3)
    )
    await db_session.flush()

    silent = await detect_silent_jobs(db_session, now=_NOW)
    assert all(row.job_id != job_id for row in silent)


@pytest.mark.asyncio
async def test_disabled_job_is_not_silent(db_session) -> None:
    city_id = await _city(db_session, "IceHealth-off")
    arena_id = await _arena(db_session, city_id, "Каток-выкл")
    job_id = await _job_row(db_session, arena_id, "off_v1", enabled=False)
    await _insert_run(
        db_session, job_id, arena_id, status=RUN_STATUS_EMPTY, finished_at=_NOW - timedelta(days=10)
    )
    await db_session.flush()

    silent = await detect_silent_jobs(db_session, now=_NOW)
    assert all(row.job_id != job_id for row in silent)


@pytest.mark.asyncio
async def test_seasonal_config_keeps_monthly_job_quiet(db_session) -> None:
    city_id = await _city(db_session, "IceHealth-season")
    arena_id = await _arena(db_session, city_id, "Каток-сезон")
    job_id = await _job_row(
        db_session,
        arena_id,
        "season_v1",
        cadence="daily",
        config={"silence_ok_hours": 720},
    )
    await _insert_run(
        db_session, job_id, arena_id, status=RUN_STATUS_OK, finished_at=_NOW - timedelta(days=10)
    )
    await db_session.flush()

    silent = await detect_silent_jobs(db_session, now=_NOW)
    assert all(row.job_id != job_id for row in silent)


# ── stale facts ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stale_session_share_alerts_when_city_over_threshold(db_session) -> None:
    city_id = await _city(db_session, "IceHealth-stale")
    arena_id = await _arena(db_session, city_id, "Каток-просрочка")
    future = _NOW + timedelta(days=1)
    await _insert_session(
        db_session,
        arena_id,
        starts_at=future,
        valid_until=_NOW - timedelta(hours=2),
    )
    await _insert_session(
        db_session,
        arena_id,
        starts_at=future + timedelta(hours=2),
        valid_until=_NOW + timedelta(days=2),
    )
    await db_session.flush()

    rows = await stale_session_share_by_city(
        db_session, now=_NOW, threshold=DEFAULT_STALE_SHARE_THRESHOLD
    )
    by_city = {row.city_id: row for row in rows}
    assert city_id in by_city
    row = by_city[city_id]
    assert row.stale_count == 1
    assert row.total_count == 2
    assert row.stale_share == 0.5
    assert row.over_threshold is True


# ── AC-002 / EDGE-002 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_city_tier_share_includes_absolute_counts(db_session) -> None:
    """AC-002 + EDGE-002: share of A/B/C plus absolute A count (one-arena city must not hide 0/1)."""
    city_id = await _city(db_session, "IceHealth-tier")
    a_id = await _arena(db_session, city_id, "Арена-A", phone="+375 17 111")
    b_id = await _arena(db_session, city_id, "Арена-B", phone="+375 17 222")
    await _arena(db_session, city_id, "Арена-C")
    await _insert_session(db_session, a_id, starts_at=_NOW + timedelta(days=1))
    await db_session.flush()
    assert b_id  # profile-complete, no future ice → B

    rows = await city_tier_shares(db_session, now=_NOW)
    by_city = {row.city_id: row for row in rows}
    row = by_city[city_id]
    assert row.arenas_total == 3
    assert row.tier_a_count == 1
    assert row.tier_b_count == 1
    assert row.tier_c_count == 1
    assert row.tier_a_share == pytest.approx(1 / 3)
    assert row.tier_a_count_prev is not None


@pytest.mark.asyncio
async def test_tier_a_week_over_week_uses_as_of_sessions(db_session) -> None:
    city_id = await _city(db_session, "IceHealth-wow")
    arena_id = await _arena(db_session, city_id, "Арена-WOW", phone="+375 17 333")
    await _insert_session(
        db_session,
        arena_id,
        starts_at=_NOW - timedelta(days=4),
        ends_at=_NOW - timedelta(days=4) + timedelta(minutes=45),
    )
    await db_session.flush()

    rows = await city_tier_shares(db_session, now=_NOW)
    row = next(r for r in rows if r.city_id == city_id)
    assert row.tier_a_count == 0
    assert row.tier_a_count_prev == 1
    assert row.tier_a_count_delta == -1


# ── AC-003 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_booking_density_per_city(db_session) -> None:
    city_id = await _city(db_session, "IceHealth-book")
    booked = await _arena(db_session, city_id, "Арена-запись")
    empty = await _arena(db_session, city_id, "Арена-пусто")
    await db_session.flush()

    service_id = await require_seed_service_id(db_session)
    trainer_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO trainers (status, schedule_grid_step_minutes)
                    VALUES ('active', 15) RETURNING id
                    """
                )
            )
        ).scalar_one()
    )
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    client_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
                    VALUES (:tg, 'Ice', 'Book', :phone, :pn) RETURNING id
                    """
                ),
                {"tg": tg, "phone": phone, "pn": phone_n},
            )
        ).scalar_one()
    )
    slot_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, arena_id)
                    VALUES (:tid, :d, TIME '09:00', TIME '10:00', 'booked', :aid) RETURNING id
                    """
                ),
                {"tid": trainer_id, "d": _NOW.date(), "aid": booked},
            )
        ).scalar_one()
    )
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status, arena_id, created_at)
            VALUES (:tid, :cid, :sid, :svc, 'confirmed', :aid, :created)
            """
        ),
        {
            "tid": trainer_id,
            "cid": client_id,
            "sid": slot_id,
            "svc": service_id,
            "aid": booked,
            "created": _NOW - timedelta(days=2),
        },
    )
    await db_session.flush()
    assert empty

    rows = await city_booking_density(db_session, now=_NOW)
    row = next(r for r in rows if r.city_id == city_id)
    assert row.arenas_total == 2
    assert row.arenas_with_bookings_30d == 1
    assert row.density_share == pytest.approx(0.5)


# ── AC-004 / AC-005 / TASK-066 placeholder ────────────────────────────────


def test_calibration_summary_is_placeholder_for_task_066() -> None:
    summary = calibration_summary()
    assert summary is None or summary.get("available") is False


def test_price_totals_never_mix_currencies() -> None:
    """AC-005: totals are per currency_code, never one blended number."""
    grouped = price_totals_grouped_by_currency(
        [
            {"currency_code": "BYN", "price_adult_minor": 1000},
            {"currency_code": "RUB", "price_adult_minor": 500},
            {"currency_code": "BYN", "price_adult_minor": 200},
        ]
    )
    assert set(grouped.keys()) == {"BYN", "RUB"}
    assert grouped["BYN"] == 1200
    assert grouped["RUB"] == 500
    assert "total" not in grouped


@pytest.mark.asyncio
async def test_weekly_digest_lists_silent_stale_and_tier_a_change(db_session) -> None:
    """AC-004: one message with silent sources, stale share, A count next to share."""
    city_id = await _city(db_session, "IceHealth-digest")
    silent_arena = await _arena(db_session, city_id, "Каток-дайджест-тишина")
    a_arena = await _arena(db_session, city_id, "Каток-дайджест-A", phone="+375 17 444")
    job_id = await _job_row(db_session, silent_arena, "digest_silent_v1")
    await _insert_run(
        db_session, job_id, silent_arena, status=RUN_STATUS_EMPTY, finished_at=_NOW - timedelta(hours=1)
    )
    await _insert_run(
        db_session,
        job_id,
        silent_arena,
        status=RUN_STATUS_OK,
        finished_at=_NOW - timedelta(days=5),
    )
    await _insert_session(db_session, a_arena, starts_at=_NOW + timedelta(days=1))
    await _insert_session(
        db_session,
        silent_arena,
        starts_at=_NOW + timedelta(days=1),
        valid_until=_NOW - timedelta(hours=1),
        currency="BYN",
        price_adult_minor=1200,
    )
    await _insert_session(
        db_session,
        a_arena,
        starts_at=_NOW + timedelta(hours=3),
        valid_until=_NOW + timedelta(days=2),
        currency="RUB",
        price_adult_minor=800,
        source_id="admin",
        observed_at=_NOW - timedelta(days=1),
    )
    await db_session.flush()

    snap = await ice_health_snapshot(db_session, now=_NOW)
    body = format_weekly_digest(snap)
    assert "молч" in body.lower() or "тишин" in body.lower() or "Каток-дайджест-тишина" in body
    assert "просроч" in body.lower() or "valid_until" in body.lower() or "устарев" in body.lower()
    assert "A" in body
    assert "%" in body
    assert "TASK-066" in body or "калибр" in body.lower()
    assert "BYN+RUB" not in body
    assert "2000" not in body  # must not sum 1200 BYN + 800 RUB


@pytest.mark.asyncio
async def test_product_analytics_includes_ice_health_slice(db_session) -> None:
    city_id = await _city(db_session, "IceHealth-admin")
    await _arena(db_session, city_id, "Каток-админ")
    await db_session.flush()

    data = await get_admin_product_analytics(db_session)
    assert "ice_health" in data
    health = data["ice_health"]
    assert "cities" in health
    assert "silent_sources" in health
    city_rows = health["cities"]
    assert any(row["city_id"] == city_id for row in city_rows)


def test_notification_service_ticks_ice_health_loops() -> None:
    loop_src = (ROOT / "src/ingestion/loop.py").read_text(encoding="utf-8")
    svc_src = (ROOT / "src/bot/notification_service.py").read_text(encoding="utf-8")
    assert "run_ice_health_alert_loop" in loop_src
    assert "run_ice_health_weekly_digest_loop" in loop_src
    assert "run_ice_health_alert_loop" in svc_src
    assert "run_ice_health_weekly_digest_loop" in svc_src
    assert "http" not in loop_src.lower() or "uvicorn" not in loop_src.lower()
