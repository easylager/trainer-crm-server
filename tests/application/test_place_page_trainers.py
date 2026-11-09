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


def test_b_trainers_lists_site_pages() -> None:
    """Тренеры на катке — строки на ``/t/…`` и ссылка в каталог города."""
    view = {
        "card": {"id": 9, "city_id": 1, "venue_type": "ice", "city_name": "Минск"},
        "trainers": [{"id": 42, "name": "Александр Гаевский", "line": "С нуля · от 50 BYN", "can_book": True}],
    }
    html = _b_trainers(view)
    assert "Александр Гаевский" in html
    assert 'href="/t/42-' in html and "?via=p9" in html
    assert 'href="/c/minsk/trenery?arena=9"' in html or 'href="/trenery?arena=9"' in html
    assert "startapp=" not in html
