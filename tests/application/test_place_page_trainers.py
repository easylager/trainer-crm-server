"""TASK-260 → TASK-350: тренеры на SSR-карточке места — одна карточка, тап на страницу тренера ``/t/…``."""

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


def test_b_trainers_has_no_trainer_list() -> None:
    """TASK-354: тренеры катка — единый блок «Учиться с тренером»; в разделе «Тренеры» списка нет."""
    view = {
        "card": {"id": 9, "city_id": 1, "venue_type": "ice"},
        "trainers": [{"id": 42, "name": "Александр Гаевский", "line": "С нуля · от 50 BYN", "can_book": True}],
    }
    html = _b_trainers(view)
    assert "Александр Гаевский" not in html
    assert "startapp=" not in html
