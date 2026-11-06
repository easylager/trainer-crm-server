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


def test_b_trainers_link_to_trainer_page_with_can_book_label() -> None:
    def view(can_book: bool) -> dict:
        return {
            "card": {"id": 9, "city_id": 1, "venue_type": "ice"},
            "trainers": [
                {"id": 42, "name": "Александр Гаевский", "line": "С нуля · от 50 BYN за занятие", "can_book": can_book}
            ],
        }

    html = _b_trainers(view(True), base_url="https://glide.by")
    assert 'id="trainers"' in html
    assert "Александр Гаевский" in html
    assert 'href="https://glide.by/t/42-aleksandr-gaevskiy"' in html
    assert "startapp=" not in html
    assert "Записаться" in html and "Перейти" not in html
    # Без подписки с онлайн-записью карточка бесплатная — «Написать», не «Записаться» (PDEC-025).
    free = _b_trainers(view(False), base_url="https://glide.by")
    assert "Написать" in free and "Записаться" not in free
