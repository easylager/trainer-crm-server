"""Бейдж времени на плитке: «сб, 14 ноября 7:45» не помещается одной строкой крупным шрифтом."""
from __future__ import annotations

from src.application.style_b import tile_html


def _tile(badge: str) -> str:
    return tile_html(href="/x", name="Каток", line="800 руб.", photo_url=None, photo_alt="", badge=badge, badge_kind="time")


def test_day_goes_above_the_time() -> None:
    html = _tile("сб, 14 ноября 7:45")
    assert '<span class="b-badge__day">сб, 14 ноября</span>7:45</span>' in html


def test_time_only_stays_one_line() -> None:
    html = _tile("13:00")
    assert "b-badge__day" not in html and ">13:00</span>" in html


def test_non_time_badges_are_untouched() -> None:
    html = tile_html(href="/x", name="Каток", line="", photo_url=None, photo_alt="", badge="Новое 12:00", badge_kind="")
    assert "b-badge__day" not in html
