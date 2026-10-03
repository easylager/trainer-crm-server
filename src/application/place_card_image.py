"""
Картинка места для шеринга: og.png (1200×630) и story.png (1080×1920) — TASK-146.

Единственное место продукта с тёмной, драматичной подачей (DEC-007): это не часть
интерфейса, а экспортируемый артефакт для чужой ленты. В чате его сначала видят,
потом читают, поэтому на картинке — план, а не реклама: что, когда, почём, где.
Фото арены сюда сознательно не тянем: оно лежит в объектном хранилище, а рендер
не должен ходить в сеть; и фотография катка не говорит «сб 20:30, 25 BYN».

Всё, что на картинке, берётся из той же модели, что и страница (``place_page``):
ни одной декоративной цифры.
"""

from __future__ import annotations

import io
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont

from src.application.ice_city_day_og import _font
from src.shared.venue_types import has_public_skating
from src.application.ice_city_day import plural_ru
from src.application.place_page import (
    _parse_iso_date,
    _services,
    _where,
    absolute_day_label,
    slot_price,
    slot_price_lines,
    slot_when,
    status_badge,
)

OG_SIZE = (1200, 630)
STORY_SIZE = (1080, 1920)

_TOP = (11, 74, 80)
_BOTTOM = (4, 12, 18)
_INK = (255, 255, 255)
_MUTED = (160, 190, 200)
_ACCENT = (94, 214, 210)
_LINE = (40, 70, 80)


