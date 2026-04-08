"""
Gift certificate PDF:
- **Production:** single ReportLab canvas (`_legacy_build_certificate_pdf`) — one coordinate system, aligned price/QR.
- Optional: PyMuPDF template + overlay kept for AcroForm experiments; not used in `build_certificate_pdf`.
"""
from __future__ import annotations

import logging
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.utils import ImageReader

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

from src.application.certificate_layout import CertificateOverlayLayout, RectFrac, load_certificate_layout

logger = logging.getLogger(__name__)

CREAM = "#fffbec"
CREAM_RICH = "#f8f1e4"
TEXT_DARK = "#1a1a1a"
TEXT_WARM = "#4a3728"
TEXT_MUTED = "#8b7355"
AMBER = "#f5a623"
AMBER_BRIGHT = "#ffb84d"
CHARCOAL = "#2c2c2e"

CERTIFICATE_BRAND_FOOTER = "Trainer CRM"
CERTIFICATE_BOT_HINT = "Откройте Telegram-бот, введите код, запишитесь на занятие"

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONT_SEMI = "Helvetica-Bold"
_REGISTERED = False

_A4_W = float(A4[0])
_A4_H = float(A4[1])


def _root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _template_pdf_path() -> Path | None:
    for name in ("certificate_template.pdf", "cerfiticate_template.pdf"):
        p = _root() / "static" / "templates" / name
        if p.is_file():
            return p
    return None


def _font_files() -> tuple[Path | None, Path | None, Path | None]:
    d = _root() / "static" / "fonts"
    return (
        d / "Inter-Regular.ttf",
        d / "Inter-Bold.ttf",
        d / "Inter-SemiBold.ttf",
    )


def _register_fonts() -> None:
    global _FONT, _FONT_BOLD, _FONT_SEMI, _REGISTERED
    if _REGISTERED:
        return
    fonts = _root() / "static" / "fonts"
    for name, file in [("Inter", "Inter-Regular.ttf"), ("InterBold", "Inter-Bold.ttf"), ("InterSemi", "Inter-SemiBold.ttf")]:
        p = fonts / file
        if p.is_file():
            try:
                pdfmetrics.registerFont(TTFont(name, str(p)))
                if name == "Inter":
                    _FONT = name
                elif name == "InterBold":
                    _FONT_BOLD = name
                elif name == "InterSemi":
                    _FONT_SEMI = name
            except Exception:
                pass
    if _FONT_BOLD == "Helvetica-Bold" and _FONT != "Helvetica":
        _FONT_BOLD = _FONT
    if _FONT_SEMI == "Helvetica-Bold":
        _FONT_SEMI = _FONT_BOLD if _FONT_BOLD != "Helvetica-Bold" else _FONT
    _REGISTERED = True


def _hex(h: str) -> colors.Color:
    return colors.HexColor(h)


