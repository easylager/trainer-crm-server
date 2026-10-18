"""Плакат компании для чата и превью ссылки. Квадрат 1080.

Площадка — светлый лёд на ночном фоне: борта, синие и красная, точки вбрасывания.
Имена стоят на льду, пустые места — пунктир. Тип сеанса отдельной плашкой,
чтобы в чате было видно: массовое катание, ОХМ или следующий формат.
"""

from __future__ import annotations

import io
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from src.application.ice_city_day_og import _fit, _font
from src.application.ice_company.copy import Snap, clock, kind_label, team_gathered, weekday_nom
from src.application.ice_company.safety import strip_emoji_for_poster

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
# Голова на льду: занятое место крупнее, чтобы аватар читался рядом с силуэтом «ждём».
_SKATER_RADIUS = 28
_SKATER_NAME_SIZE = 32
_SKATER_INITIAL_SIZE = 28
_SKATER_NAME_MAX_W = 200


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


def render_company_card(snap: Snap, *, avatar_bytes: Sequence[bytes | None] = ()) -> bytes:
    image = Image.new("RGB", CARD_SIZE, _BG)
    draw = ImageDraw.Draw(image)
    kicker_font = _font("Inter-SemiBold.ttf", 32)
    time_font = _font("Inter-Bold.ttf", 96)
    place_font = _font("Inter-Regular.ttf", 32)
    chip_font = _font("Inter-SemiBold.ttf", 28)
    name_font = _font("Inter-SemiBold.ttf", _SKATER_NAME_SIZE)
    number_font = _font("Inter-Bold.ttf", 92)
    word_font = _font("Inter-SemiBold.ttf", 36)

    pad = 64
    team = strip_emoji_for_poster((snap.team_title or "").strip())
    title_font = _font("Inter-Bold.ttf", 50)
    y = 40
    if team:
        team_rows = _wrap(draw, team, title_font, CARD_SIZE[0] - pad * 2, 2)
        for row in team_rows:
            draw.text((pad, y), row, font=title_font, fill=_INK)
            y += 56
        y += 8
    else:
        draw.text((pad, y), weekday_nom(snap.starts_at).upper(), font=kicker_font, fill=_ACCENT)
        y = 84
    _draw_kind(draw, kind_label(snap.kind), chip_font, pad)
    draw.text((pad, y), clock(snap.starts_at), font=time_font, fill=_INK)
    venue_y = y + 108
    for index, row in enumerate(_wrap(draw, snap.venue, place_font, 640, 1)):
        draw.text((pad, venue_y), row, font=place_font, fill=_MUTED)

    rink_top = max(250, venue_y + 48)
    rink = (pad, rink_top, CARD_SIZE[0] - pad, 860)
    gathered = team_gathered(snap)
    _draw_rink(image, rink)
    if gathered:
        _draw_gathered_glow(image, rink)
    _draw_skaters(image, snap, name_font, rink, avatar_bytes=avatar_bytes, team_ready=gathered)

    missing = snap.min_people - len(snap.going_names)
    closed = snap.cancelled or snap.expired or snap.status in ("cancelled", "expired")
    tagline_font = _font("Inter-SemiBold.ttf", 30)
    if closed:
        headline, word, color = ("Не собрались" if snap.expired or snap.status == "expired" else "Снято", "", _MUTED)
        number_font = _font("Inter-Bold.ttf", 64)
    elif gathered:
        headline, word, color = ("Едем", "", _ACCENT)
        number_font = _font("Inter-Bold.ttf", 72)
    else:
        headline, word, color = (str(missing), "ещё", _INK)
    draw.text((pad, 900), headline, font=number_font, fill=color)
    if word:
        gap = int(draw.textlength(headline, font=number_font)) + 18
        draw.text((pad + gap, 948), word, font=word_font, fill=_ACCENT)
    if gathered and not closed:
        draw.text((pad, 978), "Команда в сборе", font=tagline_font, fill=_ACCENT)
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


