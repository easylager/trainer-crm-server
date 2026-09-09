"""Ice data health: last valid ok, stale facts, city A/B/C share.

Source of truth is ice_parser_jobs + ice_scrape_runs + ice_sessions.
Do not invent calibration numbers — TASK-066 owns gold-set accuracy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_public_use_cases import TIER_A, TIER_B, TIER_C, compute_data_tier
from src.ingestion.jobs import cadence_timedelta
from src.ingestion.success_rates import job_success_rates

DEFAULT_SILENCE_MULTIPLES = 2
DEFAULT_STALE_SHARE_THRESHOLD = 0.25
CONFIG_SILENCE_HOURS = "silence_ok_hours"
CONFIG_SILENCE_MULTIPLES = "silence_ok_multiples"


@dataclass(frozen=True)
class SilentJob:
    job_id: int
    arena_id: int
    arena_name: str
    city_id: int
    city_name: str
    cadence: str
    last_ok_at: datetime | None
    last_status: str | None
    threshold: timedelta
    success_rate_7d: float | None
    success_rate_30d: float | None


@dataclass(frozen=True)
class CityStaleShare:
    city_id: int
    city_name: str
    stale_count: int
    total_count: int
    stale_share: float
    over_threshold: bool


@dataclass(frozen=True)
class CityTierShare:
    city_id: int
    city_name: str
    arenas_total: int
    tier_a_count: int
    tier_b_count: int
    tier_c_count: int
    tier_a_share: float
    tier_b_share: float
    tier_c_share: float
    tier_a_count_prev: int
    tier_a_share_prev: float
    tier_a_count_delta: int
    tier_a_share_delta_pp: float


@dataclass(frozen=True)
class CityBookingDensity:
    city_id: int
    city_name: str
    arenas_total: int
    arenas_with_bookings_30d: int
    density_share: float


@dataclass(frozen=True)
class IceHealthSnapshot:
    silent_jobs: list[SilentJob]
    stale_by_city: list[CityStaleShare]
    tier_by_city: list[CityTierShare]
    density_by_city: list[CityBookingDensity]
    manual_admin_sessions_7d: int
    calibration: dict[str, Any] | None


def silence_threshold(cadence: str, config: dict[str, Any] | None) -> timedelta:
    """EDGE-001: cadence×N (default 2), or absolute silence_ok_hours on the job."""
    cfg = config or {}
    hours = cfg.get(CONFIG_SILENCE_HOURS)
    if hours is not None and str(hours).strip() != "":
        return timedelta(hours=float(hours))
    raw_multiples = cfg.get(CONFIG_SILENCE_MULTIPLES, DEFAULT_SILENCE_MULTIPLES)
    multiples = int(raw_multiples)
    return cadence_timedelta(cadence) * multiples


def calibration_summary() -> dict[str, Any] | None:
    """TASK-066 will provide precision/recall. Do not invent fake accuracy."""
    # TODO(TASK-066): return calibration_summary() from the gold-set module when it exists.
    return None


def _as_config(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def _ratio(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return num / den


def _future_ice_sql() -> str:
    return """
        EXISTS (
            SELECT 1
            FROM ice_sessions AS s
            WHERE s.arena_id = a.id
              AND s.status = 'active'
              AND s.kind IN ('public_skate', 'open_ice')
              AND s.ends_at_utc >= :as_of
              AND (s.valid_until IS NULL OR s.valid_until >= :as_of)
        )
    """


def _profile_complete_sql() -> str:
    return """
        (
            NULLIF(BTRIM(COALESCE(ap.phone, '')), '') IS NOT NULL
            OR NULLIF(BTRIM(COALESCE(ap.website_url, '')), '') IS NOT NULL
            OR (ap.opening_hours IS NOT NULL AND ap.opening_hours <> '{}'::jsonb)
            OR EXISTS (
                SELECT 1 FROM media AS m
                WHERE m.owner_type = 'arena'
                  AND m.owner_id = a.id
                  AND m.status = 'published'
            )
        )
    """


async def detect_silent_jobs(session: AsyncSession, *, now: datetime) -> list[SilentJob]:
    """Enabled jobs with no ok longer than cadence×N (or per-job hours). Skip disabled."""
    rates = {
        row.job_id: row for row in await job_success_rates(session, now=now, window_days=(7, 30))
    }
    result = await session.execute(
        text(
            """
            SELECT
                j.id AS job_id,
                j.arena_id,
                a.name AS arena_name,
                a.city_id,
                c.name AS city_name,
                j.cadence,
                j.config,
                j.created_at,
                ok.finished_at AS last_ok_at,
                last_any.status AS last_status
            FROM ice_parser_jobs AS j
            JOIN arenas AS a ON a.id = j.arena_id
            JOIN cities AS c ON c.id = a.city_id
            LEFT JOIN LATERAL (
                SELECT finished_at
                FROM ice_scrape_runs
                WHERE job_id = j.id AND status = 'ok'
                ORDER BY finished_at DESC, id DESC
                LIMIT 1
            ) AS ok ON true
            LEFT JOIN LATERAL (
                SELECT status
                FROM ice_scrape_runs
                WHERE job_id = j.id
                ORDER BY finished_at DESC, id DESC
                LIMIT 1
            ) AS last_any ON true
            WHERE j.is_enabled = true
            ORDER BY j.id
            """
        )
    )
    silent: list[SilentJob] = []
    for row in result.fetchall():
        config = _as_config(row.config)
        threshold = silence_threshold(str(row.cadence), config)
        last_ok_at = row.last_ok_at
        anchor = last_ok_at if last_ok_at is not None else row.created_at
        if anchor is None:
            continue
        if now - anchor <= threshold:
            continue
        rate = rates.get(int(row.job_id))
        silent.append(
            SilentJob(
                job_id=int(row.job_id),
                arena_id=int(row.arena_id),
                arena_name=str(row.arena_name or ""),
                city_id=int(row.city_id),
                city_name=str(row.city_name or ""),
                cadence=str(row.cadence),
                last_ok_at=last_ok_at,
                last_status=str(row.last_status) if row.last_status else None,
                threshold=threshold,
                success_rate_7d=rate.success_rate_7d if rate else None,
                success_rate_30d=rate.success_rate_30d if rate else None,
            )
        )
    return silent


async def stale_session_share_by_city(
    session: AsyncSession,
    *,
    now: datetime,
    threshold: float = DEFAULT_STALE_SHARE_THRESHOLD,
) -> list[CityStaleShare]:
    result = await session.execute(
        text(
            """
            SELECT
                a.city_id,
                c.name AS city_name,
                COUNT(*) FILTER (
                    WHERE s.valid_until IS NOT NULL AND s.valid_until < :now
                )::int AS stale_count,
                COUNT(*)::int AS total_count
            FROM ice_sessions AS s
            JOIN arenas AS a ON a.id = s.arena_id
            JOIN cities AS c ON c.id = a.city_id
            WHERE s.status = 'active'
              AND s.kind IN ('public_skate', 'open_ice')
            GROUP BY a.city_id, c.name
            ORDER BY a.city_id
            """
        ),
        {"now": now},
    )
    rows: list[CityStaleShare] = []
    for row in result.fetchall():
        total = int(row.total_count or 0)
        stale = int(row.stale_count or 0)
        share = _ratio(stale, total)
        rows.append(
            CityStaleShare(
                city_id=int(row.city_id),
                city_name=str(row.city_name or ""),
                stale_count=stale,
                total_count=total,
                stale_share=share,
                over_threshold=total > 0 and share >= threshold,
            )
        )
    return rows


async def _tier_counts_as_of(session: AsyncSession, *, as_of: datetime) -> dict[int, dict[str, Any]]:
    result = await session.execute(
        text(
            f"""
            SELECT
                a.city_id,
                c.name AS city_name,
                a.id AS arena_id,
                {_future_ice_sql()} AS has_future_ice,
                {_profile_complete_sql()} AS profile_complete
            FROM arenas AS a
            JOIN cities AS c ON c.id = a.city_id
            LEFT JOIN arena_profiles AS ap ON ap.arena_id = a.id
            WHERE COALESCE(a.is_active, true)
            ORDER BY a.city_id, a.id
            """
        ),
        {"as_of": as_of},
    )
    by_city: dict[int, dict[str, Any]] = {}
    for row in result.fetchall():
        city_id = int(row.city_id)
        bucket = by_city.setdefault(
            city_id,
            {
                "city_name": str(row.city_name or ""),
                "total": 0,
                "A": 0,
                "B": 0,
                "C": 0,
            },
        )
        tier = compute_data_tier(
            has_future_public_ice=bool(row.has_future_ice),
            profile_complete=bool(row.profile_complete),
        )
        bucket["total"] += 1
        bucket[tier] += 1
    return by_city


async def city_tier_shares(session: AsyncSession, *, now: datetime) -> list[CityTierShare]:
    current = await _tier_counts_as_of(session, as_of=now)
    previous = await _tier_counts_as_of(session, as_of=now - timedelta(days=7))
    rows: list[CityTierShare] = []
    for city_id, cur in sorted(current.items()):
        prev = previous.get(city_id, {"A": 0, "total": 0})
        total = int(cur["total"])
        a_now = int(cur[TIER_A])
        a_prev = int(prev.get(TIER_A, 0))
        share_now = _ratio(a_now, total)
        prev_total = int(prev.get("total") or 0)
        share_prev = _ratio(a_prev, prev_total if prev_total else total)
        rows.append(
            CityTierShare(
                city_id=city_id,
                city_name=str(cur["city_name"]),
                arenas_total=total,
                tier_a_count=a_now,
                tier_b_count=int(cur[TIER_B]),
                tier_c_count=int(cur[TIER_C]),
                tier_a_share=share_now,
                tier_b_share=_ratio(int(cur[TIER_B]), total),
                tier_c_share=_ratio(int(cur[TIER_C]), total),
                tier_a_count_prev=a_prev,
                tier_a_share_prev=share_prev,
                tier_a_count_delta=a_now - a_prev,
                tier_a_share_delta_pp=(share_now - share_prev) * 100.0,
            )
        )
    return rows


async def city_booking_density(session: AsyncSession, *, now: datetime) -> list[CityBookingDensity]:
    cutoff = now - timedelta(days=30)
    result = await session.execute(
        text(
            """
            WITH city_arenas AS (
                SELECT a.id AS arena_id, a.city_id, c.name AS city_name
                FROM arenas AS a
                JOIN cities AS c ON c.id = a.city_id
                WHERE COALESCE(a.is_active, true)
            ),
            booked AS (
                SELECT DISTINCT COALESCE(b.arena_id, s.arena_id) AS arena_id
                FROM bookings AS b
                JOIN slots AS s ON s.id = b.slot_id
                WHERE b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                  AND COALESCE(b.is_sandbox, false) = false
                  AND b.created_at >= :cutoff
                  AND b.created_at <= :now
                  AND COALESCE(b.arena_id, s.arena_id) IS NOT NULL
            )
            SELECT
                ca.city_id,
                ca.city_name,
                COUNT(*)::int AS arenas_total,
                COUNT(*) FILTER (WHERE booked.arena_id IS NOT NULL)::int AS arenas_with_bookings_30d
            FROM city_arenas AS ca
            LEFT JOIN booked ON booked.arena_id = ca.arena_id
            GROUP BY ca.city_id, ca.city_name
            ORDER BY ca.city_id
            """
        ),
        {"now": now, "cutoff": cutoff},
    )
    rows: list[CityBookingDensity] = []
    for row in result.fetchall():
        total = int(row.arenas_total or 0)
        with_b = int(row.arenas_with_bookings_30d or 0)
        rows.append(
            CityBookingDensity(
                city_id=int(row.city_id),
                city_name=str(row.city_name or ""),
                arenas_total=total,
                arenas_with_bookings_30d=with_b,
                density_share=_ratio(with_b, total),
            )
        )
    return rows


async def _manual_admin_sessions_7d(session: AsyncSession, *, now: datetime) -> int:
    result = await session.execute(
        text(
            """
            SELECT COUNT(*)::int
            FROM ice_sessions
            WHERE source_id = 'admin'
              AND observed_at IS NOT NULL
              AND observed_at >= :cutoff
              AND observed_at <= :now
            """
        ),
        {"now": now, "cutoff": now - timedelta(days=7)},
    )
    return int(result.scalar() or 0)


async def ice_health_snapshot(session: AsyncSession, *, now: datetime) -> IceHealthSnapshot:
    silent = await detect_silent_jobs(session, now=now)
    stale = await stale_session_share_by_city(session, now=now)
    tiers = await city_tier_shares(session, now=now)
    density = await city_booking_density(session, now=now)
    manuals = await _manual_admin_sessions_7d(session, now=now)
    return IceHealthSnapshot(
        silent_jobs=silent,
        stale_by_city=stale,
        tier_by_city=tiers,
        density_by_city=density,
        manual_admin_sessions_7d=manuals,
        calibration=calibration_summary(),
    )


def _silent_as_dict(row: SilentJob) -> dict[str, Any]:
    payload = asdict(row)
    payload["last_ok_at"] = row.last_ok_at.isoformat() if row.last_ok_at else None
    payload["threshold_hours"] = row.threshold.total_seconds() / 3600.0
    del payload["threshold"]
    return payload


async def ice_health_admin_payload(session: AsyncSession, *, now: datetime | None = None) -> dict[str, Any]:
    """Admin analytics slice: city tiers, density, silent sources. No mixed-currency totals."""
    snap = await ice_health_snapshot(session, now=now or datetime.now().astimezone())
    density_by_city = {row.city_id: row for row in snap.density_by_city}
    stale_by_city = {row.city_id: row for row in snap.stale_by_city}
    cities: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in snap.tier_by_city:
        seen.add(row.city_id)
        dens = density_by_city.get(row.city_id)
        stale = stale_by_city.get(row.city_id)
        cities.append(
            {
                "city_id": row.city_id,
                "city_name": row.city_name,
                "arenas_total": row.arenas_total,
                "tier_a_count": row.tier_a_count,
                "tier_b_count": row.tier_b_count,
                "tier_c_count": row.tier_c_count,
                "tier_a_share": row.tier_a_share,
                "tier_b_share": row.tier_b_share,
                "tier_c_share": row.tier_c_share,
                "tier_a_count_prev": row.tier_a_count_prev,
                "tier_a_share_prev": row.tier_a_share_prev,
                "tier_a_count_delta": row.tier_a_count_delta,
                "tier_a_share_delta_pp": row.tier_a_share_delta_pp,
                "arenas_with_bookings_30d": dens.arenas_with_bookings_30d if dens else 0,
                "booking_density_share": dens.density_share if dens else 0.0,
                "stale_session_count": stale.stale_count if stale else 0,
                "stale_session_total": stale.total_count if stale else 0,
                "stale_session_share": stale.stale_share if stale else 0.0,
            }
        )
    for city_id, dens in density_by_city.items():
        if city_id in seen:
            continue
        stale = stale_by_city.get(city_id)
        cities.append(
            {
                "city_id": dens.city_id,
                "city_name": dens.city_name,
                "arenas_total": dens.arenas_total,
                "tier_a_count": 0,
                "tier_b_count": 0,
                "tier_c_count": 0,
                "tier_a_share": 0.0,
                "tier_b_share": 0.0,
                "tier_c_share": 0.0,
                "tier_a_count_prev": 0,
                "tier_a_share_prev": 0.0,
                "tier_a_count_delta": 0,
                "tier_a_share_delta_pp": 0.0,
                "arenas_with_bookings_30d": dens.arenas_with_bookings_30d,
                "booking_density_share": dens.density_share,
                "stale_session_count": stale.stale_count if stale else 0,
                "stale_session_total": stale.total_count if stale else 0,
                "stale_session_share": stale.stale_share if stale else 0.0,
            }
        )
    return {
        "cities": cities,
        "silent_sources": [_silent_as_dict(row) for row in snap.silent_jobs],
        "manual_admin_sessions_7d": snap.manual_admin_sessions_7d,
        "calibration": snap.calibration,
    }