def _rgb01(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def _format_date(d: Optional[date]) -> str:
    if not d:
        return "—"
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def _format_amount(cents: int) -> str:
    if cents <= 0:
        return "Любая сумма"
    v = cents / 100
    return f"{int(v)}" if v == int(v) else f"{v:.2f}"


def _draw_accent_line(c: canvas.Canvas, x: float, y: float, length: float, thickness: float = 1.5) -> None:
    c.setStrokeColor(_hex(AMBER))
    c.setLineWidth(thickness)
    c.line(x, y, x + length, y)


def build_static_certificate_background_pdf_bytes() -> bytes:
    """
    Single-page A4: decor + static labels only (no dynamic values).
    Used as default certificate_template.pdf — replace with designer file if needed.
    """
    _register_fonts()
    buf = BytesIO()
    w, h = A4
    c = canvas.Canvas(buf, pagesize=A4)
    margin = 24 * mm
    col_w = (w - 2 * margin) / 12

    c.setFillColor(_hex(CREAM))
    c.rect(0, 0, w, h, fill=1, stroke=0)

    c.setStrokeColor(_hex(CREAM_RICH))
    c.setLineWidth(0.3)
    step = int(8 * mm)
    for i in range(0, int(w + h), step):
        c.line(i - h, 0, i, h)

    y = h - 28 * mm
    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_BOLD, 22)
    c.drawString(margin, y, CERTIFICATE_BRAND_FOOTER)

    c.setFillColor(_hex(AMBER))
    c.circle(margin + 76 * mm, y + 6 * mm, 2.5 * mm, fill=1, stroke=0)

    c.setFillColor(_hex(TEXT_MUTED))
    c.setFont(_FONT_SEMI, 8)
    c.drawString(margin, y - 8 * mm, "ПОДАРОЧНЫЙ СЕРТИФИКАТ")

    _draw_accent_line(c, margin, y - 14 * mm, col_w * 4, 2)

    y -= 32 * mm
    name_x = margin
    c.setFillColor(_hex(TEXT_WARM))
    c.setFont(_FONT_SEMI, 9)
    c.drawString(name_x, y, "ДЛЯ")
    y -= 12 * mm

    name_size = 48
    y -= name_size * 0.8
    y -= 12 * mm

    left_x = margin
    left_w = col_w * 7
    right_x = margin + col_w * 8
    right_w = col_w * 4

    prod_h = 6 * mm
    badge_h = 32 * mm
    badge_y = y - badge_h + prod_h

    c.setFillColor(_hex(AMBER))
    c.roundRect(right_x, badge_y, right_w, badge_h, 4 * mm, fill=1, stroke=0)
    c.setFillColor(_hex(AMBER_BRIGHT))
    c.roundRect(right_x, badge_y + badge_h - 8 * mm, right_w, 8 * mm, 4 * mm, fill=1, stroke=0)

    y = badge_y - max(prod_h + 16 * mm, badge_h + 8 * mm)
    detail_y = y

    c.setFillColor(_hex(TEXT_MUTED))
    c.setFont(_FONT, 10)
    c.drawString(left_x, detail_y, "Тренер")
    c.drawString(left_x, detail_y - 8 * mm, "До")

    y = detail_y - 24 * mm
    code_h = 28 * mm
    code_y = y - code_h

    c.setFillColor(_hex(CHARCOAL))
    c.rect(0, code_y, w, code_h, fill=1, stroke=0)
    c.setFillColor(_hex(AMBER))
    c.rect(0, code_y + code_h - 3 * mm, w, 3 * mm, fill=1, stroke=0)
    c.setFillColor(_hex("#9a9a9e"))
    c.setFont(_FONT, 8)
    c.drawCentredString(w / 2, code_y + code_h - 10 * mm, "КОД АКТИВАЦИИ")

    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_BOLD, 9)
    c.drawRightString(w - margin, 12 * mm, CERTIFICATE_BRAND_FOOTER)

    c.setFillColor(_hex(AMBER))
    c.rect(0, 0, w, 2 * mm, fill=1, stroke=0)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


def write_default_certificate_template_file() -> Path:
    """Write static/templates/certificate_template.pdf (idempotent)."""
    out = _root() / "static" / "templates" / "certificate_template.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build_static_certificate_background_pdf_bytes())
    return out


def _frac_to_fitz_rect(page: fitz.Page, rf: RectFrac) -> fitz.Rect:
    pw, ph = page.rect.width, page.rect.height
    r = rf.clamp()
    return fitz.Rect(r.x0 * pw, r.y0 * ph, r.x1 * pw, r.y1 * ph)


def _textbox(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    fontfile: str,
    fontname: str,
    fontsize: float,
    color: tuple[float, float, float],
    align: int = 0,
) -> None:
    t = (text or "").strip() or "—"
    fs = fontsize
    min_fs = max(6.0, fontsize * 0.35)
    while fs >= min_fs:
        rc = page.insert_textbox(
            rect,
            t,
            fontfile=fontfile,
            fontname=fontname,
            fontsize=fs,
            color=color,
            align=align,
        )
        if rc >= 0:
            return
        fs -= 0.75
    page.insert_textbox(rect, t, fontfile=fontfile, fontname=fontname, fontsize=min_fs, color=color, align=align)


