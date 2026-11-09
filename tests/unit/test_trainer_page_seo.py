"""title/description страницы тренера ``/t/…``: один формат у всех, живой текст, ≤160, без выдумок."""

from __future__ import annotations

from src.application.site_trainer_page import DESCRIPTION_LIMIT, page_description, page_title


def _page(**over):
    base = {
        "name": "Александр Гаевский",
        "city_name": "Минск",
        "directions": [{"key": "zero"}, {"key": "better"}],
        "arenas": [{"name": "Замок"}, {"name": "Минск-Арена"}],
        "min_price": (4187, "BYN"),
        "can_book": True,
    }
    return {**base, **over}


def test_title_same_format_for_everyone() -> None:
    assert page_title(_page()) == "Александр Гаевский — тренер по катанию на коньках, Минск · Glideclub"
    assert (
        page_title(_page(name="Мария Соколова", city_name="Санкт-Петербург"))
        == "Мария Соколова — тренер по катанию на коньках, Санкт-Петербург · Glideclub"
    )


def test_description_minsk_live_text_with_price_and_booking() -> None:
    d = page_description(_page())
    # Два катка не помещаются в 160 знаков — остаётся один, фраза цела.
    assert d == (
        "Александр Гаевский ведёт катание с нуля и занятия для тех, кто уже катается на катке «Замок». "
        "Занятие от 41,87 BYN. Записаться можно в Telegram."
    )
    assert len(d) <= DESCRIPTION_LIMIT
    assert "— тренер." not in d and "занимается:" not in d and "…" not in d
    assert "41,87 BYN" in d and "«Замок»" in d


def test_description_spb_rubles() -> None:
    d = page_description(
        _page(
            name="Мария Соколова",
            city_name="Санкт-Петербург",
            directions=[{"key": "fig"}],
            arenas=[{"name": "Ледовый дворец"}],
            min_price=(150000, "RUB"),
        )
    )
    assert d == (
        "Мария Соколова ведёт фигурное катание на катке «Ледовый дворец». Занятие от 1500 руб. "
        "Записаться можно в Telegram."
    )


def test_description_invents_nothing_when_data_is_missing() -> None:
    d = page_description(_page(directions=[], arenas=[], min_price=None, can_book=False))
    assert d == "Александр Гаевский проводит занятия. Написать тренеру можно в Telegram."
    assert "BYN" not in d and "на катк" not in d


def test_description_trimmed_by_phrase_never_mid_word() -> None:
    d = page_description(
        _page(
            name="Константин Александрович Иванов-Петровский-Сидоренко",
            arenas=[{"name": "Ледовый дворец спорта имени Очень Длинного Названия"}] * 2,
            directions=[{"key": "zero"}, {"key": "better"}, {"key": "fig"}, {"key": "hock"}],
        )
    )
    assert len(d) <= DESCRIPTION_LIMIT and d.endswith(".") and "…" not in d
