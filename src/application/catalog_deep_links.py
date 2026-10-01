"""
Ответ бота на диплинк каталога: ``/start arena_<id>`` и ``/start catalog_<city>[_<intent>]``.

Это запасной путь для ``t.me/<bot>?start=…`` — когда у мини-аппа не задано короткое
имя и ``startapp`` недоступен (``place_links.telegram_open_link``). Человек пришёл
с публичной страницы места или из чужого сообщения: он хочет ровно этот экран,
а не приветствие и меню. Поэтому ответ — одна фраза и одна кнопка на этот экран.

Модуль чистый (без aiogram), чтобы ответ проверялся тестом, а не руками в боте.
"""

from __future__ import annotations

import html
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_public_use_cases import get_public_arena_card
from src.application.place_links import parse_catalog_start_param, parse_place_start_param
from src.shared.venue_types import venue_card_cta

_CATALOG_BUTTONS = {
    None: "Открыть каталог",
    "skate": "Где покататься",
    "coach": "Тренеры города",
    "shop": "Магазины и заточка",
    "gym": "Залы ОФП",
}


def is_catalog_deep_link(payload: str | None) -> bool:
    return parse_place_start_param(payload) is not None or parse_catalog_start_param(payload) is not None


async def build_catalog_deep_link_reply(
    session: AsyncSession, payload: str | None, *, webapp_base_url: str
) -> dict[str, Any] | None:
    """``{"text", "button_text", "url"}`` или ``None``, если payload не наш или база не HTTPS.

    Место, которого нет в каталоге, не тупик: отвечаем кнопкой на общий каталог.
    """
    base = (webapp_base_url or "").strip().rstrip("/")
    if not base.lower().startswith("https://"):
        return None

    place_id = parse_place_start_param(payload)
    if place_id is not None:
        card = await get_public_arena_card(session, str(place_id))
        if card is None:
            return {
                "text": "Этого места уже нет в каталоге — но рядом есть другие.",
                "button_text": "Открыть каталог",
                "url": f"{base}/webapp/ice",
            }
        name = html.escape(str(card.get("name") or ""))
        noun = html.escape(str(card.get("venue_noun") or ""))
        return {
            "text": f"{noun}: <b>{name}</b>\nРасписание, цены и как добраться — по кнопке ниже.",
            "button_text": venue_card_cta(card.get("venue_type")),
            "url": f"{base}/webapp/arena?" + urlencode({"ref": str(place_id)}),
        }

    target = parse_catalog_start_param(payload)
    if target is None:
        return None
    city_id, intent = target
    row = (
        await session.execute(text("SELECT name FROM cities WHERE id = :id AND is_active"), {"id": int(city_id)})
    ).first()
    params: dict[str, str] = {}
    if row is not None:
        params["city_id"] = str(int(city_id))
    if intent in ("shop", "gym"):
        params["venue"] = intent
    elif intent:
        params["intent"] = intent
    city_name = html.escape(str(row[0])) if row is not None else ""
    head = f"Каталог: <b>{city_name}</b>" if city_name else "Каталог Glide"
    return {
        "text": f"{head}\nКатки, тренеры, залы и магазины — в одном поиске.",
        "button_text": _CATALOG_BUTTONS.get(intent, "Открыть каталог"),
        "url": f"{base}/webapp/ice" + (("?" + urlencode(params)) if params else ""),
    }
