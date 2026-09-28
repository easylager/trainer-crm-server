"""Certificate PDF: HTML Story layout."""

from datetime import date

import fitz

from src.application.certificate_pdf import build_certificate_pdf


def test_build_certificate_pdf_single_page_html() -> None:
    b = build_certificate_pdf(
        trainer_name="Иван Иванов",
        product_name="Подарочный сертификат",
        amount_cents=5000,
        code="ABC-TEST-1",
        recipient_name="Получатель Тест",
        purchased_by_name="Покупатель",
        issued_at=date(2026, 3, 30),
        expires_at=None,
        activation_url="https://t.me/test_bot?start=cert_ABC-TEST-1",
        client_bot_display_name="@test_bot",
    )
    assert len(b) > 1000
    doc = fitz.open(stream=b, filetype="pdf")
    assert doc.page_count == 1
    doc.close()


def test_certificate_pdf_prints_the_code_and_fits_one_page() -> None:
    """
    Регрессия: код на листе должен быть.

    Тёмная полоска с кодом версталась через CSS-переменные и flex, которых PyMuPDF Story не
    понимает: страница переполнялась, и полоска вместе с кодом просто не попадала в PDF.
    Клиент получал сертификат, который нечем активировать. Проверяем то, ради чего документ
    существует: код, номинал и то, что всё это уместилось на одной странице.
    """
    code = "GIFT-4K2P-9XQ1"
    b = build_certificate_pdf(
        trainer_name="Максим Василенко",
        product_name="Персональная тренировка на льду",
        amount_cents=15000,
        code=code,
        recipient_name="Иван Иванов",
        purchased_by_name="Анна",
        issued_at=date(2026, 9, 28),
        expires_at=date(2027, 3, 28),
        activation_url=f"https://t.me/ice_studio_bot?start=cert_{code}",
        client_bot_display_name="@ice_studio_bot",
    )
    doc = fitz.open(stream=b, filetype="pdf")
    assert doc.page_count == 1
    text = doc[0].get_text()
    doc.close()
    assert code in text.replace("\n", "")
    assert "КОД АКТИВАЦИИ" in text
    assert "150" in text and "BYN" in text
    assert "Абонементы и сертификаты" in text.replace("\n", " ").replace("  ", " ")


def test_certificate_pdf_without_qr_does_not_tell_you_to_scan_it() -> None:
    """Без ссылки активации QR на листе нет — и шага «отсканируйте» тоже быть не должно."""
    b = build_certificate_pdf(
        trainer_name="Максим",
        product_name="Открытый номинал",
        amount_cents=0,
        code="CERT-ABC123",
        recipient_name="Александра",
        issued_at=date(2026, 9, 28),
        activation_url=None,
        client_bot_display_name=None,
    )
    doc = fitz.open(stream=b, filetype="pdf")
    assert doc.page_count == 1
    text = doc[0].get_text()
    doc.close()
    assert "Отсканируйте" not in text
    assert "CERT-ABC123" in text.replace("\n", "")
