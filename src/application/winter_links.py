"""Ссылки и deeplink-и зимних точек (TASK-343): бот, маршрут, карта Яндекса.

Static API Яндекса: картинку подставляем ссылкой при каждом показе и **не сохраняем** (условие
бесплатного тарифа); логотип и «Открыть в Картах» не скрываем (это ответственность вёрстки).
Для неточного геокода (city / street / none) карта и пин не строятся вовсе.
"""
from __future__ import annotations

import re
from urllib.parse import quote, urlencode

from src.application.place_links import telegram_bot_start_link

MAP_PRECISIONS = frozenset({"house", "osm_exact", "manual"})

BELL_PREFIX = "wbell_"  # колокольчик на точку
PHOTO_PREFIX = "wphoto_"  # «фото точки N»
NEAR_PARAM = "wnear"  # «лёд рядом со мной»
_BELL_RE = re.compile(r"^wbell_([1-9][0-9]{0,8})$")
_PHOTO_RE = re.compile(r"^wphoto_([1-9][0-9]{0,8})$")


def bell_param(arena_id: int) -> str:
    return f"{BELL_PREFIX}{int(arena_id)}"


def photo_param(arena_id: int) -> str:
    return f"{PHOTO_PREFIX}{int(arena_id)}"


def parse_winter_start(payload: str | None) -> tuple[str, int | None] | None:
    """``wbell_7`` -> ("bell", 7); ``wphoto_7`` -> ("photo", 7); ``wnear`` -> ("near", None)."""
    value = (payload or "").strip()
    if value == NEAR_PARAM:
        return ("near", None)
    m = _BELL_RE.match(value)
    if m:
        return ("bell", int(m.group(1)))
    m = _PHOTO_RE.match(value)
    if m:
        return ("photo", int(m.group(1)))
    return None


def bot_link(bot_username: str | None, param: str) -> str | None:
    return telegram_bot_start_link(client_bot_username=bot_username, start_param=param)


def map_allowed(precision: str | None) -> bool:
    return (precision or "none") in MAP_PRECISIONS


def static_map_url(
    lat: float | None,
    lon: float | None,
    precision: str | None,
    *,
    api_key: str | None,
    width: int = 650,
    height: int = 450,
    zoom: int = 16,
) -> str | None:
    """URL картинки Yandex Static API v1 с пином; ``None`` — карту не показываем."""
    if not api_key or lat is None or lon is None or not map_allowed(precision):
        return None
    width, height = max(1, min(int(width), 650)), max(1, min(int(height), 450))
    query = urlencode(
        {
            "ll": f"{float(lon):.6f},{float(lat):.6f}",
            "z": int(zoom),
            "size": f"{width},{height}",
            "l": "map",
            "pt": f"{float(lon):.6f},{float(lat):.6f},pm2rdm",
            "lang": "ru_RU",
            "apikey": api_key,
        },
        safe=",",
    )
    return f"https://static-maps.yandex.ru/v1?{query}"


def route_url(lat: float | None, lon: float | None, precision: str | None, address: str | None, city: str | None) -> str | None:
    """«Маршрут»: по координате, если точка точная; иначе поиск по тексту адреса; без адреса — нет кнопки."""
    if map_allowed(precision) and lat is not None and lon is not None:
        return f"https://yandex.ru/maps/?rtext=~{float(lat):.6f},{float(lon):.6f}&rtt=auto"
    addr = (address or "").strip()
    if not addr:
        return None
    query = f"{city or ''} {addr}".strip()
    return f"https://yandex.ru/maps/?text={quote(query)}"