def _acroform_values(
    *,
    trainer_name: str,
    product_name: str,
    amount_cents: int,
    code: str,
    recipient_name: str,
    purchased_by_name: Optional[str],
    issued_at: Optional[date],
    expires_at: Optional[date],
    footer_hint: str,
) -> dict[str, str]:
    amount_str = _format_amount(amount_cents)
    expires_str = _format_date(expires_at) if expires_at else "бессрочно"
    issued_str = _format_date(issued_at)
    purchased = (purchased_by_name or "").strip()
    return {
        "recipient_name": (recipient_name or "").strip() or "—",
        "product_title": (product_name or "").strip() or "Сертификат",
        "amount": amount_str,
        "amount_currency": "BYN",
        "trainer_display_name": (trainer_name or "").strip() or "—",
        "expires_at": expires_str,
        "issued_at": issued_str,
        "code": (code or "").strip() or "—",
        "purchased_by_name": purchased,
        "footer_hint": footer_hint,
    }


def _try_fill_acroform(doc: fitz.Document, values: dict[str, str]) -> bool:
    """Fill PDF form fields when names match. Returns True if at least one field updated."""
    updated = False
    for pi in range(doc.page_count):
        page = doc[pi]
        for w in page.widgets() or []:
            name = (w.field_name or "").strip()
            if not name:
                continue
            if name not in values:
                continue
            w.field_value = values[name]
            w.update()
            updated = True
    return updated


def _insert_qr(page: fitz.Page, rect: fitz.Rect, payload: str) -> None:
    if not payload.strip():
        return
    try:
        import qrcode
        from PIL import Image
    except ImportError:
        logger.warning("qrcode or PIL missing; skip QR on certificate")
        return
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    # qrcode returns PilImage (wrapper), not PIL.Image.Image — raster is from get_image().
    pil_img = img.get_image() if hasattr(img, "get_image") else img
    if not isinstance(pil_img, Image.Image):
        logger.warning("Unexpected QR image type %s; skip QR on certificate", type(img))
        return
    buf = BytesIO()
    pil_img.save(buf, format="PNG")
    page.insert_image(rect, stream=buf.getvalue())


