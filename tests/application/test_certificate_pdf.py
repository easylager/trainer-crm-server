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
