"""TASK-260: тренеры на SSR-карточке места — CTA «Перейти» в Telegram."""

from __future__ import annotations

from src.application.place_page import _b_trainers
from src.application.style_b import trainer_rows_html
from src.shared.copy_ru import t


def test_trainer_rows_html_fixed_go_cta() -> None:
    html = trainer_rows_html(
        [{"id": 1, "name": "Анна", "line": "С нуля · от 50 BYN", "can_book": True}],
        href_for=lambda _t: "https://glide.by/open-telegram?startapp=trainer_1",
        cta=t("cta.go"),
    )
    assert "Перейти" in html
    assert "Записаться" not in html


def test_b_trainers_renders_pereiti_and_trainer_startapp() -> None:
    html = _b_trainers(
        {
            "card": {"id": 9, "city_id": 1, "venue_type": "ice"},
            "trainers": [
                {
                    "id": 42,
                    "name": "Александр Гаевский",
                    "line": "С нуля · от 50 BYN за занятие",
                    "can_book": True,
                }
            ],
        },
        base_url="https://glide.by",
    )
    assert 'id="trainers"' in html
    assert "Александр Гаевский" in html
    assert "Перейти" in html
    assert "startapp=trainer_42_a_9" in html
    assert "surface=place_page" in html
