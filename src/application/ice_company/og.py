"""Превью 1200×630. Кэш на HTTP — 15 минут."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from src.application.ice_city_day_og import _font

OG_SIZE = (1200, 630)


def render_company_og(*, title: str, line: str) -> bytes:
    image = Image.new("RGB", OG_SIZE, (13, 27, 38))
    draw = ImageDraw.Draw(image)
    draw.text((72, 150), "Компания на лёд", font=_font("Inter-SemiBold.ttf", 42), fill=(159, 217, 214))
    draw.text((72, 240), (title or "Сбор")[:40], font=_font("Inter-Bold.ttf", 64), fill=(255, 255, 255))
    draw.text((72, 360), (line or "")[:80], font=_font("Inter-Regular.ttf", 42), fill=(195, 210, 220))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
