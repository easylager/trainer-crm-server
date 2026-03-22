"""
JustSkate gift certificate PDF: editorial layout, diagonal accent, strong typography.
Cyrillic via registered TTF. Design: motion/ice vibe, one hero (recipient), code as token.
"""
from datetime import date
from pathlib import Path
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

# JustSkate palette
JS_BLACK = "#0D0D0D"
JS_YELLOW = "#F7A600"
JS_AMBER = "#C77B00"
JS_CREAM = "#FFF8ED"
JS_CREAM_DARK = "#F5E6D3"
JS_WHITE = "#FFFFFF"
JS_GRAY = "#6B6B6B"

_CERT_FONT = "Helvetica"
_CERT_FONT_BOLD = "Helvetica-Bold"
_CERT_FONT_HEAD = "Helvetica-Bold"
_FONT_REGISTERED = False


def _register_cyrillic_font() -> None:
    global _CERT_FONT, _CERT_FONT_BOLD, _CERT_FONT_HEAD, _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    base = Path(__file__).resolve().parent
    root = base.parent.parent
    candidates = [
        root / "static" / "fonts" / "DejaVuSans.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            try:
                pdfmetrics.registerFont(TTFont("CertFont", str(path)))
                _CERT_FONT = "CertFont"
                _CERT_FONT_BOLD = "CertFont"
                break
            except Exception:
                continue
    bold_candidates = [
        root / "static" / "fonts" / "DejaVuSans-Bold.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]
    for path in bold_candidates:
        if path.is_file():
            try:
                pdfmetrics.registerFont(TTFont("CertFontBold", str(path)))
                _CERT_FONT_BOLD = "CertFontBold"
                break
            except Exception:
                pass
    serif_candidates = [
        root / "static" / "fonts" / "DejaVuSerif-Bold.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSerif-Bold.ttf"),
    ]
    for path in serif_candidates:
        if path.is_file():
            try:
                pdfmetrics.registerFont(TTFont("CertFontHead", str(path)))
                _CERT_FONT_HEAD = "CertFontHead"
                break
            except Exception:
                pass
    if _CERT_FONT_HEAD == "Helvetica-Bold":
        _CERT_FONT_HEAD = _CERT_FONT_BOLD if _CERT_FONT_BOLD != "Helvetica-Bold" else _CERT_FONT
    _FONT_REGISTERED = True


def _fmt_date(d: Optional[date]) -> str:
    if d is None:
        return "—"
    if hasattr(d, "strftime"):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _fmt_expires(expires_at: Optional[date]) -> str:
    if expires_at is None:
        return "без ограничения"
    return _fmt_date(expires_at)


def _fmt_amount(amount_cents: int) -> str:
    if amount_cents <= 0:
        return "на сумму по договорённости"
    byn = amount_cents / 100
    return f"{byn:.2f} BYN"


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
) -> bytes:
    """
    A4 certificate: diagonal yellow stripe (motion), editorial type, recipient as hero, code as token.
    """
    _register_cyrillic_font()
    buf = BytesIO()
    w, h = A4
    c = canvas.Canvas(buf, pagesize=A4)

    margin = 22 * mm
    safe_left = margin
    safe_right = w - margin
    content_w = safe_right - safe_left

    # ---- 1. Diagonal stripe (top-right to bottom-left): motion / ice blade feel ----
    c.saveState()
    c.setFillColor(colors.HexColor(JS_YELLOW))
    c.translate(w, h)
    c.rotate(-42)
    c.rect(-20 * mm, -180 * mm, 24 * mm, 400 * mm, fill=1, stroke=0)
    c.restoreState()

    # ---- 2. Top bar: black band + yellow accent line + wordmark ----
    bar_h = 28 * mm
    c.setFillColor(colors.HexColor(JS_BLACK))
    c.rect(0, h - bar_h, w, bar_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor(JS_YELLOW))
    c.rect(0, h - bar_h, w, 2 * mm, fill=1, stroke=0)
    c.setFillColor(colors.HexColor(JS_WHITE))
    c.setFont(_CERT_FONT_BOLD, 11)
    c.drawString(safe_left, h - 12 * mm, "JustSkate.by")
    c.setFont(_CERT_FONT, 9)
    c.setFillColor(colors.HexColor("#AAAAAA"))
    c.drawString(safe_left, h - 18 * mm, "Подарочный сертификат")

    # ---- 3. Body: warm cream + subtle ice lines (skate trace feel) ----
    body_top = h - bar_h
    c.setFillColor(colors.HexColor(JS_CREAM_DARK))
    c.rect(0, 0, w, body_top, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#E5DDD2"))
    c.setLineWidth(0.2)
    c.saveState()
    c.rotate(-38)
    for i in range(10):
        x0 = -15 * mm + i * 32 * mm
        c.line(x0, -5 * mm, x0 + 35 * mm, body_top + 15 * mm)
    c.restoreState()

    # ---- 3b. Corner accents (frame the content) ----
    c.setStrokeColor(colors.HexColor(JS_AMBER))
    c.setLineWidth(0.6)
    corner = 8 * mm
    # top-left
    c.line(safe_left, body_top - 12 * mm, safe_left, body_top - 12 * mm - corner)
    c.line(safe_left, body_top - 12 * mm, safe_left + corner, body_top - 12 * mm)
    # bottom-left
    c.line(safe_left, 24 * mm, safe_left, 24 * mm + corner)
    c.line(safe_left, 24 * mm, safe_left + corner, 24 * mm)
    # top-right
    c.line(safe_right, body_top - 12 * mm, safe_right - corner, body_top - 12 * mm)
    c.line(safe_right, body_top - 12 * mm, safe_right, body_top - 12 * mm - corner)
    # bottom-right
    c.line(safe_right, 24 * mm, safe_right - corner, 24 * mm)
    c.line(safe_right, 24 * mm, safe_right, 24 * mm + corner)

    # ---- 4. Hero: recipient name (editorial, left-aligned) ----
    y = body_top - 18 * mm
    c.setFillColor(colors.HexColor(JS_GRAY))
    c.setFont(_CERT_FONT, 9)
    c.drawString(safe_left, y, "ДЛЯ")
    y -= 2 * mm
    recipient = (recipient_name or "").strip() or "Получателя"
    size = 28 if len(recipient) <= 18 else 22
    c.setFillColor(colors.HexColor(JS_BLACK))
    c.setFont(_CERT_FONT_HEAD, size)
    c.drawString(safe_left, y - (size * 0.35 * mm), recipient)
    y -= (size * 0.4 * mm) + 14 * mm

    # ---- 5. Details block (compact grid feel) ----
    c.setFont(_CERT_FONT_BOLD, 12)
    product_line = (product_name or "Сертификат").strip() or "Сертификат"
    c.drawString(safe_left, y, product_line)
    y -= 6 * mm
    c.setFont(_CERT_FONT, 11)
    c.setFillColor(colors.HexColor(JS_GRAY))
    c.drawString(safe_left, y, "Номинал  " + _fmt_amount(amount_cents))
    y -= 5 * mm
    trainer_line = (trainer_name or "Тренер").strip() or "Тренер"
    c.drawString(safe_left, y, "Тренер  " + trainer_line)
    y -= 14 * mm

    # ---- 6. Code: token strip (full-width amber bar, code centered) ----
    code_str = (code or "").strip() or "—"
    strip_h = 22 * mm
    c.setFillColor(colors.HexColor(JS_AMBER))
    c.rect(0, y - strip_h, w, strip_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor(JS_WHITE))
    c.setFont(_CERT_FONT, 8)
    c.drawCentredString(w / 2, y - 5 * mm, "КОД СЕРТИФИКАТА")
    c.setFont(_CERT_FONT_BOLD, 16)
    c.drawCentredString(w / 2, y - 14 * mm, code_str)
    y -= strip_h + 10 * mm

    # ---- 7. Dates + purchaser (single line) ----
    c.setFillColor(colors.HexColor(JS_BLACK))
    c.setFont(_CERT_FONT, 10)
    date_line = _fmt_date(issued_at) + "  ·  до " + _fmt_expires(expires_at)
    c.drawString(safe_left, y, date_line)
    if (purchased_by_name or "").strip():
        c.setFillColor(colors.HexColor(JS_GRAY))
        c.drawString(safe_left, y - 5 * mm, "Приобрёл(ла): " + (purchased_by_name or "").strip())
    y -= 16 * mm

    # ---- 8. Instruction: minimal, one paragraph ----
    c.setFillColor(colors.HexColor(JS_BLACK))
    c.setFont(_CERT_FONT_BOLD, 9)
    c.drawString(safe_left, y, "Как воспользоваться")
    y -= 4 * mm
    c.setFont(_CERT_FONT, 9)
    instr = (
        "Откройте бота или приложение тренера, выберите «У меня есть сертификат», "
        "введите код. После привязки можно записаться на занятие."
    )
    style = ParagraphStyle(
        "Instr",
        parent=getSampleStyleSheet()["Normal"],
        fontName=_CERT_FONT,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor(JS_GRAY),
    )
    p = Paragraph(instr, style)
    p.wrapOn(c, content_w, 20 * mm)
    p.drawOn(c, safe_left, y - 18 * mm)

    # ---- 9. Footer ----
    c.setFont(_CERT_FONT_BOLD, 10)
    c.setFillColor(colors.HexColor(JS_BLACK))
    c.drawCentredString(w / 2, 14 * mm, "JustSkate.by")
    c.setFont(_CERT_FONT, 8)
    c.setFillColor(colors.HexColor(JS_GRAY))
    c.drawCentredString(w / 2, 9 * mm, "Сохраните код")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()
