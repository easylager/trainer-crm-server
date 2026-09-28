"""
HTML certificate (single source with ``static/templates/certificate_issue.html``) → PDF via PyMuPDF Story.
Matches UX copy from ``docs/certificate-html-constructor.html`` preview.
"""

from __future__ import annotations

import base64
import logging
from datetime import date
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Optional

import fitz

logger = logging.getLogger(__name__)


def _root() -> Path:
    """Repo root (directory that contains ``src/`` and ``static/``)."""
    return Path(__file__).resolve().parent.parent.parent


def _esc(s: object) -> str:
    return escape(str(s) if s is not None else "")


def _nl2br_html(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return ""
    return _esc(t).replace("\n", "<br/>")


def _format_date(d: Optional[date]) -> str:
    if not d:
        return "—"
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def _format_amount(cents: int) -> str:
    if cents <= 0:
        return "Любая сумма"
    v = cents / 100
    return f"{int(v)}" if v == int(v) else f"{v:.2f}"


def _qr_png_bytes(payload: str, *, box_size: int = 3, border: int = 1) -> Optional[bytes]:
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


def _qr_png_pdf_safe(payload: str, *, px: int = 72) -> Optional[bytes]:
    """
    MuPDF Story treats embedded PNG intrinsic pixels as layout units unless width/height are set;
    resizing keeps the bitmap small so it cannot blow up across multiple pages.
    """
    raw = _qr_png_bytes(payload, box_size=2, border=1)
    if not raw:
        return None
    try:
        from PIL import Image

        im = Image.open(BytesIO(raw)).convert("RGB")
        if im.width != px or im.height != px:
            try:
                resample = Image.Resampling.NEAREST  # Pillow >=9
            except AttributeError:
                resample = Image.NEAREST
            im = im.resize((px, px), resample)
        out = BytesIO()
        im.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        return raw


def _normalize_bot(bot_raw: str) -> str:
    b = (bot_raw or "").strip()
    if not b:
        return ""
    if not b.startswith("@"):
        b = "@" + b.lstrip("@")
    return b


def _instructions_block_html(bot_display: Optional[str], *, has_qr: bool = True) -> str:
    """
    Короткая инструкция вместо прежних десяти шагов.

    Раньше здесь жили две нумерованные простыни (6 шагов активации + 4 шага использования),
    блок «Возможности сервиса» и два абзаца мелким курсивом. Половина текста повторяла
    подпись под QR, четыре шага из шести начинались со слов «Если зашли без QR», а страница
    при этом переполнялась — сертификат печатался без кода. Осталось три шага активации и
    три факта о том, как сертификат тратится: всё, что получателю нужно знать в руках.

    Формулировки проверены по коду, а не по памяти:
    * QR (``/start cert_<CODE>``) активирует сертификат сам и сразу предлагает записаться —
      ``client_handlers._parse_cert_start``;
    * ручной путь идёт через кнопку бота «Абонементы и сертификаты» (так она и называется —
      ``messages.CLIENT_BUTTON_MY_PASSES_AND_CERTIFICATES``), а не через «Обзор»;
    * баланс списывается, когда занятие отмечено проведённым —
      ``booking_use_cases.redeem_certificate_balance_for_booking``;
    * повторный ввод кода идемпотентен для того же аккаунта, но чужому он уже не откроется —
      ``certificate_use_cases.activate_certificate_by_code``.
    """
    bd = _normalize_bot(bot_display or "")
    open_bot = (
        f"откройте в Telegram бота {bd}" if bd else "откройте бота по ссылке из письма"
    )

    # Без QR первый шаг про сканирование — ложь на бумаге: ссылки на карточке просто нет.
    steps_act: list[str] = []
    if has_qr:
        steps_act.append(
            "Отсканируйте QR выше и нажмите «Запустить» — сертификат активируется сразу."
        )
    manual = (
        open_bot + ", зайдите в «Абонементы и сертификаты» и введите код — "
        "без пробелов, точно как напечатано."
    )
    steps_act.append(
        "Без QR: " + manual if has_qr else manual[:1].upper() + manual[1:]
    )
    steps_act.append("Бот подтвердит активацию и покажет тренера — можно выбирать время.")

    facts_use = [
        "Записывайтесь к тренеру в мини-приложении: время, отмены и правила — там же.",
        "Сумма списывается после проведённого занятия. Остаток всегда виден в «Абонементах и сертификатах».",
        "Сертификат закрепляется за вашим аккаунтом Telegram — код нужен один раз.",
    ]

    ol_act = "".join(f"<li>{_esc(t)}</li>" for t in steps_act)
    ul_use = "".join(f"<li>{_esc(t)}</li>" for t in facts_use)

    fineprint = _esc(
        "Код — как деньги: он сработает у того, кто введёт его первым. "
        "Не активируется — напишите тренеру, который выдал сертификат."
    )

    return (
        '<div class="instructions">'
        "<h3>Как активировать</h3>"
        f"<ol>{ol_act}</ol>"
        "<h3>Как пользоваться</h3>"
        f"<ul>{ul_use}</ul>"
        f'<p class="fineprint">{fineprint}</p>'
        "</div>"
    )


def _amount_row_html(amount_cents: int) -> str:
    plain = _format_amount(amount_cents)
    if plain == "Любая сумма":
        return f'<div class="amount-row"><span>{_esc(plain)}</span></div>'
    return (
        f'<div class="amount-row"><span>{_esc(plain)}</span>'
        f'<span class="curr">&#160;BYN</span></div>'
    )


def _meta_html(trainer_name: str, expires_at: Optional[date]) -> str:
    ex = _format_date(expires_at) if expires_at else "бессрочно"
    return f"<b>Тренер</b>: {_esc((trainer_name or '').strip() or '—')}<br/><b>Действителен до</b>: {_esc(ex)}"


def _sheet_foot_line(
    *,
    brand: str,
    issued_at: Optional[date],
    purchased_by_name: Optional[str],
    powered_by: Optional[str] = None,
) -> str:
    foot = f"{(brand or '').strip() or 'GLIDE'} · выдан {_format_date(issued_at)}"
    if (purchased_by_name or "").strip():
        foot += f" · {(purchased_by_name or '').strip()}"
    platform = (powered_by or "").strip()
    if platform and platform.lower() not in (brand or "").strip().lower():
        foot += f" · powered by {platform}"
    return _esc(foot)


def build_certificate_issue_html(
    *,
    brand_display: str,
    brand_tagline: str,
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
    brand_powered_by: Optional[str] = None,
) -> str:
    """
    Fill ``static/templates/certificate_issue.html`` with escaped dynamic fields.
    Bot display for steps: explicit @bot else parsed from activation_url (t.me/…) inside caller if needed.
    """
    p = _root() / "static/templates/certificate_issue.html"
    tpl = p.read_text(encoding="utf-8")

    bot_for_steps = _normalize_bot(client_bot_display_name or "")
    if not bot_for_steps and (activation_url or "").strip():
        import re

        m = re.search(r"(?:https?://)?t\.me/([^/?#]+)", (activation_url or "").strip(), flags=re.I)
        if m:
            bot_for_steps = _normalize_bot(m.group(1) or "")

    qr_png = _qr_png_pdf_safe((activation_url or "").strip(), px=80)
    if qr_png:
        b64 = base64.b64encode(qr_png).decode("ascii")
        # Explicit HTML dimensions: Story uses intrinsic image size if these are missing (full-page QR spam).
        qr_inner = (
            f'<img alt="QR" width="80" height="80" '
            f'style="width:80px;height:80px;max-width:80px;max-height:80px;" '
            f'src="data:image/png;base64,{b64}" />'
            '<div class="qr-caption"><b>Наведите камеру</b> — '
            "бот активирует сертификат сам.</div>"
        )
    else:
        qr_inner = ""

    html = tpl
    html = html.replace("__BRAND__", _esc((brand_display or "").strip() or "GLIDE"))
    html = html.replace("__TAGLINE_HTML__", _nl2br_html(brand_tagline))
    html = html.replace("__RECIPIENT__", _esc((recipient_name or "").strip() or "Получатель"))
    html = html.replace("__AMOUNT_ROW__", _amount_row_html(amount_cents))
    html = html.replace("__PRODUCT__", _esc((product_name or "").strip()))
    html = html.replace("__META__", _meta_html(trainer_name, expires_at))
    html = html.replace(
        "__INSTRUCTIONS_BLOCK__",
        _instructions_block_html(bot_for_steps or None, has_qr=bool(qr_png)),
    )
    html = html.replace("__QR_INNER__", qr_inner)
    html = html.replace("__CODE__", _esc(((code or "").strip() or "—").replace("\n", " ")))
    html = html.replace(
        "__SHEET_FOOT__",
        _sheet_foot_line(
            brand=(brand_display or "").strip() or "GLIDE",
            issued_at=issued_at,
            purchased_by_name=purchased_by_name,
            powered_by=brand_powered_by,
        ),
    )
    return html


def certificate_html_to_pdf_bytes(html: str) -> bytes:
    """Render HTML/CSS to a **single** A5 PDF page (PyMuPDF Story)."""
    static_root = _root() / "static"
    archive = fitz.Archive(str(static_root))
    story = fitz.Story(html=html, archive=archive)
    buf = BytesIO()
    writer = fitz.DocumentWriter(buf)
    mediabox = fitz.paper_rect("a5")
    inset_pt = 9
    where = mediabox + (inset_pt, inset_pt, -inset_pt, -inset_pt)
    device = writer.begin_page(mediabox)
    more, _ = story.place(where)
    story.draw(device)
    writer.end_page()
    writer.close()
    if more:
        logger.warning(
            "Certificate Story still had overflow after one page — check CSS or copy length.",
        )
    return buf.getvalue()
