"""Легенда карты главной следует фильтру when."""

from __future__ import annotations

from src.application.catalog_home_page import home_map_legend_labels


def test_map_legend_follows_when_filter() -> None:
    assert home_map_legend_labels("today") == ("лёд сегодня", "сегодня нет")
    assert home_map_legend_labels("tomorrow") == ("лёд завтра", "завтра нет")
    assert home_map_legend_labels("weekend") == ("лёд в выходные", "в выходные нет")
    assert home_map_legend_labels("day") == ("лёд сегодня", "сегодня нет")
