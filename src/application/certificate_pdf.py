"""
Premium gift certificate PDF — editorial design by senior graphic designer.
Strong visual hierarchy, memorable layout, brand consistency.
Cyrillic via Inter (static/fonts).
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

# --- Brand palette ---
CREAM = "#fffbec"
CREAM_RICH = "#f8f1e4"
TEXT_DARK = "#1a1a1a"
TEXT_WARM = "#4a3728"
TEXT_MUTED = "#8b7355"
AMBER = "#f5a623"
AMBER_BRIGHT = "#ffb84d"
AMBER_DEEP = "#d4941a"
CHARCOAL = "#2c2c2e"

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONT_SEMI = "Helvetica-Bold"
_REGISTERED = False


def _root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


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
    """Draw signature amber accent line."""
    c.setStrokeColor(_hex(AMBER))
    c.setLineWidth(thickness)
    c.line(x, y, x + length, y)


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
    _register_fonts()
    buf = BytesIO()
    w, h = A4
    c = canvas.Canvas(buf, pagesize=A4)
    
    # Grid system
    margin = 24 * mm
    col_w = (w - 2 * margin) / 12
    
    # ===== BACKGROUND =====
    c.setFillColor(_hex(CREAM))
    c.rect(0, 0, w, h, fill=1, stroke=0)
    
    # Subtle texture: diagonal lines
    c.setStrokeColor(_hex(CREAM_RICH))
    c.setLineWidth(0.3)
    step = int(8 * mm)
    for i in range(0, int(w + h), step):
        c.line(i - h, 0, i, h)
    
    # ===== HEADER ZONE =====
    y = h - 28 * mm
    
    # Brand lockup
    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_BOLD, 22)
    c.drawString(margin, y, "JustSkate")
    
    # Amber dot after brand
    c.setFillColor(_hex(AMBER))
    c.circle(margin + 76 * mm, y + 6 * mm, 2.5 * mm, fill=1, stroke=0)
    
    # Certificate type — small caps
    c.setFillColor(_hex(TEXT_MUTED))
    c.setFont(_FONT_SEMI, 8)
    c.drawString(margin, y - 8 * mm, "ПОДАРОЧНЫЙ СЕРТИФИКАТ")
    
    # Accent line under header
    _draw_accent_line(c, margin, y - 14 * mm, col_w * 4, 2)
    
    y -= 32 * mm
    
    # ===== HERO SECTION =====
    # Recipient label — aligned with name
    name_x = margin
    c.setFillColor(_hex(TEXT_WARM))
    c.setFont(_FONT_SEMI, 9)
    c.drawString(name_x, y, "ДЛЯ")
    y -= 12 * mm
    
    # Recipient name — hero typography
    recipient = (recipient_name or "").strip() or "Получателя"
    name_size = 48 if len(recipient) <= 10 else (36 if len(recipient) <= 18 else 28)
    
    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_BOLD, name_size)
    
    # Multi-line if needed
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
    
    # ===== CONTENT GRID =====
    # Left column: Product & Details
    left_x = margin
    left_w = col_w * 7
    
    # Right column: Amount badge
    right_x = margin + col_w * 8
    right_w = col_w * 4
    
    # Product name
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
    
    # Amount badge (right column)
    badge_h = 32 * mm
    badge_y = y - badge_h + prod_h
    
    # Badge background
    c.setFillColor(_hex(AMBER))
    c.roundRect(right_x, badge_y, right_w, badge_h, 4 * mm, fill=1, stroke=0)
    
    # Badge highlight
    c.setFillColor(_hex(AMBER_BRIGHT))
    c.roundRect(right_x, badge_y + badge_h - 8 * mm, right_w, 8 * mm, 4 * mm, fill=1, stroke=0)
    
    # Amount text
    amount_str = _format_amount(amount_cents)
    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_BOLD, 24)
    c.drawCentredString(right_x + right_w / 2, badge_y + 14 * mm, amount_str)
    
    c.setFont(_FONT_SEMI, 10)
    c.drawCentredString(right_x + right_w / 2, badge_y + 6 * mm, "BYN")
    
    y -= max(prod_h + 16 * mm, badge_h + 8 * mm)
    
    # Details grid
    detail_y = y
    
    # Trainer
    c.setFillColor(_hex(TEXT_MUTED))
    c.setFont(_FONT, 10)
    c.drawString(left_x, detail_y, "Тренер")
    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_SEMI, 10)
    c.drawString(left_x + 18 * mm, detail_y, (trainer_name or "").strip() or "—")
    detail_y -= 8 * mm
    
    # Validity
    c.setFillColor(_hex(TEXT_MUTED))
    c.setFont(_FONT, 10)
    c.drawString(left_x, detail_y, "До")
    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_SEMI, 10)
    expires_str = _format_date(expires_at) if expires_at else "бессрочно"
    c.drawString(left_x + 18 * mm, detail_y, expires_str)
    
    y = detail_y - 24 * mm
    
    # ===== CODE SECTION =====
    # Code background — full width, compact
    code_h = 28 * mm
    code_y = y - code_h
    
    c.setFillColor(_hex(CHARCOAL))
    c.rect(0, code_y, w, code_h, fill=1, stroke=0)
    
    # Amber accent strip
    c.setFillColor(_hex(AMBER))
    c.rect(0, code_y + code_h - 3 * mm, w, 3 * mm, fill=1, stroke=0)
    
    # Code label
    c.setFillColor(_hex("#9a9a9e"))
    c.setFont(_FONT, 8)
    c.drawCentredString(w / 2, code_y + code_h - 10 * mm, "КОД АКТИВАЦИИ")
    
    # Code value — monospace feel
    code_str = (code or "").strip() or "—"
    c.setFillColor(colors.white)
    c.setFont(_FONT_BOLD, 28)
    
    # Letter spacing for code
    code_w = c.stringWidth(code_str, _FONT_BOLD, 28)
    start_x = (w - code_w) / 2
    c.drawString(start_x, code_y + 8 * mm, code_str)
    
    y = code_y - 16 * mm
    
    # ===== FOOTER =====
    # Issue info
    c.setFillColor(_hex(TEXT_MUTED))
    c.setFont(_FONT, 8)
    issue_str = f"Выдан {_format_date(issued_at)}"
    if (purchased_by_name or "").strip():
        issue_str += f" • {purchased_by_name.strip()}"
    c.drawString(margin, y, issue_str)
    
    # Instructions — compact
    y -= 8 * mm
    c.drawString(margin, y, "Откройте @JustSkateBot, введите код, запишитесь на занятие")
    
    # Brand signature
    c.setFillColor(_hex(TEXT_DARK))
    c.setFont(_FONT_BOLD, 9)
    c.drawRightString(w - margin, 12 * mm, "JustSkate.by")
    
    # Bottom accent
    c.setFillColor(_hex(AMBER))
    c.rect(0, 0, w, 2 * mm, fill=1, stroke=0)
    
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()