def _overlay_certificate_fields(
    page: fitz.Page,
    layout: CertificateOverlayLayout,
    *,
    recipient: str,
    product: str,
    amount_str: str,
    trainer: str,
    expires_str: str,
    code_str: str,
    issue_str: str,
    hint: str,
    brand: str,
    font_reg: str,
    font_bold: str,
    font_semi: str,
    activation_url: Optional[str],
) -> None:
    fs = layout.font_scale * min(page.rect.width / _A4_W, page.rect.height / _A4_H)
    _fn_i = 0

    def tb(rf: RectFrac, text: str, *, size: float, bold: bool = False, semi: bool = False, color: tuple[float, float, float], align: int = 0) -> None:
        nonlocal _fn_i
        rect = _frac_to_fitz_rect(page, rf)
        if rect.width <= 2 or rect.height <= 2:
            return
        ff = font_bold if bold else (font_semi if semi else font_reg)
        _fn_i += 1
        fn = f"ix{_fn_i}"
        _textbox(page, rect, text, fontfile=ff, fontname=fn, fontsize=size * fs, color=color, align=align)

    tb(layout.recipient, recipient, size=40, bold=True, color=_rgb01(TEXT_DARK), align=0)
    tb(layout.product_title, product, size=15, semi=True, color=_rgb01(TEXT_DARK), align=0)
    tb(layout.amount, amount_str, size=22, bold=True, color=_rgb01(TEXT_DARK), align=1)
    tb(layout.amount_currency, "BYN", size=9, semi=True, color=_rgb01(TEXT_DARK), align=1)

    if layout.draw_field_labels_on_overlay:
        tb(
            RectFrac(layout.trainer_value.x0 - 0.12, layout.trainer_value.y0, layout.trainer_value.x0, layout.trainer_value.y1),
            "Тренер",
            size=9,
            color=_rgb01(TEXT_MUTED),
            align=0,
        )
        tb(
            RectFrac(layout.expires_value.x0 - 0.12, layout.expires_value.y0, layout.expires_value.x0, layout.expires_value.y1),
            "До",
            size=9,
            color=_rgb01(TEXT_MUTED),
            align=0,
        )

    tb(layout.trainer_value, trainer, size=9, semi=True, color=_rgb01(TEXT_DARK), align=0)
    tb(layout.expires_value, expires_str, size=9, semi=True, color=_rgb01(TEXT_DARK), align=0)

    code_col = (1.0, 1.0, 1.0) if layout.code_color_light else _rgb01(TEXT_DARK)
    tb(layout.code, code_str, size=24, bold=True, color=code_col, align=1)

    tb(layout.issued_line, issue_str, size=7.5, color=_rgb01(TEXT_MUTED), align=0)
    tb(layout.hint, hint, size=7.5, color=_rgb01(TEXT_MUTED), align=0)

    if not layout.skip_brand_footer_overlay:
        tb(layout.brand_footer, brand, size=8, bold=True, color=_rgb01(TEXT_DARK), align=2)

    if layout.qr and activation_url:
        _insert_qr(page, _frac_to_fitz_rect(page, layout.qr), activation_url)


def _build_on_template(
    template_path: Path,
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
) -> bytes:
    assert fitz is not None
    reg, bold, semi = _font_files()
    if not reg or not reg.is_file():
        raise FileNotFoundError("Inter-Regular.ttf missing for template overlay")

    font_reg = str(reg)
    font_bold = str(bold) if bold and bold.is_file() else font_reg
    font_semi = str(semi) if semi and semi.is_file() else font_bold

    footer_hint = CERTIFICATE_BOT_HINT
    values = _acroform_values(
        trainer_name=trainer_name,
        product_name=product_name,
        amount_cents=amount_cents,
        code=code,
        recipient_name=recipient_name,
        purchased_by_name=purchased_by_name,
        issued_at=issued_at,
        expires_at=expires_at,
        footer_hint=footer_hint,
    )

    doc = fitz.open(template_path)
    try:
        try:
            if _try_fill_acroform(doc, values):
                return doc.tobytes(deflate=True, garbage=4, clean=True)
        except Exception as e:
            logger.warning("AcroForm fill failed, falling back to overlay: %s", e)

        layout = load_certificate_layout()
        page = doc[0]
        recipient = (recipient_name or "").strip() or "Получатель"
        product = (product_name or "Сертификат").strip()
        amount_str = _format_amount(amount_cents)
        trainer = (trainer_name or "").strip() or "—"
        expires_str = _format_date(expires_at) if expires_at else "бессрочно"
        code_str = (code or "").strip() or "—"
        issue_str = f"Выдан {_format_date(issued_at)}"
        if (purchased_by_name or "").strip():
            issue_str += f" • {(purchased_by_name or '').strip()}"

        _overlay_certificate_fields(
            page,
            layout,
            recipient=recipient,
            product=product,
            amount_str=amount_str,
            trainer=trainer,
            expires_str=expires_str,
            code_str=code_str,
            issue_str=issue_str,
            hint=footer_hint,
            brand=CERTIFICATE_BRAND_FOOTER,
            font_reg=font_reg,
            font_bold=font_bold,
            font_semi=font_semi,
            activation_url=activation_url,
        )
        return doc.tobytes(deflate=True, garbage=4, clean=True)
    finally:
        doc.close()


