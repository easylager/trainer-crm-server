"""Certificate PDF: template overlay / legacy."""
from datetime import date

import fitz

from src.application.certificate_pdf import build_certificate_pdf, build_static_certificate_background_pdf_bytes


def test_static_background_is_valid_pdf() -> None:
    b = build_static_certificate_background_pdf_bytes()
    assert len(b) > 1000
    doc = fitz.open(stream=b, filetype="pdf")
    assert doc.page_count == 1
    doc.close()


def test_build_certificate_pdf_template_overlay() -> None:
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
    )
    assert len(b) > 1000
    doc = fitz.open(stream=b, filetype="pdf")
    assert doc.page_count == 1
    doc.close()
