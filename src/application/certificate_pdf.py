"""
Gift certificate PDF:
- **Production:** A5 portrait: спокойный фон страницы + центральная белая карточка (бренд, сумма, получатель, шаги в Telegram, код).
- Optional: PyMuPDF template + overlay для экспериментов; статичный шаблон A4 — отдельно.
"""

from __future__ import annotations

import logging
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
import re
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
from src.shared.config import Settings

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
# Issued certificate (trainer flow): compact A5 portrait (~148×210 mm).
_CERT_ISSUE_PAGE = (148 * mm, 210 * mm)


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


def _bot_display_resolve(
    *,
    client_bot_display_name: Optional[str],
    activation_url: Optional[str],
) -> Optional[str]:
    """Prefer explicit @trainer_bot from API; otherwise parse ``t.me/<user>`` from activation_url."""
    s = (client_bot_display_name or "").strip()
    if s:
        return s if s.startswith("@") else f"@{s}"
    raw = (activation_url or "").strip()
    if not raw:
        return None
    m = re.search(r"(?:https?://)?t\.me/([^/?#]+)", raw, flags=re.I)
    if not m:
        return None
    uname = (m.group(1) or "").strip()
    if not uname:
        return None
    return uname if uname.startswith("@") else f"@{uname}"


def _certificate_card_instructions_markup(bot_display: Optional[str]) -> str:
    """Trust-first numbered steps matching Telegram mini-app navigation (Paragraph XML)."""
    intro = (
        "<font color='#64748b'><i>Всё оформлено официально: после активации баланс появится в вашем аккаунте. "
        "Сохраните эту карточку — пригодится, если понадобится восстановить код.</i></font>"
    )
    footer = (
        "<font color='#64748b'>Не получается активировать — напишите того, кто подарил сертификат, или в поддержку бота.</font>"
    )
    header = "<font color='#0f172a'><b>Как активировать подарочный сертификат</b></font>"
    if not bot_display:
        qr_line = "<b>Сначала откройте нашего Telegram-бота через QR ниже или по ссылке из письма.</b>"
        body = (
            f"{intro}<br/><br/>"
            f"{qr_line}<br/><br/>"
            "1. В чате с ботом нажмите <b>«Обзор»</b>.<br/>"
            "2. Откройте <b>«Абонементы / Сертификаты»</b>.<br/>"
            "3. Перейдите на вкладку <b>«Сертификаты»</b>.<br/>"
            "4. Введите <b>код из тёмной полосы</b> на этой карточке.<br/>"
            "5. После активации можно записаться к вашему тренеру в приложении.<br/><br/>"
            f"{footer}"
        )
        return f"{header}<br/><br/>{body}"

    bd = escape(bot_display)
    body = (
        f"{intro}<br/><br/>"
        "1. Откройте <b>Telegram</b>.<br/>"
        f"2. Найдите бота <b>{bd}</b> — отсканируйте <b>QR на карточке</b> или введите имя в поиске.<br/>"
        "3. У бота нажмите <b>«Обзор»</b>.<br/>"
        "4. Откройте <b>«Абонементы / Сертификаты»</b>.<br/>"
        "5. Перейдите на вкладку <b>«Сертификаты»</b>.<br/>"
        "6. Введите <b>код подарочного сертификата</b> из тёмной полосы ниже.<br/>"
        "7. После успешной активации можете записаться к вашему тренеру в каталоге.<br/><br/>"
        f"{footer}"
    )
    return f"{header}<br/><br/>{body}"


def _draw_accent_line(c: canvas.Canvas, x: float, y: float, length: float, thickness: float = 1.5) -> None:
    c.setStrokeColor(_hex(AMBER))
    c.setLineWidth(thickness)
    c.line(x, y, x + length, y)


_CARD_PAGE_BG = "#d8e0ed"
_CARD_SHADOW_FILL = "#b8c4d9"
_CARD_FACE = "#ffffff"
_CARD_BORDER = "#94a3b8"


def _pdf_card_sheet_background(canvas_obj: canvas.Canvas, pw: float, ph: float) -> None:
    canvas_obj.setFillColor(_hex(_CARD_PAGE_BG))
    canvas_obj.rect(0, 0, pw, ph, fill=1, stroke=0)