def _qr_png_bytes(payload: str) -> Optional[bytes]:
    """PNG bytes for QR or None if qrcode/PIL missing."""
    if not (payload or "").strip():
        return None
    try:
        import qrcode
        from PIL import Image
    except ImportError:
        return None
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    pil_img = img.get_image() if hasattr(img, "get_image") else img
    if not isinstance(pil_img, Image.Image):
        return None
    buf = BytesIO()
    pil_img.save(buf, format="PNG")
    return buf.getvalue()


def _legacy_build_certificate_pdf(
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
) -> bytes:
    _register_fonts()
    buf = BytesIO()
    w, h = A4
    c = canvas.Canvas(buf, pagesize=A4)

    margin = 24 * mm
    col_w = (w - 2 * margin) / 12

    c.setFillColor(_hex(CREAM))
    c.rect(0, 0, w, h, fill=1, stroke=0)

    c.setStrokeColor(_hex(CREAM_RICH))
    c.setLineWidth(0.3)
    step = int(8 * mm)
    for i in range(0, int(w + h), step):
        c.line(i - h, 0, i, h)

    y = h - 28 * mm

    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_BOLD, 22)
    c.drawString(margin, y, CERTIFICATE_BRAND_FOOTER)

    c.setFillColor(_hex(AMBER))
    c.circle(margin + 76 * mm, y + 6 * mm, 2.5 * mm, fill=1, stroke=0)

    c.setFillColor(_hex(TEXT_MUTED))
    c.setFont(_FONT_SEMI, 8)
    c.drawString(margin, y - 8 * mm, "ПОДАРОЧНЫЙ СЕРТИФИКАТ")

    _draw_accent_line(c, margin, y - 14 * mm, col_w * 4, 2)

    y -= 32 * mm

    name_x = margin
    c.setFillColor(_hex(TEXT_WARM))
    c.setFont(_FONT_SEMI, 9)
    c.drawString(name_x, y, "ДЛЯ")
    y -= 12 * mm

    recipient = (recipient_name or "").strip() or "Получателя"
    name_size = 48 if len(recipient) <= 10 else (36 if len(recipient) <= 18 else 28)

    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_BOLD, name_size)

    if len(recipient) > 25:
        words = recipient.split()
        mid = len(words) // 2
        line1 = " ".join(words[:mid])
        line2 = " ".join(words[mid:])
        c.drawString(name_x, y, line1)
        y -= name_size * 0.8
        c.drawString(name_x, y, line2)
        y -= name_size * 0.6
    else:
        c.drawString(name_x, y, recipient)
        y -= name_size * 0.8

    y -= 12 * mm

    left_x = margin
    left_w = col_w * 7

    right_x = margin + col_w * 8
    right_w = col_w * 4

    product = (product_name or "Сертификат").strip()
    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_SEMI, 16)

    if len(product) > 35:
        style = ParagraphStyle("Prod", fontName=_FONT_SEMI, fontSize=16, leading=20, textColor=_hex(TEXT_DARK))
        p = Paragraph(escape(product), style)
        pw, ph = p.wrap(left_w, 40 * mm)
        p.drawOn(c, left_x, y - ph + 4 * mm)
        prod_h = ph
    else:
        c.drawString(left_x, y, product)
        prod_h = 6 * mm

    badge_h = 32 * mm
    badge_y = y - badge_h + prod_h

    c.setFillColor(_hex(AMBER))
    c.roundRect(right_x, badge_y, right_w, badge_h, 4 * mm, fill=1, stroke=0)

    c.setFillColor(_hex(AMBER_BRIGHT))
    c.roundRect(right_x, badge_y + badge_h - 8 * mm, right_w, 8 * mm, 4 * mm, fill=1, stroke=0)

    amount_str = _format_amount(amount_cents)
    # Badge: main amber is badge_y..badge_y+24mm; top 8mm is lighter amber (drawn second).
    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_BOLD, 24)
    c.drawCentredString(right_x + right_w / 2, badge_y + 12 * mm, amount_str)

    c.setFont(_FONT_SEMI, 10)
    c.drawCentredString(right_x + right_w / 2, badge_y + badge_h - 4 * mm, "BYN")

    y -= max(prod_h + 16 * mm, badge_h + 8 * mm)

    detail_y = y

    c.setFillColor(_hex(TEXT_MUTED))
    c.setFont(_FONT, 10)
    c.drawString(left_x, detail_y, "Тренер")
    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_SEMI, 10)
    c.drawString(left_x + 18 * mm, detail_y, (trainer_name or "").strip() or "—")
    detail_y -= 8 * mm

    c.setFillColor(_hex(TEXT_MUTED))
    c.setFont(_FONT, 10)
    c.drawString(left_x, detail_y, "До")
    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_SEMI, 10)
    expires_str = _format_date(expires_at) if expires_at else "бессрочно"
    c.drawString(left_x + 18 * mm, detail_y, expires_str)

    # detail_y is «До» row baseline; strip top = detail_y − 24mm → ~24mm band above charcoal bar for QR.
    strip_top = detail_y - 24 * mm
    code_h = 28 * mm
    code_y = strip_top - code_h
    if activation_url:
        png = _qr_png_bytes(activation_url)
        if png:
            m = 2 * mm
            gap_top = detail_y - m
            gap_bottom = strip_top + m
            gap_h = gap_top - gap_bottom
            if gap_h >= 8 * mm:
                qr_side = min(22 * mm, gap_h - 1 * mm)
                qr_side = max(10 * mm, qr_side)
                y_qr = gap_bottom + (gap_h - qr_side) / 2
                x_qr = right_x + (right_w - qr_side) / 2
                c.drawImage(ImageReader(BytesIO(png)), x_qr, y_qr, width=qr_side, height=qr_side, mask="auto")

    c.setFillColor(_hex(CHARCOAL))
    c.rect(0, code_y, w, code_h, fill=1, stroke=0)

    c.setFillColor(_hex(AMBER))
    c.rect(0, code_y + code_h - 3 * mm, w, 3 * mm, fill=1, stroke=0)

    c.setFillColor(_hex("#9a9a9e"))
    c.setFont(_FONT, 8)
    c.drawCentredString(w / 2, code_y + code_h - 10 * mm, "КОД АКТИВАЦИИ")

    code_str = (code or "").strip() or "—"
    c.setFillColor(colors.white)
    c.setFont(_FONT_BOLD, 28)
    code_w = c.stringWidth(code_str, _FONT_BOLD, 28)
    start_x = (w - code_w) / 2
    c.drawString(start_x, code_y + 8 * mm, code_str)

    y = code_y - 16 * mm

    c.setFillColor(_hex(TEXT_MUTED))
    c.setFont(_FONT, 8)
    issue_str = f"Выдан {_format_date(issued_at)}"
    if (purchased_by_name or "").strip():
        issue_str += f" • {purchased_by_name.strip()}"
    c.drawString(margin, y, issue_str)

    y -= 8 * mm
    c.drawString(margin, y, CERTIFICATE_BOT_HINT)

    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_BOLD, 9)
    c.drawRightString(w - margin, 12 * mm, CERTIFICATE_BRAND_FOOTER)

    c.setFillColor(_hex(AMBER))
    c.rect(0, 0, w, 2 * mm, fill=1, stroke=0)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


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
) -> bytes:
    """
    Single ReportLab layout: price/BYN/QR share one coordinate system (no PyMuPDF overlay drift).
    activation_url: optional deep link for QR (e.g. t.me/bot?start=cert_CODE).
    """
    return _legacy_build_certificate_pdf(
        trainer_name=trainer_name,
        product_name=product_name,
        amount_cents=amount_cents,
        code=code,
        recipient_name=recipient_name,
        purchased_by_name=purchased_by_name,
        issued_at=issued_at,
        expires_at=expires_at,
        activation_url=activation_url,
    )
