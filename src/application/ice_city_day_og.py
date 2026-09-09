"""
OG-превью для «Лёд сегодня в городе» (TASK-096 S3).

Зачем картинка вообще: в чате ссылку сначала видят, а потом читают. Telegram рисует
карточку по og:image, и без неё пересланная ссылка выглядит как строчка текста —
то есть как спам, а не как продукт. Это и есть та часть AC-003, где «артефакт красив
в превью Telegram, а не только внутри приложения».

Шрифт — Inter из ``static/fonts``. Технический план называл Golos Text, но Golos в
репозитории нет: интерфейс тянет его с fonts.googleapis.com, локального TTF не
существует, а рендер картинки на сервере не может ходить в сеть. Inter уже лежит в
репозитории (им печатаются PDF-сертификаты) и покрывает кириллицу.

Всё, что попадает на картинку, приходит из той же выборки, что и страница: число
катков, число сеансов, диапазон цен. Ничего декоративно-выдуманного (AC-005).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Mapping

from PIL import Image, ImageDraw, ImageFont

from src.application.ice_city_day import plural_ru, price_range_compact

OG_WIDTH = 1200
OG_HEIGHT = 630

_FONTS_DIR = Path(__file__).resolve().parents[2] / "static" / "fonts"

# Тёмная карточка: в ленте Telegram она отделяется от обоих системных фонов, светлого
# и тёмного, а светлая на светлом сливается в белый прямоугольник.
_BG = (10, 22, 32)
_INK = (255, 255, 255)
_MUTED = (150, 172, 188)
_ACCENT = (94, 214, 210)


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = _FONTS_DIR / name
    if path.is_file():
        return ImageFont.truetype(str(path), size)
    # Дефолтный битмап-шрифт Pillow кириллицу не покажет, но 500 на превью хуже, чем
    # некрасивое превью: страница обязана открыться даже в окружении без шрифтов.
    return ImageFont.load_default()


def _fit(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    ellipsis = "…"
    cut = text
    while cut and draw.textlength(cut + ellipsis, font=font) > max_w:
        cut = cut[:-1]
    return (cut.rstrip() + ellipsis) if cut else ellipsis


def render_ice_city_day_og(*, city_name: str, day: Mapping[str, object]) -> bytes:
    """PNG 1200×630 для og:image. Возвращает готовые байты, на диск ничего не пишет."""
    img = Image.new("RGB", (OG_WIDTH, OG_HEIGHT), _BG)
    draw = ImageDraw.Draw(img)

    f_kicker = _font("Inter-SemiBold.ttf", 34)
    f_title = _font("Inter-Bold.ttf", 92)
    f_stat = _font("Inter-Bold.ttf", 64)
    f_stat_label = _font("Inter-Regular.ttf", 30)
    f_foot = _font("Inter-Regular.ttf", 32)

    pad = 80
    inner = OG_WIDTH - pad * 2

    arenas = int(day.get("arena_count") or 0)
    sessions = int(day.get("session_count") or 0)
    label = str(day.get("day_label") or "сегодня")

    draw.text((pad, 92), f"ЛЁД · {label.upper()}", font=f_kicker, fill=_ACCENT)
    draw.text((pad, 148), _fit(draw, city_name, f_title, inner), font=f_title, fill=_INK)

    if sessions:
        columns: list[tuple[str, str]] = [
            (str(sessions), plural_ru(sessions, "сеанс", "сеанса", "сеансов")),
            (str(arenas), plural_ru(arenas, "каток", "катка", "катков")),
        ]
        prices = price_range_compact(day)
        if prices:
            columns.append((prices, "цена билета"))
        x = pad
        for value, caption in columns:
            value_text = _fit(draw, value, f_stat, 420)
            draw.text((x, 320), value_text, font=f_stat, fill=_INK)
            draw.text((x, 400), caption, font=f_stat_label, fill=_MUTED)
            x += max(
                int(draw.textlength(value_text, font=f_stat)),
                int(draw.textlength(caption, font=f_stat_label)),
            ) + 90
        footer = "Время и цены каждого сеанса — на странице"
    else:
        draw.text((pad, 330), "Расписание на этот день пустое", font=f_stat_label, fill=_MUTED)
        footer = "Загляните — расписание обновляется"

    draw.line([(pad, OG_HEIGHT - 132), (OG_WIDTH - pad, OG_HEIGHT - 132)], fill=(30, 48, 62), width=2)
    draw.text((pad, OG_HEIGHT - 100), _fit(draw, footer, f_foot, inner - 120), font=f_foot, fill=_MUTED)
    draw.text(
        (OG_WIDTH - pad - int(draw.textlength("Glide", font=f_foot)), OG_HEIGHT - 100),
        "Glide",
        font=f_foot,
        fill=_ACCENT,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
