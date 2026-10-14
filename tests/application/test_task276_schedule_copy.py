"""TASK-276: нет сеансов — факт и способ узнать, без оговорки системы."""

from __future__ import annotations

from datetime import date

from src.application.place_page import _b_schedule


def _view(
    *,
    phone: str = "",
    website: str = "",
    schedule_mode: str = "auto",
    schedule_auto: bool | None = True,
) -> dict:
    freshness: dict | None = None
    if schedule_auto is not None:
        freshness = {"schedule_auto": schedule_auto}
    return {
        "card": {
            "venue_type": "ice",
            "schedule_mode": schedule_mode,
            "phone": phone,
            "website_url": website,
            "in_season": True,
            "freshness": freshness,
        },
        "days": [],
        "today": date(2026, 10, 14),
    }


def test_schedule_section_skip_shows_not_published_with_phone() -> None:
    html = _b_schedule(
        _view(
            phone="+375291112233",
            website="https://rink.example/ice",
            schedule_mode="phone",
        ),
        base_path="/p/1",
        invite=False,
        links={"tel": "tel:+375291112233"},
    )
    assert "Расписание пока не публикуют." in html
    assert "tel:+375291112233" in html
    assert "на сайте катка" not in html


def test_schedule_section_parser_skip_shows_not_published_with_site() -> None:
    html = _b_schedule(
        _view(website="https://rink.example/ice", schedule_auto=False),
        base_path="/p/1",
        invite=False,
        links={},
    )
    assert "Расписание пока не публикуют." in html
    assert 'href="https://rink.example/ice"' in html
    assert "на сайте катка" not in html


def test_schedule_section_auto_parser_site_when_db_empty() -> None:
    html = _b_schedule(
        _view(website="https://rink.example/ice", schedule_auto=True),
        base_path="/p/1",
        invite=False,
        links={},
    )
    assert "Время массового катания — на сайте катка" in html
    assert 'href="https://rink.example/ice"' in html
    assert "не публикуют" not in html


def test_schedule_section_auto_parser_phone_before_site() -> None:
    html = _b_schedule(
        _view(phone="+375291112233", website="https://rink.example/ice", schedule_auto=True),
        base_path="/p/1",
        invite=False,
        links={"tel": "tel:+375291112233"},
    )
    assert "Время массового катания называют по телефону." in html
    assert "tel:+375291112233" in html


def test_schedule_section_absent_without_phone_and_site() -> None:
    html = _b_schedule(_view(schedule_mode="phone"), base_path="/p/1", invite=False, links={})
    assert html == ""


def test_schedule_section_ignores_unsafe_site() -> None:
    html = _b_schedule(
        _view(website="javascript:alert(1)", schedule_auto=False),
        base_path="/p/1",
        invite=False,
        links={},
    )
    assert html == ""
