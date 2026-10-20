"""Картинки открытки «Пойдёшь со мной на каток?» (TASK-233).

* ``og.png`` 1200×630 — превью ссылки в чате. Тёмная подача Glide, как блок «Так
  увидят в чате» в прототипе: тиловая рейка, срез угла, вопрос с именем, время и каток.
* ``ticket.png`` 1080×1350 — билет «ДА» с экрана ответа: им делятся после «да».

Шрифт — Inter из ``static/fonts`` через ``_font`` (Golos локально нет, рендер не ходит
в сеть). Тексты — из ``zovi_card_page``, теми же функциями, что og:title и экран.
"""

from __future__ import annotations

import io
from typing import Any, Mapping

from PIL import Image, ImageChops, ImageDraw, ImageFont

from src.application.ice_city_day_og import _font
from src.application.zovi_card_page import (
    activity,
    day_short,
    day_ticket,
    match_title_of,
    ticket_who,
    verdict,
)

OG_SIZE = (1200, 630)
TICKET_SIZE = (1080, 1350)

# Палитра прототипа (glide-tokens.css): тёмная только в превью, билет — светлый, как на экране.
_DARK = (13, 27, 38)
_DARK_2 = (29, 47, 61)
_ON_DARK = (255, 255, 255)
_ON_DARK_MUTED = (195, 210, 220)
_ON_DARK_ACCENT = (159, 217, 214)
_ACCENT = (69, 185, 187)
_ACCENT_INK = (11, 110, 112)
_BG = (244, 246, 247)
_SURFACE = (255, 255, 255)
_INK = (13, 27, 38)
_MUTED = (93, 114, 133)
_LINE = (225, 232, 236)
_LINE_STRONG = (201, 213, 220)

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont
Segment = tuple[str, tuple[int, int, int]]