def _pdf_draw_white_card(
    canvas_obj: canvas.Canvas,
    *,
    x: float,
    y: float,
    cw: float,
    ch: float,
    r: float,
) -> None:
    """Drop shadow + white face + cool border."""
    canvas_obj.saveState()
    canvas_obj.setFillColor(_hex(_CARD_SHADOW_FILL))
    canvas_obj.roundRect(x - 0.7 * mm, y - 1.0 * mm, cw + 1.4 * mm, ch + 1.0 * mm, r + 0.6 * mm, fill=1, stroke=0)
    canvas_obj.restoreState()
    canvas_obj.setFillColor(_hex(_CARD_FACE))
    canvas_obj.setStrokeColor(_hex(_CARD_BORDER))
    canvas_obj.setLineWidth(0.7)
    canvas_obj.roundRect(x, y, cw, ch, r, fill=1, stroke=1)


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


def _qr_png_bytes(
    payload: str, *, box_size: int = 3, border: int = 1
) -> Optional[bytes]:
    """PNG bytes for QR or None if qrcode/PIL missing."""
    if not (payload or "").strip():
        return None
    try:
        import qrcode
        from PIL import Image
    except ImportError:
        return None
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
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
    client_bot_display_name: Optional[str] = None,
) -> bytes:
    """Фон страницы + центральная карточка: бренд из настроек, сумма, получатель, шаги Telegram, код."""
    _register_fonts()
    w, h = _CERT_ISSUE_PAGE
    buf = BytesIO()
    cnv = canvas.Canvas(buf, pagesize=(w, h))
    cfg = Settings()
    brand_display = (cfg.certificate_pdf_brand_display_name or "ICE STUDIO").strip()
    tagline_txt = (cfg.certificate_pdf_brand_tagline_ru or "").strip()
    bot_display = _bot_display_resolve(
        client_bot_display_name=client_bot_display_name,
        activation_url=activation_url,
    )
    qr_img = (
        _qr_png_bytes(str(activation_url).strip(), box_size=3, border=1)
        if (activation_url or "").strip()
        else None
    )

    qr_side = 18.5 * mm
    qr_pad = 2 * mm
    qr_shell = qr_side + 2 * qr_pad
    ink = "#0f172a"
    muted = "#64748b"
    rule_tc = "#cbd5e1"
    stripe_bg = "#0f172a"
    stripe_hi = "#3b82f6"

    _pdf_card_sheet_background(cnv, w, h)

    mx, my = 10 * mm, 10 * mm
    cw, ch = w - 2 * mx, h - 2 * my
    cr = 5 * mm
    _pdf_draw_white_card(cnv, x=mx, y=my, cw=cw, ch=ch, r=cr)

    pad_inner = 8 * mm
    ix = mx + pad_inner
    iy_top = my + ch - pad_inner
    iw = cw - 2 * pad_inner
    qr_reserve = (qr_shell + 5 * mm) if qr_img else 4 * mm
    col_w = max(52 * mm, iw - qr_reserve)

    stripe_left = mx + 9 * mm
    stripe_w_inner = cw - 18 * mm
    stripe_h = 29 * mm
    stripe_bottom = my + 11 * mm
    stripe_top = stripe_bottom + stripe_h

    cnv.saveState()
    cnv.setFillColor(_hex(stripe_bg))
    cnv.roundRect(stripe_left, stripe_bottom, stripe_w_inner, stripe_h, 4 * mm, fill=1, stroke=0)
    cnv.restoreState()

    p_code_lbl_st = ParagraphStyle(
        "codelb",
        fontName=_FONT_SEMI,
        fontSize=7.05,
        alignment=1,
        textColor=colors.HexColor("#94a3b8"),
        leading=8.6,
    )
    pclr = Paragraph(escape("код активации в Telegram"), p_code_lbl_st)
    _, hclr = pclr.wrap(stripe_w_inner, 16 * mm)
    pclr.drawOn(cnv, stripe_left, stripe_bottom + stripe_h - hclr - 6 * mm)

    code_plain = ((code or "").strip() or "—").replace("\n", " ")
    cnv.setFillColor(colors.HexColor("#f8fafc"))
    cnv.setFont("Courier-Bold", 12.2)
    cnv.drawCentredString(mx + cw / 2, stripe_bottom + 8 * mm, code_plain)

    cnv.setStrokeColor(_hex(stripe_hi))
    cnv.setLineWidth(0.85)
    cnv.line(
        stripe_left + 14 * mm,
        stripe_top - 1 * mm,
        stripe_left + stripe_w_inner - 14 * mm,
        stripe_top - 1 * mm,
    )

    if qr_img:
        ql = ix + iw - qr_shell
        qb = iy_top - 6 * mm - qr_shell
        cnv.saveState()
        cnv.setFillColor(colors.white)
        cnv.setStrokeColor(_hex(rule_tc))
        cnv.setLineWidth(0.45)
        cnv.roundRect(ql, qb, qr_shell, qr_shell, 2.8 * mm, fill=1, stroke=1)
        cnv.restoreState()
        cnv.drawImage(
            ImageReader(BytesIO(qr_img)),
            ql + qr_pad,
            qb + qr_pad,
            width=qr_side,
            height=qr_side,
            mask="auto",
        )

    stack = stripe_top + 8 * mm
    ins_budget = iy_top - 15 * mm - stack
    if ins_budget < 28 * mm:
        ins_budget = 28 * mm
    ins_fs = 6.75 if ins_budget >= 70 * mm else 6.38
    ins_lead = 8.45 if ins_budget >= 70 * mm else 7.92
    p_ins_st = ParagraphStyle(
        "ins",
        fontName=_FONT,
        fontSize=ins_fs,
        leading=ins_lead,
        textColor=_hex("#334155"),
    )
    p_ins = Paragraph(_certificate_card_instructions_markup(bot_display), p_ins_st)
    _, hi_meas = p_ins.wrap(iw - 3 * mm, ins_budget + 40 * mm)
    hi_use = min(hi_meas, ins_budget)
    if hi_meas > ins_budget:
        p_ins_st.fontSize = 6.35
        p_ins_st.leading = 7.88
        p_ins = Paragraph(_certificate_card_instructions_markup(bot_display), p_ins_st)
        _, hi_meas = p_ins.wrap(iw - 3 * mm, ins_budget)
        hi_use = min(hi_meas, ins_budget)
    _, hf_ins = p_ins.wrap(iw - 3 * mm, hi_use)
    p_ins.drawOn(cnv, ix + 1 * mm, stack)
    stack += hf_ins + 10 * mm

    meta_txt = "<b>%s</b>:&nbsp;%s<br/><b>%s</b>:&nbsp;%s" % (
        escape("Тренер"),
        escape((trainer_name or "").strip() or "—"),
        escape("Действителен до"),
        escape(_format_date(expires_at) if expires_at else "бессрочно"),
    )
    pst_meta = ParagraphStyle(
        "meta",
        fontName=_FONT,
        fontSize=7.75,
        leading=10.6,
        textColor=_hex(muted),
    )
    p_meta = Paragraph(meta_txt, pst_meta)
    _, hm = p_meta.wrap(col_w, 42 * mm)
    p_meta.drawOn(cnv, ix, stack)
    stack += hm + 11 * mm

    pst_prod = ParagraphStyle(
        "prd",
        fontName=_FONT,
        fontSize=8.5,
        leading=11,
        textColor=_hex("#475569"),
    )
    p_prod = Paragraph(escape((product_name or "Сертификат на услуги вашего тренера").strip()), pst_prod)
    _, hp = p_prod.wrap(col_w, 44 * mm)
    p_prod.drawOn(cnv, ix, stack)
    stack += hp + 10 * mm

    amt_plain = _format_amount(amount_cents)
    if amt_plain == "Любая сумма":
        pst_amt = ParagraphStyle("amtlo", fontName=_FONT_BOLD, fontSize=12.8, leading=15, textColor=_hex(ink))
        p_amt = Paragraph("<b>%s</b>" % escape("Номинал согласуется при выдаче — любая сумма"), pst_amt)
    else:
        pst_amt = ParagraphStyle("amtfx", fontName=_FONT, fontSize=11, leading=24, textColor=_hex(ink))
        amt_sz = "22" if len(amt_plain) <= 7 else ("18" if len(amt_plain) <= 11 else "16")
        p_amt = Paragraph(
            '<font face="%s" size="%s"><b>%s</b></font> <font face="%s" color="#64748b" size="11"><b>BYN</b></font>'
            % (_FONT_BOLD, amt_sz, escape(amt_plain), _FONT_SEMI),
            pst_amt,
        )
    _, ha = p_amt.wrap(col_w, 32 * mm)
    p_amt.drawOn(cnv, ix, stack)
    stack += ha + 9 * mm

    recipient_plain = ((recipient_name or "").strip() or "Получатель").replace("\n", " ")
    r_sz = 15 if len(recipient_plain) <= 28 else (13 if len(recipient_plain) <= 42 else 11.8)
    pst_rec = ParagraphStyle(
        "rec",
        fontName=_FONT_BOLD,
        fontSize=r_sz,
        leading=r_sz + 3,
        textColor=_hex(ink),
    )
    p_rec = Paragraph(escape(recipient_plain), pst_rec)
    _, hr = p_rec.wrap(col_w, 42 * mm)
    p_rec.drawOn(cnv, ix, stack)
    stack += hr + 7 * mm

    pst_lab = ParagraphStyle(
        "lab",
        fontName=_FONT_SEMI,
        fontSize=6.95,
        leading=9,
        textColor=_hex(muted),
    )
    p_lab = Paragraph(escape("получатель"), pst_lab)
    _, hl = p_lab.wrap(col_w, 14 * mm)
    p_lab.drawOn(cnv, ix, stack)
    stack += hl + 9 * mm

    pst_cap = ParagraphStyle(
        "cap",
        fontName=_FONT_SEMI,
        fontSize=8.2,
        leading=10.5,
        textColor=_hex("#334155"),
    )
    p_cap = Paragraph(escape("Подарочный сертификат"), pst_cap)
    _, hc = p_cap.wrap(col_w, 22 * mm)
    p_cap.drawOn(cnv, ix, stack)
    stack += hc + 12 * mm

    cnv.setStrokeColor(_hex(rule_tc))
    cnv.setLineWidth(0.55)
    cnv.line(ix, stack, ix + iw, stack)
    stack += 13 * mm

    pst_br = ParagraphStyle(
        "brd",
        fontName=_FONT_BOLD,
        fontSize=17.5,
        leading=20,
        textColor=_hex(ink),
    )
    p_brand = Paragraph(escape(brand_display), pst_br)
    _, hb = p_brand.wrap(col_w, 40 * mm)
    p_brand.drawOn(cnv, ix, stack)
    stack += hb + 5 * mm

    pst_tag = ParagraphStyle(
        "tag",
        fontName=_FONT,
        fontSize=7.82,
        leading=11.1,
        textColor=_hex(muted),
    )
    p_tag = Paragraph(escape(tagline_txt), pst_tag)
    _, ht = p_tag.wrap(col_w, 52 * mm)
    p_tag.drawOn(cnv, ix, stack)
    stack += ht

    overshoot = (stack + 6 * mm) - iy_top
    if overshoot > 0.8 * mm and logger.isEnabledFor(logging.WARNING):
        logger.warning("certificate_pdf: card overflow by %.2f pt — shorten CERTIFICATE_* env tagline", overshoot)

    foot = "%s · выдан %s" % (brand_display, _format_date(issued_at))
    if (purchased_by_name or "").strip():
        foot += " · %s" % purchased_by_name.strip()
    cnv.setFillColor(_hex(muted))
    cnv.setFont(_FONT, 6.6)
    cnv.drawCentredString(w / 2, max(4.8 * mm, my - 4 * mm), foot)

    cnv.showPage()
    cnv.save()
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
    client_bot_display_name: Optional[str] = None,
) -> bytes:
    """
    A5 portrait: фон страницы + центральная карточка. Брендинг через Settings (certificate_pdf_brand_*).
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
        client_bot_display_name=client_bot_display_name,
    )
