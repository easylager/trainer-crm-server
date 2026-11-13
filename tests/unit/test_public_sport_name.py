"""Вид спорта для строки героя: один вид из направлений, иначе ничего."""

from src.application.catalog_directions import public_sport_name


def test_neutral_tabs_are_not_a_sport() -> None:
    assert public_sport_name(["zero"]) is None
    assert public_sport_name(["better"]) is None
    assert public_sport_name(["zero", "better"]) is None


def test_one_sport_ignores_neutral_tabs() -> None:
    assert public_sport_name(["fig"]) == "Фигурное катание"
    assert public_sport_name(["zero", "fig"]) == "Фигурное катание"
    assert public_sport_name(["better", "fig"]) == "Фигурное катание"
    assert public_sport_name(["hock"]) == "Хоккей"
    assert public_sport_name(["zero", "hock"]) == "Хоккей"
    assert public_sport_name(["zero", "better", "hock"]) == "Хоккей"


def test_both_sports_or_none_is_not_a_sport() -> None:
    assert public_sport_name(["fig", "hock"]) is None
    assert public_sport_name(["zero", "fig", "hock"]) is None
    assert public_sport_name([]) is None
    assert public_sport_name(["rollers"]) is None