def wrap_words(draw: ImageDraw.ImageDraw, text: str, font: Font, max_w: int, max_lines: int) -> list[str]:
    """Перенос по словам, без обрезки посреди слова. Не влезло в ``max_lines`` — хвост с «…» после слова."""
    words = (text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if not current or draw.textlength(trial, font=font) <= max_w:
            current = trial
            continue
        lines.append(current)
        current = word
        if len(lines) == max_lines:
            lines[-1] = _ellipsize_words(draw, lines[-1], font, max_w)
            return lines
    if current:
        lines.append(current)
    return lines


def _ellipsize_words(draw: ImageDraw.ImageDraw, line: str, font: Font, max_w: int) -> str:
    words = line.split()
    while len(words) > 1 and draw.textlength(" ".join(words) + "…", font=font) > max_w:
        words.pop()
    return " ".join(words) + "…"


def _question_words(to_name: str | None, kind: str | None) -> list[list[Segment]]:
    """Слова вопроса с цветом: имя — тиловым, как на открытке."""
    to = (to_name or "").strip()
    tail = f"пойдёшь со мной {activity(kind)}?"
    words: list[list[Segment]] = []
    if to:
        name_words = to.split()
        for idx, word in enumerate(name_words):
            segs: list[Segment] = [(word, _ON_DARK_ACCENT)]
            if idx == len(name_words) - 1:
                segs.append((",", _ON_DARK))
            words.append(segs)
    else:
        tail = tail[:1].upper() + tail[1:]
    words.extend([[(w, _ON_DARK)] for w in tail.split()])
    return words


def _wrap_segments(
    draw: ImageDraw.ImageDraw, words: list[list[Segment]], font: Font, max_w: int
) -> list[list[list[Segment]]]:
    space = draw.textlength(" ", font=font)
    lines: list[list[list[Segment]]] = [[]]
    width = 0.0
    for word in words:
        w = sum(draw.textlength(t, font=font) for t, _ in word)
        add = w if not lines[-1] else width + space + w
        if lines[-1] and add > max_w:
            lines.append([word])
            width = w
        else:
            lines[-1].append(word)
            width = add
    return lines


def _draw_segments(
    draw: ImageDraw.ImageDraw, lines: list[list[list[Segment]]], font: Font, x: int, y: int, line_h: int
) -> int:
    space = draw.textlength(" ", font=font)
    for line in lines:
        cx = float(x)
        for word in line:
            for chunk, color in word:
                draw.text((cx, y), chunk, font=font, fill=color)
                cx += draw.textlength(chunk, font=font)
            cx += space
        y += line_h
    return y


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _brand(draw: ImageDraw.ImageDraw, xy: tuple[int, int], font: Font, *, ink: Any, dot: Any, muted: Any) -> None:
    x, y = xy
    draw.text((x, y), "Glide", font=font, fill=ink)
    x += int(draw.textlength("Glide", font=font))
    draw.text((x, y), ".", font=font, fill=dot)
    x += int(draw.textlength(". ", font=font))
    draw.text((x, y), "приглашение на лёд", font=font, fill=muted)


def render_zovi_og(invite: Mapping[str, Any]) -> bytes:
    """og.png 1200×630: «Glide. приглашение на лёд», вопрос, время и каток."""
    w, h = OG_SIZE
    img = Image.new("RGB", OG_SIZE, _DARK)
    draw = ImageDraw.Draw(img)
    pad = 84
    inner = w - pad - 96
    cut = 72
    draw.rectangle([(0, 0), (9, h)], fill=_ACCENT)
    draw.polygon([(w - cut, 0), (w, 0), (w, cut)], fill=_ACCENT)

    _brand(
        draw,
        (pad, 58),
        _font("Inter-Bold.ttf", 32),
        ink=_ON_DARK_MUTED,
        dot=_ON_DARK_ACCENT,
        muted=_ON_DARK_MUTED,
    )

    words = _question_words(invite.get("to_name"), str(invite.get("kind") or ""))
    lines: list[list[list[Segment]]] = []
    size = 84
    for size in (84, 76, 68, 60, 54):
        font = _font("Inter-Bold.ttf", size)
        lines = _wrap_segments(draw, words, font, inner)
        if len(lines) <= 3:
            break
    font = _font("Inter-Bold.ttf", size)
    _draw_segments(draw, lines[:3], font, pad, 124, int(size * 1.1))

    s = invite["session"]
    arena = s["arena"]
    top = 404
    draw.line([(pad, top), (w - pad, top)], fill=_DARK_2, width=2)
    f_time = _font("Inter-Bold.ttf", 64)
    f_day = _font("Inter-SemiBold.ttf", 32)
    f_place = _font("Inter-Regular.ttf", 32)
    time_text = str(s.get("starts_at_local") or "")
    draw.text((pad, top + 30), time_text, font=f_time, fill=_ON_DARK)
    col = pad + int(draw.textlength(time_text, font=f_time)) + 32
    col_w = w - pad - col
    draw.text((col, top + 28), day_short(s.get("local_date")), font=f_day, fill=_ON_DARK_ACCENT)
    place = str(arena.get("name") or "")
    if match_title_of(invite):
        place = f"{match_title_of(invite)}, {place}"
    place_lines = wrap_words(draw, place, f_place, col_w, 2)
    for i, line in enumerate(place_lines):
        draw.text((col, top + 72 + i * 40), line, font=f_place, fill=_ON_DARK_MUTED)
    return _png(img)


def _stamp(size: int) -> Image.Image:
    """Штамп «ДА»: двойное кольцо, повёрнут на -14°, как на экране."""
    scale = 2
    big = size * scale
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ring = int(big * 0.04)
    d.ellipse([(ring, ring), (big - ring, big - ring)], outline=_ACCENT_INK + (235,), width=ring * 2)
    inner = int(big * 0.13)
    d.ellipse([(inner, inner), (big - inner, big - inner)], outline=_ACCENT_INK + (235,), width=max(2, ring // 2))
    font = _font("Inter-Bold.ttf", int(big * 0.3))
    text = "ДА"
    tw = d.textlength(text, font=font)
    bbox = d.textbbox((0, 0), text, font=font)
    th = bbox[3] - bbox[1]
    d.text(((big - tw) / 2, (big - th) / 2 - bbox[1]), text, font=font, fill=_ACCENT_INK + (235,))
    layer = layer.rotate(14, resample=Image.Resampling.BICUBIC, expand=False)
    return layer.resize((size, size), Image.Resampling.LANCZOS)


def ticket_place_lines(invite: Mapping[str, Any]) -> tuple[str, str]:
    """Каток — отдельной строкой (переносится на две), адрес и цена — под ним."""
    s = invite["session"]
    arena = s["arena"]
    extra = [str(arena["address"])] if arena.get("address") else []
    if s.get("price"):
        extra.append(str(s["price"]))
    title = match_title_of(invite)
    if title:
        # Матч: команды первой строкой, Минск-Арена и адрес — под ними.
        extra.insert(0, str(arena.get("name") or ""))
        return title, " · ".join(extra)
    return str(arena.get("name") or ""), " · ".join(extra)


def render_zovi_ticket(
    invite: Mapping[str, Any],
    *,
    tries: int,
    seconds: int,
    falls: int,
    tricked: bool,
) -> bytes:
    """ticket.png 1080×1350: «{to} + {from}», время, дата, каток, штамп, вердикт, три числа."""
    w, h = TICKET_SIZE
    img = Image.new("RGB", TICKET_SIZE, _BG)
    draw = ImageDraw.Draw(img)
    margin = 64
    left, right = margin, w - margin
    top, bottom = 150, h - 96
    radius = 44

    f_kicker = _font("Inter-SemiBold.ttf", 34)
    draw.text((left + 8, 76), "Ответ получен", font=f_kicker, fill=_MUTED)

    draw.rounded_rectangle([(left, top), (right, bottom)], radius=radius, fill=_SURFACE, outline=_LINE, width=3)
    # Рейка слева — тил, как у билета на экране; скругление сохраняем маской.
    rail = Image.new("L", TICKET_SIZE, 0)
    ImageDraw.Draw(rail).rounded_rectangle([(left, top), (right, bottom)], radius=radius, fill=255)
    rail_fill = Image.new("RGB", TICKET_SIZE, _ACCENT)
    strip = Image.new("L", TICKET_SIZE, 0)
    ImageDraw.Draw(strip).rectangle([(left, top), (left + 9, bottom)], fill=255)
    img.paste(rail_fill, (0, 0), ImageChops.multiply(rail, strip))
    draw = ImageDraw.Draw(img)

    x = left + 60
    text_w = right - x - 56
    y = top + 56

    who = ticket_who(invite.get("to_name"), invite.get("from_name"))
    f_who = _font("Inter-SemiBold.ttf", 42)
    cx = float(x)
    for chunk, color in ((who[0], _INK), (" + ", _MUTED), (who[1], _INK)):
        draw.text((cx, y), chunk, font=f_who, fill=color)
        cx += draw.textlength(chunk, font=f_who)
    y += 76

    s = invite["session"]
    f_time = _font("Inter-Bold.ttf", 150)
    f_day = _font("Inter-SemiBold.ttf", 38)
    time_text = str(s.get("starts_at_local") or "")
    draw.text((x - 6, y), time_text, font=f_time, fill=_INK)
    tw = int(draw.textlength(time_text, font=f_time))
    draw.text((x + tw + 24, y + 98), day_ticket(s.get("local_date")), font=f_day, fill=_ACCENT_INK)
    y += 190

    f_place = _font("Inter-Regular.ttf", 38)
    place_w = int(text_w * 0.78)
    name, extra = ticket_place_lines(invite)
    for line in wrap_words(draw, name, f_place, place_w, 2):
        draw.text((x, y), line, font=f_place, fill=_INK)
        y += 50
    if extra:
        for line in wrap_words(draw, extra, f_place, place_w, 1):
            draw.text((x, y), line, font=f_place, fill=_MUTED)
            y += 50

    stamp_size = 196
    stamp = _stamp(stamp_size)
    img.paste(stamp, (right - stamp_size - 26, top + 26), stamp)

    # Перфорация: пунктир и два полукруглых выреза под цвет фона.
    cut_y = max(y + 40, top + 560)
    notch = 34
    for side in (left, right):
        draw.ellipse([(side - notch, cut_y - notch), (side + notch, cut_y + notch)], fill=_BG, outline=_LINE, width=3)
    draw.rectangle([(left - notch - 4, cut_y - notch - 4), (left - 2, cut_y + notch + 4)], fill=_BG)
    draw.rectangle([(right + 2, cut_y - notch - 4), (right + notch + 4, cut_y + notch + 4)], fill=_BG)
    dash_x = left + notch + 16
    while dash_x < right - notch - 16:
        draw.line([(dash_x, cut_y), (min(dash_x + 18, right - notch - 16), cut_y)], fill=_LINE_STRONG, width=4)
        dash_x += 32

    y = cut_y + 56
    f_verdict = _font("Inter-SemiBold.ttf", 54)
    text = verdict(tries, falls, tricked)
    v_lines = wrap_words(draw, text, f_verdict, text_w, 3)
    for line in v_lines:
        draw.text((x, y), line, font=f_verdict, fill=_INK)
        y += 68
    y += 56

    f_label = _font("Inter-SemiBold.ttf", 25)
    f_value = _font("Inter-Bold.ttf", 76)
    col_w = text_w // 3
    stats = (("ДЕРЖАЛИСЬ", f"{seconds} с"), ("ОТКАЗОВ", str(tries)), ("ПАДЕНИЙ", str(falls)))
    for i, (label, value) in enumerate(stats):
        sx = x + i * col_w
        draw.text((sx, y), label, font=f_label, fill=_MUTED)
        draw.text((sx, y + 40), value, font=f_value, fill=_INK)

    _brand(
        draw,
        (x, bottom - 86),
        _font("Inter-SemiBold.ttf", 32),
        ink=_MUTED,
        dot=_ACCENT_INK,
        muted=_MUTED,
    )
    return _png(img)
