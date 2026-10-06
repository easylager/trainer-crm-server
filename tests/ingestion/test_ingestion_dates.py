"""Unit tests for src.ingestion.dates (year rollover window)."""
from __future__ import annotations

from datetime import date

import pytest

from src.ingestion.dates import infer_date_from_day_month, parser_reference_date


def test_infer_date_january_after_december_reference() -> None:
    ref = date(2026, 12, 29)
    assert infer_date_from_day_month(1, 1, ref) == date(2027, 1, 1)
    assert infer_date_from_day_month(4, 1, ref) == date(2027, 1, 4)


def test_infer_date_december_before_january_reference() -> None:
    ref = date(2027, 1, 2)
    assert infer_date_from_day_month(29, 12, ref) == date(2026, 12, 29)


def test_infer_date_same_month_near_reference() -> None:
    ref = date(2026, 9, 5)
    assert infer_date_from_day_month(12, 9, ref) == date(2026, 9, 12)


def test_parser_reference_date_run_year_uses_mid_season_anchor() -> None:
    assert parser_reference_date({"run_year": 2026}) == date(2026, 7, 1)


def test_parser_reference_date_run_date_wins() -> None:
    assert parser_reference_date({"run_year": 2026, "run_date": "2026-12-29"}) == date(2026, 12, 29)
