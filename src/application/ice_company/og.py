"""Плакат компании для чата и превью ссылки. Квадрат 1080."""

from __future__ import annotations

import io
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from src.application.ice_city_day_og import _fit, _font
from src.application.ice_company.copy import Snap, clock, closed_headline, crowd_line, kind_label, weekday_nom
from src.application.ice_company.safety import strip_emoji_for_poster

CARD_SIZE = (1080, 1080)
_BG = (14, 28, 36)
_INK = (244, 247, 248)
_MUTED = (155, 176, 188)
_ACCENT = (127, 215, 216)
# Тёмная площадка в цветах сайта: --g-dark-line для разметки, лист чуть светлее фона.
_SHEET = (17, 34, 45)
_RINK_LINE = (44, 70, 89)
# Бирюза поверх листа, как .b-motif__mid (55%) и __dot (70%) на сайте — уже смешанная.
_RINK_MID = (78, 134, 139)
_RINK_DOT = (94, 161, 164)
_PLAYER = (29, 47, 61)

_SPOTS: dict[int, tuple[tuple[float, float], ...]] = {
    1: ((0.22, 0.50),),
    2: ((0.20, 0.50), (0.80, 0.50)),
    3: ((0.18, 0.32), (0.82, 0.32), (0.38, 0.76)),
    4: ((0.18, 0.30), (0.82, 0.30), (0.18, 0.74), (0.82, 0.74)),
    5: ((0.18, 0.28), (0.82, 0.28), (0.18, 0.74), (0.82, 0.74), (0.40, 0.78)),
    6: ((0.18, 0.26), (0.40, 0.22), (0.60, 0.22), (0.82, 0.26), (0.30, 0.78), (0.70, 0.78)),
}
_ON_ICE = 6
_SKATER_RADIUS = 28
_SKATER_NAME_SIZE = 32
_SKATER_INITIAL_SIZE = 28
_SKATER_NAME_MAX_W = 200
_DEFAULT_TEAM = "Компания на лёд"


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
    team_title_font = _font("Inter-Bold.ttf", 56)
    crowd_font = _font("Inter-SemiBold.ttf", 30)

    pad = 64
    draw.text((pad, 40), weekday_nom(snap.starts_at).upper(), font=kicker_font, fill=_ACCENT)
    _draw_kind(draw, kind_label(snap.kind), chip_font, pad)
    draw.text((pad, 84), clock(snap.starts_at), font=time_font, fill=_INK)
    venue_y = 192
    for row in _wrap(draw, snap.venue, place_font, 640, 1):
        draw.text((pad, venue_y), row, font=place_font, fill=_MUTED)

    rink_top = max(250, venue_y + 48)
    rink = (pad, rink_top, CARD_SIZE[0] - pad, 820)
    going_n = len(snap.going_names)
    glow = going_n >= 3 and closed_headline(snap) is None
    _draw_rink(image, rink)
    if glow:
        _draw_gathered_glow(image, rink)
    _draw_skaters(image, snap, name_font, rink, avatar_bytes=avatar_bytes, team_ready=glow)

    closed = closed_headline(snap)
    bottom_y = 860
    if closed:
        headline_font = _font("Inter-Bold.ttf", 64)
        draw.text((pad, bottom_y), closed, font=headline_font, fill=_MUTED)
    else:
        team_raw = strip_emoji_for_poster((snap.team_title or "").strip()) or _DEFAULT_TEAM
        team_rows = _wrap(draw, team_raw, team_title_font, CARD_SIZE[0] - pad * 2, 2)
        y = bottom_y
        for row in team_rows:
            draw.text((pad, y), row, font=team_title_font, fill=_INK)
            y += 62
        line = crowd_line(going_n)
        for row in _wrap(draw, line, crowd_font, CARD_SIZE[0] - pad * 2, 2):
            draw.text((pad, y), row, font=crowd_font, fill=_ACCENT)
            y += 36

    extra = going_n - _ON_ICE
    if extra > 0 and closed is None:
        more = f"и ещё {extra}"
        more_w = int(draw.textlength(more, font=place_font))
        draw.text((CARD_SIZE[0] - pad - more_w, 800), more, font=place_font, fill=_MUTED)

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
    """Тёмная разметка катка, как обложки сайта (``rink_motif_svg``): линии в цвет
    ``--g-dark-line``, центр — бирюзовым. Яркий белый лёд с красным и синим в ленте
    чата спорил с лицами и названием команды."""
    left, top, right, bottom = rink
    width, height = right - left, bottom - top
    sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=86, fill=255)
    pen = ImageDraw.Draw(sheet)
    pen.rounded_rectangle((0, 0, width - 1, height - 1), radius=86, fill=_SHEET, outline=_RINK_LINE, width=4)

    def x_at(fraction: float) -> int:
        return int(width * fraction)

    def y_at(fraction: float) -> int:
        return int(height * fraction)

    for fraction in (0.3, 0.7):
        pen.line((x_at(fraction), 0, x_at(fraction), height), fill=_RINK_LINE, width=4)
    mid = _RINK_MID
    pen.line((x_at(0.5), 0, x_at(0.5), height), fill=mid, width=6)
    radius = 82
    cx, cy = x_at(0.5), y_at(0.5)
    pen.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=mid, width=6)
    pen.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=_RINK_DOT)
    for fx in (0.13, 0.87):
        for fy in (0.27, 0.73):
            r = 52
            pen.ellipse(
                (x_at(fx) - r, y_at(fy) - r, x_at(fx) + r, y_at(fy) + r), outline=_RINK_LINE, width=4
            )

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
    if not names:
        return
    faces = list(avatar_bytes[: len(names)])
    while len(faces) < len(names):
        faces.append(None)
    count = min(_ON_ICE, len(names))
    shown = names[:count]
    shown_faces = faces[:count]
    spots = _SPOTS[max(count, 1)][:count]
    left, top, right, bottom = rink
    inset = 26
    ice_left, ice_top = left + inset, top + inset
    ice_w, ice_h = (right - left) - inset * 2, (bottom - top) - inset * 2
    overlay = ImageDraw.Draw(image)
    for (fx, fy), label, face in zip(spots, shown, shown_faces, strict=False):
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
    display = strip_emoji_for_poster(label)
    if face:
        _paste_face(image, draw, cx, cy, radius, face)
    else:
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=_PLAYER)
        initial = (display[:1] if display else "?").upper()
        initial_font = _font("Inter-Bold.ttf", _SKATER_INITIAL_SIZE)
        initial_w = draw.textlength(initial, font=initial_font)
        draw.text((cx - initial_w / 2, cy - initial_font.size // 2), initial, font=initial_font, fill=_INK)
    # На тёмном льду лицо держит бирюзовое кольцо; собравшимся (3+) — толще.
    ring = 6 if team_ready else 3
    halo = (cx - radius - ring, cy - radius - ring, cx + radius + ring, cy + radius + ring)
    draw.ellipse(halo, outline=_ACCENT, width=ring)
    if not display:
        return
    name = _fit(draw, display, font, _SKATER_NAME_MAX_W)
    text_w = draw.textlength(name, font=font)
    box_w = text_w + 32
    box = (cx - box_w / 2, cy + radius + 10, cx + box_w / 2, cy + radius + 54)
    draw.rounded_rectangle(box, radius=20, fill=_PLAYER, outline=_RINK_LINE, width=2)
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