def _draw_gathered_glow(image: Image.Image, rink: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = rink
    cx = (left + right) // 2
    cy = (top + bottom) // 2
    overlay = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    pen = ImageDraw.Draw(overlay)
    for radius, alpha in ((430, 22), (330, 32), (240, 42)):
        pen.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=(_ACCENT[0], _ACCENT[1], _ACCENT[2], alpha),
        )
    image.paste(overlay, (0, 0), overlay)


def _draw_skaters(
    image: Image.Image,
    snap: Snap,
    font: ImageFont.FreeTypeFont,
    rink: tuple[int, int, int, int],
    *,
    avatar_bytes: Sequence[bytes | None],
    team_ready: bool = False,
) -> None:
    names = list(snap.going_names)
    faces = list(avatar_bytes[: len(names)])
    while len(faces) < len(names):
        faces.append(None)
    holes = max(0, snap.min_people - len(names))
    count = min(_ON_ICE, max(len(names), min(len(names) + holes, _ON_ICE), 1))
    if not names and holes <= 0:
        count = 0
    shown = names[:count]
    shown_faces = faces[:count]
    empty = count - len(shown)
    spots = _SPOTS[max(count, 1)][:count]
    left, top, right, bottom = rink
    inset = 26
    ice_left, ice_top = left + inset, top + inset
    ice_w, ice_h = (right - left) - inset * 2, (bottom - top) - inset * 2
    overlay = ImageDraw.Draw(image)
    for (fx, fy), label, face in zip(
        spots,
        shown + [""] * empty,
        shown_faces + [None] * empty,
        strict=False,
    ):
        _skater(
            image,
            overlay,
            ice_left + ice_w * fx,
            ice_top + ice_h * fy,
            label,
            font,
            face,
            team_ready=team_ready,
        )


def _skater(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    label: str,
    font: ImageFont.FreeTypeFont,
    face: bytes | None,
    *,
    team_ready: bool,
) -> None:
    radius = _SKATER_RADIUS
    shoulder_w = 54
    display = strip_emoji_for_poster(label)
    if not label and not display:
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=_HOLE, width=3)
        plate = (cx - shoulder_w, cy + radius + 10, cx + shoulder_w, cy + radius + 52)
        draw.rounded_rectangle(plate, radius=20, outline=_HOLE, width=3)
        return
    if face:
        _paste_face(image, draw, cx, cy, radius, face)
    else:
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=_PLAYER)
        initial = (display[:1] if display else "?").upper()
        initial_font = _font("Inter-Bold.ttf", _SKATER_INITIAL_SIZE)
        initial_w = draw.textlength(initial, font=initial_font)
        draw.text((cx - initial_w / 2, cy - initial_font.size // 2), initial, font=initial_font, fill=_INK)
    if team_ready:
        halo = (cx - radius - 5, cy - radius - 5, cx + radius + 5, cy + radius + 5)
        draw.ellipse(halo, outline=_ACCENT, width=5)
    if not display:
        return
    name = _fit(draw, display, font, _SKATER_NAME_MAX_W)
    text_w = draw.textlength(name, font=font)
    box_w = text_w + 32
    box = (cx - box_w / 2, cy + radius + 10, cx + box_w / 2, cy + radius + 54)
    draw.rounded_rectangle(box, radius=20, fill=_PLAYER)
    draw.text((box[0] + 16, box[1] + 8), name, font=font, fill=_INK)


def _paste_face(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    radius: int,
    body: bytes,
) -> None:
    size = radius * 2
    try:
        face = Image.open(io.BytesIO(body)).convert("RGBA")
    except Exception:
        return
    face = face.resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    box = (int(cx - radius), int(cy - radius))
    image.paste(face, box, mask)
    ring = (cx - radius - 2, cy - radius - 2, cx + radius + 2, cy + radius + 2)
    draw.ellipse(ring, outline=_INK, width=4)
    draw.ellipse(ring, outline=_PLAYER, width=2)


