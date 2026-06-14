"""
Gift certificate PDF: HTML layout in ``static/templates/certificate_issue.html`` (see also
``docs/certificate-html-constructor.html``) rendered with PyMuPDF Story (A5 portrait).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from src.application.certificate_issue_render import (
    build_certificate_issue_html,
    certificate_html_to_pdf_bytes,
)
from src.shared.config import Settings


def build_certificate_pdf(
    *,
    trainer_name: str,
    product_name: str,
    amount_cents: int,
    code: str,
    recipient_name: str,
    purchased_by_name: Optional[str] = None,
    issued_at: Optional[date] = None,
    expires_at: Optional[date] = None,
    activation_url: Optional[str] = None,
    client_bot_display_name: Optional[str] = None,
    brand_display: Optional[str] = None,
    brand_tagline: Optional[str] = None,
    brand_powered_by: Optional[str] = None,
) -> bytes:
    """
    Produced PDF matches the client/Telegram HTML certificate (email attachment, S3, sample endpoint).
    Branding: explicit args, else ``Settings.certificate_pdf_brand_*``.
    """
    cfg = Settings()
    brand = (brand_display or cfg.certificate_pdf_brand_display_name or "ICE STUDIO").strip()
    tagline = (brand_tagline if brand_tagline is not None else (cfg.certificate_pdf_brand_tagline_ru or "")).strip()

    html = build_certificate_issue_html(
        brand_display=brand,
        brand_tagline=tagline,
        trainer_name=trainer_name,
        product_name=product_name,
        amount_cents=amount_cents,
        code=code,
        recipient_name=recipient_name,
        purchased_by_name=purchased_by_name,
        issued_at=issued_at,
        expires_at=expires_at,
        activation_url=activation_url,
        client_bot_display_name=client_bot_display_name,
        brand_powered_by=brand_powered_by,
    )
    return certificate_html_to_pdf_bytes(html)
