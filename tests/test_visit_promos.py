"""Акции в visit_info: срок жизни, анонс за неделю, валидация дат."""
from __future__ import annotations

from datetime import date

import pytest

from src.application.arena_visit_info import VisitInfoError, normalize_visit_info, visit_view

RAW = {
    "promos": [
        {"title": "Красный день", "text": "Скидка 50%", "valid_from": "2026-11-07", "valid_until": "2026-11-07"},
        {"title": "День молодёжи", "valid_until": "2026-11-10"},
        {"title": "Студенты", "valid_from": "2026-11-17", "valid_until": "2026-11-17"},
        {"title": "Далёкая", "valid_from": "2026-12-20", "valid_until": "2026-12-20"},
        {"title": "Бессрочная"},
    ]
}


def _titles(today: date) -> list[str]:
    card = {"visit_info": normalize_visit_info(RAW)}
    more = visit_view(card, today=today, has_slots=True)["more"]
    promos = next((m for m in more if m["key"] == "promos"), None)
    return [r["title"] for r in promos["detail"]["rows"]] if promos else []


def test_expired_and_far_future_promos_are_hidden() -> None:
    titles = _titles(date(2026, 11, 9))
    assert "Красный день" not in titles and "Далёкая" not in titles
    assert "День молодёжи" in titles and "Бессрочная" in titles


def test_announce_window_is_one_week() -> None:
    assert "Студенты" not in _titles(date(2026, 11, 9))
    assert "Студенты" in _titles(date(2026, 11, 12))
    assert "Студенты" not in _titles(date(2026, 11, 18))


def test_promo_row_says_until_when() -> None:
    card = {"visit_info": normalize_visit_info(RAW)}
    rows = next(m for m in visit_view(card, today=date(2026, 11, 9), has_slots=True)["more"] if m["key"] == "promos")["detail"]["rows"]
    assert {r["title"]: r["when"] for r in rows}["День молодёжи"] == "до 10 ноября"


def test_bad_date_is_rejected() -> None:
    with pytest.raises(VisitInfoError):
        normalize_visit_info({"promos": [{"title": "x", "valid_until": "10.11"}]})
