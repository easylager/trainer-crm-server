"""TASK-276: нет сеансов — факт и способ узнать, без оговорки системы."""

from __future__ import annotations

from datetime import date

from src.application.place_page import _b_schedule


def _view(*, phone: str = "", website: str = "") -> dict:
    return {
        "card": {
            "venue_type": "ice",
            "schedule_mode": "auto",
            "phone": phone,
            "website_url": website,
            "in_season": True,
        },
        "days": [],
        "today": date(2026, 10, 14),
    }


def test_schedule_section_phone_matches_the_shared_sentence() -> None:
    html = _b_schedule(
        _view(phone="+375291112233", website="https://rink.example/ice"),
        base_path="/p/1",
        invite=False,
        links={"tel": "tel:+375291112233"},
    )
    assert "Время массового катания называют по телефону." in html
    assert "tel:+375291112233" in html
    assert "уточняется" not in html
    assert "пока не получили" not in html


def test_schedule_section_site_when_there_is_no_phone() -> None:
    html = _b_schedule(
        _view(website="https://rink.example/ice"),
        base_path="/p/1",
        invite=False,
        links={},
    )
    assert "Время массового катания — на сайте катка" in html
    assert 'href="https://rink.example/ice"' in html
    assert "rink.example" in html
    assert "уточняется" not in html


def test_schedule_section_absent_without_phone_and_site() -> None:
    html = _b_schedule(_view(), base_path="/p/1", invite=False, links={})
    assert html == ""


def test_schedule_section_ignores_unsafe_site() -> None:
    html = _b_schedule(
        _view(website="javascript:alert(1)"),
        base_path="/p/1",
        invite=False,
        links={},
    )
    assert html == ""
