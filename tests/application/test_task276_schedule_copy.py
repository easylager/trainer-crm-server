"""TASK-276: нет сеансов — контакт без оговорок про отсутствие сетки."""

from __future__ import annotations

from datetime import date

from src.application.place_page import _b_schedule


def _view(
    *,
    phone: str = "",
    website: str = "",
    opening_hours: dict | None = None,
) -> dict:
    card: dict = {
        "venue_type": "ice",
        "schedule_mode": "auto",
        "phone": phone,
        "website_url": website,
        "in_season": True,
        "freshness": {"schedule_auto": True},
    }
    if opening_hours is not None:
        card["opening_hours"] = opening_hours
    return {
        "card": card,
        "days": [],
        "today": date(2026, 10, 14),
    }


def test_schedule_section_phone_without_banner_text() -> None:
    html = _b_schedule(
        _view(phone="+375291112233", website="https://rink.example/ice"),
        base_path="/p/1",
        invite=False,
        links={"tel": "tel:+375291112233"},
    )
    assert "tel:+375291112233" in html
    assert "называют по телефону" not in html
    assert "не публикуют" not in html
    assert "на сайте катка" not in html


def test_schedule_section_does_not_repeat_hours_from_info() -> None:
    html = _b_schedule(
        _view(
            phone="+375291112233",
            opening_hours={"daily": {"open": "07:00", "close": "23:00"}},
        ),
        base_path="/p/1",
        invite=False,
        links={"tel": "tel:+375291112233"},
    )
    assert "tel:+375291112233" in html
    assert "каждый день 7:00–23:00" not in html


def test_schedule_section_site_when_no_phone() -> None:
    html = _b_schedule(
        _view(website="https://rink.example/ice"),
        base_path="/p/1",
        invite=False,
        links={},
    )
    assert "Время массового катания — на сайте катка" in html
    assert 'href="https://rink.example/ice"' in html
    assert "не публикуют" not in html


def test_schedule_section_buy_link_when_no_sessions() -> None:
    html = _b_schedule(
        _view(website="https://hc-vitebsk.by/"),
        base_path="/p/vitebsk/vitebsk-ds",
        invite=False,
        links={"tickets": ("/out?action=tickets", False)},
    )
    assert "Купить билет онлайн" in html
    assert 'href="/out?action=tickets"' in html
    assert 'href="https://hc-vitebsk.by/"' in html
    assert "на сайте катка" not in html


def test_schedule_section_absent_without_contact() -> None:
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
