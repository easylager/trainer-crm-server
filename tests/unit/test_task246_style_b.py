"""TASK-246: вариант города по данным, ровная неделя, время без ведущего нуля, мотив без текста."""

from src.application.catalog_icons import icon_svg, rink_motif_svg
from src.application.city_style_b import VARIANT_MANY, VARIANT_ONE, VARIANT_PHONE, choose_city_variant, price_sentence
from src.application.week_grid import collapse_even_grid
from src.shared.public_display import format_clock


def test_clock_drops_the_leading_hour_zero() -> None:
    assert format_clock("09:00") == "9:00"
    assert format_clock("00:15") == "0:15"
    assert format_clock("12:05") == "12:05"
    assert "09:" not in format_clock("09:30")


def test_city_variant_follows_rink_count_and_schedule_mode() -> None:
    ice = {"venue_type": "ice", "schedule_mode": "auto"}
    phone = {"venue_type": "ice", "schedule_mode": "phone"}
    shop = {"venue_type": "shop", "schedule_mode": "auto"}
    assert choose_city_variant([ice, ice, shop]) == VARIANT_MANY
    assert choose_city_variant([ice, shop]) == VARIANT_ONE
    assert choose_city_variant([phone]) == VARIANT_PHONE
    assert choose_city_variant([phone, phone]) == VARIANT_PHONE
    assert choose_city_variant([ice, phone]) == VARIANT_MANY
    assert choose_city_variant([shop]) == VARIANT_MANY


def test_even_week_grid_collapses_and_a_ragged_one_does_not() -> None:
    assert collapse_even_grid(["12:30", "13:45", "15:00"]) == "с 12:30 каждые 1 ч 15 мин"
    assert collapse_even_grid(["9:00", "10:00"]) is None
    assert collapse_even_grid(["9:00", "10:00", "12:00"]) is None


def test_price_sentence_uses_only_prices_that_exist() -> None:
    rows = [{"price_adult_minor": 330, "price_child_minor": 250, "currency_code": "BYN"}]
    assert price_sentence(rows, has_rental=True, has_sharpening=True) == (
        "Взрослый билет — 3,30 BYN, детский — 2,50 BYN. Есть прокат и заточка"
    )
    assert price_sentence([{"price_child_minor": 250}], has_rental=False, has_sharpening=False) == ""


def test_motif_and_icons_have_no_emoji_and_no_missing_photo_caption() -> None:
    motif = rink_motif_svg()
    assert "нет фото" not in motif
    assert "❄" not in motif
    assert icon_svg("skate").startswith("<svg")
    assert icon_svg("nope") == ""