def _gradient(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, _BOTTOM)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = (y / max(1, h - 1)) ** 0.8
        color = tuple(int(_TOP[i] + (_BOTTOM[i] - _TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    return img


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, max_w: int, max_lines: int) -> list[str]:
    words = (text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_w:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    # Одно слово длиннее строки — режем по ширине.
    out = []
    for line in lines:
        while line and draw.textlength(line, font=font) > max_w:
            line = line[:-2] + "…"
        out.append(line)
    return out


_TYPE_COLORS = {
    "ice": (42, 167, 201),
    "outdoor": (42, 167, 201),
    "gym": (224, 138, 30),
    "choreo": (224, 138, 30),
    "shop": (122, 90, 245),
}


def card_lines(view: Mapping[str, Any], *, invite: bool) -> dict[str, str]:
    """Тексты картинки — отдельно от рисования, чтобы их можно было проверить тестом.

    Даты только абсолютные («Пт, 2 окт»): превью живёт в кэше Telegram днями.
    """
    card = view["card"]
    city = str(card.get("city_name") or "").strip()
    vt = card.get("venue_type")
    skating = has_public_skating(vt)
    kicker = "Погнали кататься?" if invite and skating else ("Погнали?" if invite else "Карта льда")
    if city and not invite:
        kicker = f"{kicker} · {city}"
    slot = view.get("focus") or (view.get("next_slot") if skating else None)
    big = ""
    day = ""
    time = ""
    sub_bits: list[str] = []
    if slot is not None:
        big = slot_when(slot, today=view["today"], absolute=True)
        d = _parse_iso_date(slot.get("local_date"))
        day = absolute_day_label(d) if d else ""
        time = str(slot.get("starts_at_local") or "")[:5]
        price = slot_price(slot)
        if price:
            sub_bits.append(price)
    elif vt == "shop":
        big = " · ".join(_services(card)) or "Магазин для катания"
    else:
        badge = status_badge(view)
        if badge and badge[0] in ("closed", "open", "shut"):
            big = badge[1]
        elif skating and view.get("session_count"):
            n = int(view["session_count"])
            big = f"{n} {plural_ru(n, 'сеанс', 'сеанса', 'сеансов')} на неделе"
        else:
            big = str(card.get("venue_noun") or "")
    district = str(card.get("district") or "").strip()
    if district:
        sub_bits.append(district)
    elif _where(card):
        sub_bits.append(_where(card))
    return {
        "kicker": kicker.upper(),
        "title": str(card.get("name") or ""),
        "big": big,
        "day": day,
        "time": time,
        "sub": " · ".join(sub_bits),
        # Детский билет и прокат — то, что спрашивают первым, когда зовут с ребёнком.
        "extra": " · ".join(
            line for line in (slot_price_lines(slot) if slot is not None else []) if not line.startswith("Взрослый")
        ),
        "foot": "Расписание, цены и как добраться — по ссылке",
    }


def _corner_cut(draw: ImageDraw.ImageDraw, size: tuple[int, int], cut: int) -> None:
    """Срез 45° в правом верхнем углу — «ribbon»-геометрия продукта (mini-app-arena-ribbon.css)."""
    w, _h = size
    draw.polygon([(w - cut, 0), (w, 0), (w, cut)], fill=_ACCENT)


def _render_og(view: Mapping[str, Any], lines: Mapping[str, str]) -> Image.Image:
    w, h = OG_SIZE
    img = _gradient(OG_SIZE)
    draw = ImageDraw.Draw(img)
    _corner_cut(draw, OG_SIZE, 64)
    pad = 80
    inner = w - pad * 2
    rail = _TYPE_COLORS.get(str(view["card"].get("venue_type")), _MUTED)
    f_kicker = _font("Inter-SemiBold.ttf", 30)
    f_title = _font("Inter-Bold.ttf", 72)
    f_big = _font("Inter-Bold.ttf", 64)
    f_sub = _font("Inter-Regular.ttf", 34)
    f_foot = _font("Inter-Regular.ttf", 28)

    y = 72
    draw.text((pad, y), lines["kicker"], font=f_kicker, fill=_ACCENT)
    y += 58
    top_of_rail = y + 8
    for line in _wrap(draw, lines["title"], f_title, inner, 2):
        draw.text((pad, y), line, font=f_title, fill=_INK)
        y += 84
    y += 18
    for line in _wrap(draw, lines["big"], f_big, inner, 2):
        draw.text((pad, y), line, font=f_big, fill=_ACCENT)
        y += 76
    if lines["sub"]:
        y += 4
        for line in _wrap(draw, lines["sub"], f_sub, inner, 1):
            draw.text((pad, y), line, font=f_sub, fill=_MUTED)
            y += 44
    # Цветная рейка типа места — та же, что у строки в каталоге (DEC-006).
    draw.rectangle([(pad - 32, top_of_rail), (pad - 26, y - 6)], fill=rail)

    foot_y = h - 96
    draw.line([(pad, foot_y - 28), (w - pad, foot_y - 28)], fill=_LINE, width=2)
    brand = "Glide"
    brand_w = int(draw.textlength(brand, font=f_foot))
    foot = _wrap(draw, lines["foot"], f_foot, inner - brand_w - 40, 1)
    if foot:
        draw.text((pad, foot_y), foot[0], font=f_foot, fill=_MUTED)
    draw.text((w - pad - brand_w, foot_y), brand, font=f_foot, fill=_ACCENT)
    return img


def _render_story(view: Mapping[str, Any], lines: Mapping[str, str], display_url: str) -> Image.Image:
    """
    Сторис — постер-билет. Ссылка в историях не кликается (кроме стикеров), поэтому
    адрес места напечатан на корешке: его можно набрать руками.
    """
    w, h = STORY_SIZE
    img = _gradient(STORY_SIZE)
    draw = ImageDraw.Draw(img)
    pad = 84
    f_kicker = _font("Inter-SemiBold.ttf", 40)
    f_title = _font("Inter-Bold.ttf", 76)
    f_day = _font("Inter-SemiBold.ttf", 52)
    f_time = _font("Inter-Bold.ttf", 210)
    f_big = _font("Inter-Bold.ttf", 76)
    f_sub = _font("Inter-Regular.ttf", 42)
    f_url = _font("Inter-SemiBold.ttf", 38)
    f_brand = _font("Inter-Regular.ttf", 34)

    draw.text((pad, 220), lines["kicker"], font=f_kicker, fill=_ACCENT)

    # Билет: тёмная плашка с вырезами-полукругами на линии отрыва.
    left, right = pad - 20, w - pad + 20
    top, bottom = 330, 1560
    stub_y = 1300
    ticket = (13, 32, 40)
    draw.rounded_rectangle([(left, top), (right, bottom)], radius=36, fill=ticket, outline=_LINE, width=2)
    notch = 34
    for cx in (left, right):
        draw.ellipse([(cx - notch, stub_y - notch), (cx + notch, stub_y + notch)], fill=_BOTTOM)
    for x in range(left + 50, right - 50, 34):
        draw.line([(x, stub_y), (x + 16, stub_y)], fill=_LINE, width=3)
    rail = _TYPE_COLORS.get(str(view["card"].get("venue_type")), _MUTED)
    draw.rectangle([(left, top + 60), (left + 8, top + 300)], fill=rail)

    inner = right - left - 120
    x = left + 60
    y = top + 70
    for line in _wrap(draw, lines["title"], f_title, inner, 3):
        draw.text((x, y), line, font=f_title, fill=_INK)
        y += 92
    y += 40
    if lines["time"]:
        draw.text((x, y), lines["day"], font=f_day, fill=_MUTED)
        y += 70
        draw.text((x - 8, y), lines["time"], font=f_time, fill=_ACCENT)
        y += 240
    else:
        for line in _wrap(draw, lines["big"], f_big, inner, 4):
            draw.text((x, y), line, font=f_big, fill=_ACCENT)
            y += 92
        y += 20
    for line in _wrap(draw, lines["sub"], f_sub, inner, 2):
        draw.text((x, min(y, stub_y - 120)), line, font=f_sub, fill=_MUTED)
        y += 56
    rows = lines.get("rows")
    if rows:
        # Подборка: одна площадка — одна строка «название …… время». Раньше это был один
        # абзац с «…» в конце, и половина мест обрезалась на полуслове.
        f_row = _font("Inter-SemiBold.ttf", 44)
        f_row_time = _font("Inter-Bold.ttf", 44)
        row_h = 84
        limit = stub_y - 70
        room = max(1, (limit - y) // row_h)
        # Всё влезло — рисуем всё; иначе оставляем место под строку «и ещё N».
        shown = rows if len(rows) <= room else rows[: max(1, (limit - y - 64) // row_h)]
        draw.line([(x, y), (x + inner, y)], fill=_LINE, width=2)
        for name, when in shown:
            tw = int(draw.textlength(when, font=f_row_time)) + 30 if when else 0
            label = _wrap(draw, name, f_row, inner - tw, 1)[0]
            draw.text((x, y + 16), label, font=f_row, fill=_INK)
            if when:
                draw.text((x + inner - tw + 30, y + 16), when, font=f_row_time, fill=_ACCENT)
            y += row_h
            draw.line([(x, y), (x + inner, y)], fill=_LINE, width=2)
        hidden = len(rows) - len(shown)
        if hidden > 0:
            more = f"и ещё {hidden} {plural_ru(hidden, 'место', 'места', 'мест')} — по ссылке"
            draw.text((x, y + 20), more, font=f_sub, fill=_MUTED)
    elif lines.get("extra"):
        y += 16
        for line in _wrap(draw, lines["extra"].replace(" · ", "  ·  "), f_sub, inner, 3):
            if y > stub_y - 80:
                break
            draw.text((x, y), line, font=f_sub, fill=_MUTED)
            y += 56

    # URL без пробелов: переносим по «/», чтобы адрес читался целиком, а не «mins…».
    url_lines = _wrap(draw, display_url.replace("/", " /").replace(": /", ":/"), f_url, inner, 2) if display_url else []
    url_lines = [line.replace(" /", "/") for line in url_lines]
    uy = stub_y + 70
    for line in url_lines:
        draw.text((x, uy), line, font=f_url, fill=_INK)
        uy += 52
    draw.text((x, bottom - 70), "Glide · карта льда", font=f_brand, fill=_ACCENT)
    return img


def render_place_card(
    view: Mapping[str, Any],
    *,
    invite: bool = False,
    story: bool = False,
    display_url: str = "",
) -> bytes:
    lines = card_lines(view, invite=invite)
    img = _render_story(view, lines, display_url) if story else _render_og(view, lines)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_selection_card(view: Mapping[str, Any], *, story: bool = False) -> bytes:
    """og.png / story.png подборки (/c/{город}): что за подборка, сколько мест и сеансов, первые места."""
    from src.application.selection_page import (
        absolute_window_phrase,
        selection_share_description,
        selection_share_title,
    )

    window = view.get("window")
    phrase = absolute_window_phrase(window) if window and view.get("skating") else ""
    kicker = f"Карта льда · {phrase}" if phrase else "Карта льда"
    names = [str(i.get("name") or "") for i in (view.get("items") or [])[:3]]
    lines = {
        "kicker": kicker.upper(),
        "title": selection_share_title(view),
        "big": selection_share_description(view),
        "sub": " · ".join(n for n in names if n),
        "foot": "Расписание, цены и адреса — по ссылке",
    }
    fake_view = {"card": {"venue_type": view.get("venue") or "ice"}}
    if story:
        # В середине билета — первые места с ближайшим временем: ради этого и смотрят историю.
        rows = []
        for item in view.get("items") or []:
            slots = (view.get("slots") or {}).get(int(item["id"])) or []
            when = str(slots[0].get("starts_at_local") or "")[:5] if slots else ""
            rows.append((str(item.get("name") or ""), when))
        lines = {**lines, "day": "", "time": "", "sub": "", "rows": rows}
        img = _render_story(fake_view, lines, display_url=view.get("display_url") or "")
    else:
        img = _render_og(fake_view, lines)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
