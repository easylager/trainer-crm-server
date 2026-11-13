"""Вид спорта для строки героя: один вид из направлений, иначе ничего."""

from src.application.catalog_directions import public_sport_name


def test_figure_tabs_share_one_sport() -> None:
    assert public_sport_name(["zero"]) == "Фигурное катание"
    assert public_sport_name(["better", "fig"]) == "Фигурное катание"
    assert public_sport_name(["zero", "better"]) == "Фигурное катание"


def test_hockey_tab_is_hockey() -> None:
    assert public_sport_name(["hock"]) == "Хоккей"


def test_mixed_or_empty_is_not_a_sport() -> None:
    assert public_sport_name(["zero", "hock"]) is None
    assert public_sport_name([]) is None
    assert public_sport_name(["rollers"]) is None
