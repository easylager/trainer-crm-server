"""Два мира — белорусский (BYN) и русский (руб.): одна подпись валюты на всех серверных текстах."""

from __future__ import annotations

import pytest

from src.application.arena_public_use_cases import _format_price_minor as arena_price
from src.application.certificate_issue_render import _amount_row_html
from src.application.certificate_use_cases import default_certificate_product_name
from src.application.city_style_b import _money
from src.application.ice_city_day import format_price_minor
from src.bot.messages import money_text
from src.shared.byr_currency_display import format_kopeks_byn_display, format_rubles_byn_display


@pytest.mark.parametrize(
    ("fn", "args", "byn", "rub"),
    [
        (format_price_minor, (850,), "8,50 BYN", "8,50 руб."),
        (format_price_minor, (1200,), "12 BYN", "12 руб."),
        (_money, (1200,), "12 BYN", "12 руб."),
        (arena_price, (500,), "5 BYN", "5 руб."),
    ],
)
def test_server_price_text_follows_the_currency(fn, args, byn, rub):
    assert fn(*args, "BYN") == byn
    assert fn(*args, "RUB") == rub


def test_no_server_price_text_ever_prints_the_iso_code_for_rubles():
    for text in (format_price_minor(5000, "RUB"), _money(5000, "RUB"), arena_price(5000, "RUB")):
        assert "RUB" not in text and "₽" not in text


def test_bot_and_digest_money_use_the_same_label():
    assert money_text(5000, "RUB") == "50 руб."
    assert money_text(4050, "BYN") == "40,50 BYN"
    assert format_rubles_byn_display(500, "RUB") == "500 руб."
    assert format_kopeks_byn_display(4050, "RUB") == "40,50 руб."


def test_certificate_name_and_image_are_in_the_trainers_currency():
    assert default_certificate_product_name(10000) == "Сертификат 100 BYN"
    assert default_certificate_product_name(10000, "RUB") == "Сертификат 100 руб."
    assert "руб." in _amount_row_html(10000, "RUB") and "BYN" not in _amount_row_html(10000, "RUB")
    assert "BYN" in _amount_row_html(10000)
