"""Одна подпись рейтинга тренера: «★ 5,0 · 2 оценки» с первой оценки."""

from src.application.site_trainer_catalog import _rating_html
from src.application.site_trainer_page import _rating_ok, jsonld
from src.shared.ru_text import trainer_rating_caption


def test_caption_for_zero_one_two_and_seven() -> None:
    assert trainer_rating_caption(5, 0) == ""
    assert trainer_rating_caption(None, 2) == ""
    assert trainer_rating_caption(0, 2) == ""
    assert trainer_rating_caption(5, 1) == "★ 5,0 · 1 оценка"
    assert trainer_rating_caption(5, 2) == "★ 5,0 · 2 оценки"
    assert trainer_rating_caption(5, 7) == "★ 5,0 · 7 оценок"


def test_site_uses_the_same_caption() -> None:
    assert _rating_html({"rating_avg": 5, "rating_count": 0}) == ""
    assert _rating_html({"rating_avg": 5, "rating_count": 1}) == (
        '<div class="tc-rate"><i aria-hidden="true">★</i>5,0 <span>· 1 оценка</span></div>'
    )
    assert "2 оценки" in _rating_html({"rating_avg": 5, "rating_count": 2})
    assert "7 оценок" in _rating_html({"rating_avg": 4.96, "rating_count": 7})
    assert _rating_ok({"rating_avg": 5, "rating_count": 0}) is False
    assert _rating_ok({"rating_avg": 5, "rating_count": 1}) is True
    assert _rating_ok({"rating_avg": 5, "rating_count": 2}) is True
    assert _rating_ok({"rating_avg": 5, "rating_count": 7}) is True


def test_jsonld_does_not_add_aggregate_rating() -> None:
    payload = jsonld(
        {
            "name": "Влад Сак",
            "rating_avg": 5,
            "rating_count": 2,
            "city_name": "Минск",
            "arenas": [],
        },
        canonical="https://glideclub.by/t/11-vlad-sak",
        base_url="https://glideclub.by",
    )
    assert "AggregateRating" not in payload
    assert "ratingCount" not in payload
