"""Плакат компании для чата и превью ссылки. Квадрат 1080.

Площадка — светлый лёд на ночном фоне: борта, синие и красная, точки вбрасывания.
Имена стоят на льду, пустые места — пунктир. Тип сеанса отдельной плашкой,
чтобы в чате было видно: массовое катание, ОХМ или следующий формат.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from src.application.ice_city_day_og import _fit, _font
from src.application.ice_company.copy import Snap, clock, kind_label, weekday_nom

CARD_SIZE = (1080, 1080)
_BG = (14, 28, 36)
_INK = (244, 247, 248)
_MUTED = (155, 176, 188)
_ACCENT = (127, 215, 216)
_BOARD = (18, 42, 52)
_ICE = (214, 236, 242)
_LINE_BLUE = (46, 108, 184)
_LINE_RED = (196, 54, 54)
_PLAYER = (14, 28, 36)

# Доли льда, в стороне от синих, красной и центрального круга.
_SPOTS: dict[int, tuple[tuple[float, float], ...]] = {
    1: ((0.22, 0.50),),
    2: ((0.20, 0.50), (0.80, 0.50)),
    3: ((0.18, 0.32), (0.82, 0.32), (0.38, 0.76)),
    4: ((0.18, 0.30), (0.82, 0.30), (0.18, 0.74), (0.82, 0.74)),
    5: ((0.18, 0.28), (0.82, 0.28), (0.18, 0.74), (0.82, 0.74), (0.40, 0.78)),
    6: ((0.18, 0.26), (0.40, 0.22), (0.60, 0.22), (0.82, 0.26), (0.30, 0.78), (0.70, 0.78)),
}
_HOLE = (110, 140, 152)
_ON_ICE = 6


def card_photo_url(base: str, code: str, digest: str) -> str | None:
    root = (base or "").strip().rstrip("/")
    if not root.startswith("https://"):
        return None
    return f"{root}/k/{code}/card.png?v={digest[:16]}"


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int, lines: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    rows: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_w:
            current = trial
            continue
        if current:
            rows.append(current)
        current = word
        if len(rows) == lines - 1:
            break
    if len(rows) < lines and current:
        rows.append(_fit(draw, current, font, max_w))
    return rows[:lines]


def render_company_card(snap: Snap) -> bytes:
    image = Image.new("RGB", CARD_SIZE, _BG)
    draw = ImageDraw.Draw(image)
    kicker_font = _font("Inter-SemiBold.ttf", 32)
    time_font = _font("Inter-Bold.ttf", 96)
    place_font = _font("Inter-Regular.ttf", 32)
    chip_font = _font("Inter-SemiBold.ttf", 28)
    name_font = _font("Inter-SemiBold.ttf", 26)
    number_font = _font("Inter-Bold.ttf", 92)
    word_font = _font("Inter-SemiBold.ttf", 36)

    pad = 64
    draw.text((pad, 40), weekday_nom(snap.starts_at).upper(), font=kicker_font, fill=_ACCENT)
    _draw_kind(draw, kind_label(snap.kind), chip_font, pad)
    draw.text((pad, 84), clock(snap.starts_at), font=time_font, fill=_INK)
    for index, row in enumerate(_wrap(draw, snap.venue, place_font, 640, 1)):
        draw.text((pad, 192), row, font=place_font, fill=_MUTED)

    rink = (pad, 250, CARD_SIZE[0] - pad, 860)
    _draw_rink(image, rink)
    _draw_skaters(image, snap, name_font, rink)

    missing = snap.min_people - len(snap.going_names)
    closed = snap.cancelled or snap.expired or snap.status in ("cancelled", "expired")
    if closed:
        headline, word, color = ("Не собрались" if snap.expired or snap.status == "expired" else "Снято", "", _MUTED)
        number_font = _font("Inter-Bold.ttf", 64)
    elif snap.status == "confirmed" or missing <= 0:
        headline, word, color = ("Едем", "", _ACCENT)
        number_font = _font("Inter-Bold.ttf", 72)
    else:
        headline, word, color = (str(missing), "ещё", _INK)
    draw.text((pad, 900), headline, font=number_font, fill=color)
    if word:
        gap = int(draw.textlength(headline, font=number_font)) + 18
        draw.text((pad + gap, 948), word, font=word_font, fill=_ACCENT)
    extra = len(snap.going_names) - _ON_ICE
    if extra > 0 and not closed:
        more = f"и ещё {extra}"
        more_w = int(draw.textlength(more, font=place_font))
        draw.text((CARD_SIZE[0] - pad - more_w, 940), more, font=place_font, fill=_MUTED)

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _draw_kind(draw: ImageDraw.ImageDraw, label: str, font: ImageFont.FreeTypeFont, pad: int) -> None:
    if not label:
        return
    text_w = int(draw.textlength(label, font=font))
    height = 56
    width = text_w + 40
    right = CARD_SIZE[0] - pad
    box = (right - width, 36, right, 36 + height)
    draw.rounded_rectangle(box, radius=28, outline=_ACCENT, width=3)
    draw.text((box[0] + 20, 48), label, font=font, fill=_INK)


def _draw_rink(image: Image.Image, rink: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = rink
    width, height = right - left, bottom - top
    sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=86, fill=255)
    pen = ImageDraw.Draw(sheet)
    pen.rounded_rectangle((0, 0, width - 1, height - 1), radius=86, fill=_BOARD)
    inset = 18
    pen.rounded_rectangle((inset, inset, width - 1 - inset, height - 1 - inset), radius=70, fill=_ICE)

    ice_left, ice_top = inset + 8, inset + 8
    ice_right, ice_bottom = width - inset - 8, height - inset - 8
    ice_w = ice_right - ice_left
    ice_h = ice_bottom - ice_top

    def x_at(fraction: float) -> int:
        return int(ice_left + ice_w * fraction)

    def y_at(fraction: float) -> int:
        return int(ice_top + ice_h * fraction)

    for fraction in (1 / 3, 2 / 3):
        x = x_at(fraction)
        pen.line((x, ice_top, x, ice_bottom), fill=_LINE_BLUE, width=6)
    pen.line((x_at(0.5), ice_top, x_at(0.5), ice_bottom), fill=_LINE_RED, width=6)
    for fraction in (0.08, 0.92):
        x = x_at(fraction)
        pen.line((x, ice_top, x, ice_bottom), fill=_LINE_RED, width=3)

    radius = 78
    pen.ellipse(
        (x_at(0.5) - radius, y_at(0.5) - radius, x_at(0.5) + radius, y_at(0.5) + radius),
        outline=_LINE_RED,
        width=4,
    )
    pen.ellipse((x_at(0.5) - 7, y_at(0.5) - 7, x_at(0.5) + 7, y_at(0.5) + 7), fill=_LINE_RED)

    for fraction, start in ((0.08, 270), (0.92, 90)):
        radius = 36
        box = (x_at(fraction) - radius, y_at(0.5) - radius, x_at(fraction) + radius, y_at(0.5) + radius)
        pen.arc(box, start, start + 180, fill=_LINE_RED, width=3)
        goal_w, goal_h = 16, 54
        gx = x_at(fraction) - goal_w if fraction < 0.5 else x_at(fraction)
        gy = y_at(0.5) - goal_h // 2
        pen.rectangle((gx, gy, gx + goal_w, gy + goal_h), outline=_LINE_RED, width=3)

    image.paste(sheet, (left, top), mask)


def _draw_skaters(image: Image.Image, snap: Snap, font: ImageFont.FreeTypeFont, rink: tuple[int, int, int, int]) -> None:
    names = list(snap.going_names)
    holes = max(0, snap.min_people - len(names))
    count = min(_ON_ICE, max(len(names), min(len(names) + holes, _ON_ICE), 1))
    if not names and holes <= 0:
        count = 0
    shown = names[:count]
    empty = count - len(shown)
    spots = _SPOTS[max(count, 1)][:count]
    left, top, right, bottom = rink
    inset = 26
    ice_left, ice_top = left + inset, top + inset
    ice_w, ice_h = (right - left) - inset * 2, (bottom - top) - inset * 2
    overlay = ImageDraw.Draw(image)
    for (fx, fy), label in zip(spots, shown + [""] * empty, strict=False):
        _skater(overlay, ice_left + ice_w * fx, ice_top + ice_h * fy, label, font)


def _skater(draw: ImageDraw.ImageDraw, cx: float, cy: float, label: str, font: ImageFont.FreeTypeFont) -> None:
    radius = 20
    if not label:
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=_HOLE, width=3)
        plate = (cx - 46, cy + radius + 8, cx + 46, cy + radius + 44)
        draw.rounded_rectangle(plate, radius=18, outline=_HOLE, width=3)
        return
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=_PLAYER)
    initial = label.strip()[:1].upper()
    initial_font = _font("Inter-Bold.ttf", 22)
    initial_w = draw.textlength(initial, font=initial_font)
    draw.text((cx - initial_w / 2, cy - 14), initial, font=initial_font, fill=_INK)
    name = _fit(draw, label, font, 168)
    text_w = draw.textlength(name, font=font)
    box_w = text_w + 28
    box = (cx - box_w / 2, cy + radius + 8, cx + box_w / 2, cy + radius + 46)
    draw.rounded_rectangle(box, radius=18, fill=_PLAYER)
    draw.text((box[0] + 14, box[1] + 7), name, font=font, fill=_INK)


