"""
Approximate physical effort from completed bookings for motivational milestone pushes.

Method (transparent heuristics, not medical precision):
- Each catalog ``services.name`` maps to an internal **effort profile** (ice learn / figure / hockey / …).
- **Energy (kcal)** uses the standard MET formula::
      kcal ≈ MET × body_mass_kg × duration_hours
  MET values follow published compendium bands for skating / team sports / conditioning,
  tightened per profile so totals stay plausible for typical coached sessions.
- **Skating-like distance (km)** applies only to on-ice / roller profiles::
      km ≈ typical_mean_speed_kmh × active_time_hours
  where ``active_time_hours = duration_hours × active_fraction`` (fraction accounts for
  explanations, drills on boards, water breaks — not continuous laps).
- **ОФП/СФП** has no meaningful «km skated»; we convert only those minutes into an intuitive
  **brisk-walk equivalent** distance using ~52 kcal/km for an average adult — same order as
  fitness-app rough guides.

Default reference mass **72 kg** matches «типичный взрослый»; copy in Telegram explains that
figures are estimates.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class EffortServiceProfile(str, Enum):
    """Internal coarse buckets derived from Russian service titles."""

    ICE_LEARN = "ice_learn"
    ICE_IMPROVE = "ice_improve"
    FIGURE = "figure"
    HOCKEY_SKATE = "hockey_skate"
    OHM = "ohm"
    ROLLERS = "rollers"
    CONDITIONING = "conditioning"
    DEFAULT = "default"


# MET, active_fraction (0–1), mean_speed_kmh while moving (0 ⇒ no skating distance)
_PROFILE_PARAMS: dict[EffortServiceProfile, tuple[float, float, float]] = {
    # beginners: lower MET, more pauses, modest lap speed
    EffortServiceProfile.ICE_LEARN: (5.5, 0.52, 5.2),
    EffortServiceProfile.ICE_IMPROVE: (6.5, 0.56, 7.8),
    EffortServiceProfile.FIGURE: (7.2, 0.50, 6.8),
    EffortServiceProfile.HOCKEY_SKATE: (7.6, 0.58, 9.2),
    EffortServiceProfile.OHM: (8.2, 0.60, 10.5),
    EffortServiceProfile.ROLLERS: (6.6, 0.56, 8.0),
    # gym / dryland — distance via walk equivalent only
    EffortServiceProfile.CONDITIONING: (5.8, 0.72, 0.0),
    EffortServiceProfile.DEFAULT: (6.4, 0.55, 7.5),
}

REFERENCE_BODY_MASS_KG = 72.0
# Approximate kcal per km brisk walking for REFERENCE_BODY_MASS_KG (order-of-magnitude, docs/compendium).
_KCAL_PER_KM_WALK_BRISK = 52.0


def classify_service_effort_profile(
    service_name: str, effort_profile: str | None = None
) -> EffortServiceProfile:
    """Map catalog title to effort bucket; DB effort_profile wins over name heuristics."""
    raw_profile = (effort_profile or "").strip().lower()
    if raw_profile:
        try:
            return EffortServiceProfile(raw_profile)
        except ValueError:
            pass
    raw = (service_name or "").strip().lower()
    n = raw.replace("ё", "е")
    if "офп" in n or "сфп" in n:
        return EffortServiceProfile.CONDITIONING
    if "ролик" in n:
        return EffortServiceProfile.ROLLERS
    if "фигур" in n:
        return EffortServiceProfile.FIGURE
    if "охм" in n:
        return EffortServiceProfile.OHM
    if "хоккей" in n:
        return EffortServiceProfile.HOCKEY_SKATE
    if "с нуля" in n or "обучен" in n and "катан" in n:
        return EffortServiceProfile.ICE_LEARN
    if "совершенств" in n:
        return EffortServiceProfile.ICE_IMPROVE
    return EffortServiceProfile.DEFAULT


@dataclass(frozen=True)
class SessionEffortBreakdown:
    """Single completed booking contribution."""

    duration_minutes: float
    service_name: str
    profile: EffortServiceProfile
    kcal: float
    skating_distance_km: float
    conditioning_kcal: float  # subset of kcal that uses walk-equivalent km


@dataclass(frozen=True)
class AggregatedSessionEffort:
    """Totals over many sessions (already summed)."""

    total_kcal: float
    skating_distance_km: float
    conditioning_walk_equivalent_km: float

    def distance_lines_for_push(self) -> tuple[str, ...]:
        """
        Short Russian lines for Telegram (no HTML).

        Returns 1–2 fragments merged by formatter (middle dot or newline).
        """
        parts: list[str] = []
        skate = self.skating_distance_km
        walk = self.conditioning_walk_equivalent_km
        if skate >= 0.05:
            parts.append(f"около {_fmt_km(skate)} км скольжения на льду или роликах (суммарно)")
        if walk >= 0.05:
            parts.append(
                f"плюс эквивалент прогулки около {_fmt_km(walk)} км для занятий в зале/ОФП"
            )
        if not parts:
            parts.append("маршрут по занятиям смешанный — см. детали в приложении")
        return tuple(parts)


def estimate_session_effort(
    *,
    service_name: str,
    duration_minutes: float,
    body_mass_kg: float = REFERENCE_BODY_MASS_KG,
    effort_profile: str | None = None,
) -> SessionEffortBreakdown:
    """Best-effort MET + distance split for one completed session."""
    dur = max(1.0, float(duration_minutes))
    profile = classify_service_effort_profile(service_name, effort_profile=effort_profile)
    met, frac, v_kmh = _PROFILE_PARAMS.get(profile, _PROFILE_PARAMS[EffortServiceProfile.DEFAULT])
    hours = dur / 60.0
    kcal = max(0.0, met * body_mass_kg * hours)
    cond_kcal = kcal if profile is EffortServiceProfile.CONDITIONING else 0.0
    skate_km = 0.0
    if profile is not EffortServiceProfile.CONDITIONING and v_kmh > 0:
        active_hours = hours * frac
        skate_km = max(0.0, v_kmh * active_hours)
    return SessionEffortBreakdown(
        duration_minutes=dur,
        service_name=service_name,
        profile=profile,
        kcal=kcal,
        skating_distance_km=skate_km,
        conditioning_kcal=cond_kcal,
    )


def aggregate_effort_from_completed_sessions(
    rows: Iterable[tuple[float, str]],
    *,
    body_mass_kg: float = REFERENCE_BODY_MASS_KG,
) -> AggregatedSessionEffort:
    """
    Sum estimates over (duration_minutes, service_name) rows from DB.

    Conditioning sessions contribute kcal and walk-equivalent km only.
    """
    total_kcal = 0.0
    total_skate = 0.0
    total_cond_kcal = 0.0
    for dur_min, svc in rows:
        b = estimate_session_effort(service_name=svc, duration_minutes=float(dur_min), body_mass_kg=body_mass_kg)
        total_kcal += b.kcal
        total_skate += b.skating_distance_km
        total_cond_kcal += b.conditioning_kcal
    walk_km = total_cond_kcal / _KCAL_PER_KM_WALK_BRISK if total_cond_kcal > 0 else 0.0
    return AggregatedSessionEffort(
        total_kcal=total_kcal,
        skating_distance_km=total_skate,
        conditioning_walk_equivalent_km=walk_km,
    )


def format_compact_effort_display_html(*, kcal_display: int, agg: AggregatedSessionEffort) -> str:
    """Краткая строка усилий для Telegram HTML: жирные ориентиры по ккал и км."""
    chunks: list[str] = [f"<b>≈{int(kcal_display)} ккал</b>"]
    skate = agg.skating_distance_km
    walk = agg.conditioning_walk_equivalent_km
    if skate >= 0.05:
        chunks.append(f"<b>≈{_fmt_km(skate)} км</b> на льду или роликах")
    if walk >= 0.05:
        chunks.append(f"<b>≈{_fmt_km(walk)} км</b> эквивалента прогулки (ОФП)")
    return " · ".join(chunks)


def round_kcal_for_display(value: float) -> int:
    """Softer rounding so we do not imply false precision."""
    x = max(0.0, float(value))
    if x < 150:
        return int(round(x / 20.0) * 20)
    if x < 600:
        return int(round(x / 50.0) * 50)
    return int(round(x / 100.0) * 100)


def _fmt_km(km: float) -> str:
    if km >= 10:
        return str(int(round(km)))
    return f"{km:.1f}".replace(".", ",")
