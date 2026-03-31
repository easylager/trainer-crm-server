"""
Certificate PDF overlay layout: fractions of page (origin top-left, x/y in 0..1).

Tuned for static/templates/certificate_template.pdf (A4 programmatic background).
Override via static/templates/certificate_layout.json when you replace the PDF or adjust alignment.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@dataclass
class RectFrac:
    """Inclusive box: (0,0) top-left of page, (1,1) bottom-right."""

    x0: float
    y0: float
    x1: float
    y1: float

    def clamp(self) -> RectFrac:
        return RectFrac(
            x0=max(0.0, min(1.0, self.x0)),
            y0=max(0.0, min(1.0, self.y0)),
            x1=max(0.0, min(1.0, self.x1)),
            y1=max(0.0, min(1.0, self.y1)),
        )


@dataclass
class CertificateOverlayLayout:
    """Where to draw dynamic text / QR relative to page size."""

    recipient: RectFrac
    product_title: RectFrac
    amount: RectFrac
    amount_currency: RectFrac
    trainer_value: RectFrac
    expires_value: RectFrac
    code: RectFrac
    issued_line: RectFrac
    hint: RectFrac
    brand_footer: RectFrac
    qr: RectFrac | None = None
    # If True, overlay also draws small labels (e.g. «Тренер»). False when template already has them.
    draw_field_labels_on_overlay: bool = False
    # If True, skip drawing brand line (already on static background).
    skip_brand_footer_overlay: bool = True

    font_scale: float = 1.0
    code_color_light: bool = True  # white code on dark strip


def _default_layout() -> CertificateOverlayLayout:
    """A4 portrait (~595×842 pt): matches programmatic background in certificate_pdf."""
    return CertificateOverlayLayout(
        recipient=RectFrac(0.097, 0.245, 0.78, 0.36),
        product_title=RectFrac(0.097, 0.38, 0.62, 0.445),
        amount=RectFrac(0.66, 0.395, 0.93, 0.455),
        amount_currency=RectFrac(0.66, 0.455, 0.93, 0.48),
        trainer_value=RectFrac(0.22, 0.52, 0.75, 0.545),
        expires_value=RectFrac(0.22, 0.555, 0.75, 0.58),
        code=RectFrac(0.06, 0.66, 0.94, 0.715),
        issued_line=RectFrac(0.097, 0.74, 0.88, 0.765),
        hint=RectFrac(0.097, 0.77, 0.92, 0.795),
        brand_footer=RectFrac(0.097, 0.92, 0.9, 0.97),
        qr=RectFrac(0.62, 0.52, 0.93, 0.64),
        draw_field_labels_on_overlay=False,
        skip_brand_footer_overlay=True,
        font_scale=1.0,
        code_color_light=True,
    )


def _rect_from_dict(d: dict[str, Any]) -> RectFrac:
    return RectFrac(
        float(d["x0"]),
        float(d["y0"]),
        float(d["x1"]),
        float(d["y1"]),
    )


def load_certificate_layout() -> CertificateOverlayLayout:
    """Load JSON override next to template, else defaults."""
    import json

    d = _default_layout()
    p = _root() / "static" / "templates" / "certificate_layout.json"
    if not p.is_file():
        return d
    try:
        base = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(base, dict):
            return d
        if "recipient" in base:
            d.recipient = _rect_from_dict(base["recipient"])
        if "product_title" in base:
            d.product_title = _rect_from_dict(base["product_title"])
        if "amount" in base:
            d.amount = _rect_from_dict(base["amount"])
        if "amount_currency" in base:
            d.amount_currency = _rect_from_dict(base["amount_currency"])
        if "trainer_value" in base:
            d.trainer_value = _rect_from_dict(base["trainer_value"])
        if "expires_value" in base:
            d.expires_value = _rect_from_dict(base["expires_value"])
        if "code" in base:
            d.code = _rect_from_dict(base["code"])
        if "issued_line" in base:
            d.issued_line = _rect_from_dict(base["issued_line"])
        if "hint" in base:
            d.hint = _rect_from_dict(base["hint"])
        if "brand_footer" in base:
            d.brand_footer = _rect_from_dict(base["brand_footer"])
        if base.get("qr"):
            d.qr = _rect_from_dict(base["qr"])
        if "draw_field_labels_on_overlay" in base:
            d.draw_field_labels_on_overlay = bool(base["draw_field_labels_on_overlay"])
        if "font_scale" in base:
            d.font_scale = float(base["font_scale"])
        if "code_color_light" in base:
            d.code_color_light = bool(base["code_color_light"])
        if "skip_brand_footer_overlay" in base:
            d.skip_brand_footer_overlay = bool(base["skip_brand_footer_overlay"])
    except (KeyError, TypeError, ValueError, OSError) as e:
        logger.warning("certificate_layout.json parse issue, using defaults: %s", e)
    return d
