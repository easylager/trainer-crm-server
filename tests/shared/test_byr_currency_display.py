from src.shared.byr_currency_display import format_kopeks_byn_display, format_rubles_byn_display


def test_format_rubles_byn_display_defaults_to_byn():
    assert format_rubles_byn_display(100) == "100 BYN"
    assert format_rubles_byn_display(99.5) == "99.5 BYN"


def test_format_rubles_byn_display_rub():
    assert format_rubles_byn_display(1500, currency="RUB") == "1500 ₽"
    assert format_rubles_byn_display(990.5, currency="RUB") == "990.5 ₽"


def test_format_kopeks_byn_display_defaults_to_byn():
    assert format_kopeks_byn_display(0) == "0 BYN"
    assert format_kopeks_byn_display(10050) == "100,50 BYN"
    assert format_kopeks_byn_display(10000) == "100 BYN"


def test_format_kopeks_byn_display_rub():
    assert format_kopeks_byn_display(150000, currency="RUB") == "1500 ₽"
    assert format_kopeks_byn_display(99050, currency="RUB") == "990,50 ₽"


def test_format_display_unknown_currency_falls_back_to_code_itself():
    assert format_rubles_byn_display(10, currency="USD") == "10 USD"
