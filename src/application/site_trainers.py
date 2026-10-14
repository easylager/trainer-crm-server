"""Тренеры на сайте (TASK-265): те же люди и та же строка, что в Mini App на карточке катка.

Данные — ``list_active_trainers_for_client`` (только опубликованные в каталоге, как у
``/api/public/arenas/{ref}/trainers``). Запись — в Telegram на карточку тренера
(``trainer_<id>[_a_<arena>]``), а не на каток: человек видит, к кому идёт.
"""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_city_day import format_price_minor

#: Сколько лиц показываем на странице города; остальные — ссылкой «Все тренеры».
CITY_TRAINERS_SHOWN = 6


def trainer_name(trainer: Mapping[str, Any]) -> str:
    profile = trainer.get("profile") or {}
    name = " ".join(str(profile.get(k) or "").strip() for k in ("first_name", "last_name")).strip()
    return name or "Тренер"


def trainer_initial(name: str) -> str:
    """Первая буква имени для кружка без фото; эмодзи и знаки пропускаем, как в Mini App."""
    for ch in name:
        if ch.isalpha():
            return ch.upper()
    return "Т"


def trainer_photo_url(trainer: Mapping[str, Any]) -> str | None:
    from src.application.style_b import b_photo_url

    photos = trainer.get("photos") or []
    if not photos:
        return None
    first = photos[0] or {}
    return b_photo_url(first.get("file_key_list") or first.get("file_key"))


def trainer_line(trainer: Mapping[str, Any]) -> str:
    """«Обучение катанию „с нуля“ · от 41,87 BYN за занятие»: первая услуга и самое дешёвое занятие.

    Цена — ``min_session_price_cents`` из ``trainer_min_price`` (абонементы, тарифы, групповые).
    """
    services = list(trainer.get("services") or [])
    names = [str(s.get("service_name") or s.get("name") or "").strip() for s in services]
    names = [n for n in names if n]
    bits = names[:1]
    cents = trainer.get("min_session_price_cents")
    if cents:
        price = format_price_minor(int(cents), str(trainer.get("min_session_price_currency") or "BYN"))
        bits.append("от\u00a0" + price.replace(" ", "\u00a0") + " за\u00a0занятие")
    return " · ".join(bits)


def site_trainer_view(trainer: Mapping[str, Any], *, can_book: bool) -> dict[str, Any]:
    name = trainer_name(trainer)
    return {
        "id": int(trainer["id"]),
        "name": name,
        "initial": trainer_initial(name),
        "photo_url": trainer_photo_url(trainer),
        "line": trainer_line(trainer),
        "can_book": bool(can_book),
    }


async def load_site_trainers(
    session: AsyncSession,
    *,
    arena_id: int | None = None,
    city_id: int | None = None,
    limit: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """(тренеры для строки, сколько всего). Порядок — как в каталоге Mini App."""
    from src.application.subscription_tier_use_cases import get_trainer_booking_availability
    from src.application.trainer_use_cases import list_active_trainers_for_client
    from src.application.trainer_min_price import enrich_min_session_price
    from src.shared.public_trainer_payload import sanitize_trainer_for_public_catalog

    items, total = await list_active_trainers_for_client(
        session, limit=limit, offset=0, arena_id=arena_id, city_id=city_id
    )
    bodies = [sanitize_trainer_for_public_catalog(raw) for raw in items]
    await enrich_min_session_price(session, bodies)
    out: list[dict[str, Any]] = []
    for body in bodies:
        availability = await get_trainer_booking_availability(session, int(body["id"]))
        out.append(site_trainer_view(body, can_book=bool(availability.get("can_book"))))
    return out, int(total)
