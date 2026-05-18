"""Unit tests for heuristic session effort (MET / skating km / walk equivalent)."""

from __future__ import annotations

from src.application.client_session_effort_estimates import (
    EffortServiceProfile,
    aggregate_effort_from_completed_sessions,
    classify_service_effort_profile,
    estimate_session_effort,
    format_compact_effort_display_html,
    round_kcal_for_display,
)


def test_format_compact_effort_display_html() -> None:
    agg = aggregate_effort_from_completed_sessions([(60.0, "Фигурное катание")])
    line = format_compact_effort_display_html(
        kcal_display=round_kcal_for_display(agg.total_kcal), agg=agg
    )
    assert "<b>" in line
    assert "ккал" in line
    assert "льду" in line or "льд" in line


def test_classify_seed_services() -> None:
    assert classify_service_effort_profile("Обучение катанию «с нуля»") is EffortServiceProfile.ICE_LEARN
    assert classify_service_effort_profile("Совершенствование катания") is EffortServiceProfile.ICE_IMPROVE
    assert classify_service_effort_profile("Фигурное катание") is EffortServiceProfile.FIGURE
    assert classify_service_effort_profile("Хоккейное катание") is EffortServiceProfile.HOCKEY_SKATE
    assert classify_service_effort_profile("Катание на роликах") is EffortServiceProfile.ROLLERS
    assert classify_service_effort_profile("ОХМ(отработка хоккейного мастерства)") is EffortServiceProfile.OHM
    assert classify_service_effort_profile("ОФП/СФП") is EffortServiceProfile.CONDITIONING


def test_figure_session_positive_skating_km_and_kcal() -> None:
    e = estimate_session_effort(service_name="Фигурное катание", duration_minutes=60.0)
    assert e.profile is EffortServiceProfile.FIGURE
    assert e.kcal > 200
    assert e.skating_distance_km > 2.0
    assert e.conditioning_kcal == 0.0


def test_conditioning_walk_equivalent_not_skating_km() -> None:
    e = estimate_session_effort(service_name="ОФП/СФП", duration_minutes=45.0)
    assert e.profile is EffortServiceProfile.CONDITIONING
    assert e.skating_distance_km == 0.0
    assert e.conditioning_kcal > 0


def test_aggregate_mix_skating_and_conditioning() -> None:
    agg = aggregate_effort_from_completed_sessions(
        [
            (60.0, "Фигурное катание"),
            (45.0, "ОФП/СФП"),
        ]
    )
    assert agg.total_kcal > 0
    assert agg.skating_distance_km > 0
    assert agg.conditioning_walk_equivalent_km > 0
    lines = agg.distance_lines_for_push()
    assert len(lines) >= 2


def test_round_kcal_for_display() -> None:
    assert round_kcal_for_display(44) == 40
    assert round_kcal_for_display(180) == 200
    assert round_kcal_for_display(950) == 1000
