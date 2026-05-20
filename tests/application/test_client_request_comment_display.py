"""Client-visible comment strips pass/certificate order machine lines."""

from src.application.client_cert_order_use_cases import build_certificate_product_order_comment
from src.application.client_pass_order_use_cases import (
    PASS_ORDER_LINE_PREFIX,
    build_pass_product_order_comment,
)
from src.application.client_request_comment_display import (
    client_request_comment_editable,
    client_request_subtype,
    client_visible_request_comment,
)


def test_pass_order_comment_shows_human_block_only() -> None:
    raw = build_pass_product_order_comment(
        pass_product_id=7,
        human_block="Хочу абонемент на 10 занятий",
    )
    assert PASS_ORDER_LINE_PREFIX in raw
    assert client_visible_request_comment(raw) == "Хочу абонемент на 10 занятий"


def test_pass_order_marker_only_returns_none() -> None:
    raw = f"{PASS_ORDER_LINE_PREFIX}7"
    assert client_visible_request_comment(raw) is None


def test_cert_order_comment_strips_meta_line() -> None:
    raw = build_certificate_product_order_comment(
        certificate_product_id=3,
        recipient_email="a@b.c",
        recipient_name="Иван",
        purchased_by_name=None,
        human_block="Подарок маме",
        requested_nominal_cents=10000,
    )
    visible = client_visible_request_comment(raw)
    assert visible == "Подарок маме"
    assert "__CERT_ORDER" not in (visible or "")
    assert "__CERT_ORDER_META__" not in (visible or "")


def test_plain_comment_unchanged() -> None:
    assert client_visible_request_comment("  Нужен тренер по плаванию  ") == "Нужен тренер по плаванию"


def test_cert_and_pass_orders_not_editable() -> None:
    cert_raw = build_certificate_product_order_comment(
        certificate_product_id=1,
        recipient_email="a@b.c",
        recipient_name="Иван",
        purchased_by_name=None,
        human_block="Подарок",
    )
    assert client_request_subtype(cert_raw) == "certificate_product_order"
    assert client_request_comment_editable(cert_raw) is False

    pass_raw = build_pass_product_order_comment(pass_product_id=2, human_block="Хочу абонемент")
    assert client_request_subtype(pass_raw) == "pass_product_order"
    assert client_request_comment_editable(pass_raw) is False

    assert client_request_comment_editable("Обычная заявка") is True
    assert client_request_subtype("Обычная заявка") is None
