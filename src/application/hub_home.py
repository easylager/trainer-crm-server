"""Главная клиента в стиле страницы города (TASK-303, PDEC-023).

Два куска для `/client/hub/bootstrap`:
- `city_block` — шапка, «Ближайший лёд» и «Что нужно» из того же вида, что рисует glideclub.by/c/{город},
  но со ссылками на экраны Mini App;
- `now_slot` — одна карточка «сейчас» по приоритету: моя запись сегодня → итог «Кто кого» →
  матч скоро → ближайший лёд.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, time
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from src.application.city_hub_page import _WINDOW_KEYS, _b_counts_line, _b_today_kicker, _price_bits, _session_when
from src.application.ice_city_day import plural_ru
from src.application.style_b import b_photo_url
from src.shared.public_display import format_public_name

UPCOMING_LIMIT = 3
_RINK_TYPES = ("ice", "outdoor")
# Записи, которые уже не про «сегодня иду на лёд».
_DEAD_BOOKING = frozenset({"cancelled", "canceled", "declined", "rejected", "no_show", "completed", "expired"})


def _ice_href(city_id: int, **params: str) -> str:
    query = {"city_id": str(city_id), **{k: v for k, v in params.items() if v}}
    return "ice?" + urlencode(query)


def _place_href(arena_id: Any, session_id: Any = None) -> str | None:
    if arena_id is None:
        return None
    href = f"arena?ref={int(arena_id)}"
    if session_id:
        href += f"&s={int(session_id)}"
    return href


def _photo(place: Mapping[str, Any]) -> dict[str, str | None]:
    variants = place.get("photo_variants")
    variants = variants if isinstance(variants, Mapping) else {}
    return {
        "thumb": b_photo_url(variants.get("thumb")),
        "card": b_photo_url(variants.get("card")),
        "hero": b_photo_url(variants.get("hero") or variants.get("card")),
    }


def _windows(counts: Mapping[str, int], *, city_id: int, hot: str | None, **base: str) -> list[dict[str, Any]]:
    labels = {"today": "Сегодня", "tomorrow": "Завтра", "weekend": "В выходные"}
    out = []
    for key in _WINDOW_KEYS:
        n = int(counts.get(key) or 0)
        out.append(
            {
                "key": key,
                "label": labels[key],
                "count": n,
                "hot": key == hot,
                "href": _ice_href(city_id, when=key, **base) if n else None,
            }
        )
    return out


def _needs(view: Mapping[str, Any], city_id: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rinks = int(view.get("rink_count") or 0)
    if rinks:
        skate = view["skate_counts"]
        line = f"{rinks} {plural_ru(rinks, 'каток', 'катка', 'катков')}"
        has_times = bool(int(skate.get("all") or 0))
        rows.append(
            {
                "key": "skate",
                "title": "Покататься",
                "line": line if has_times else line + " · расписания пока нет",
                "href": _ice_href(city_id, intent="skate"),
                "windows": _windows(skate, city_id=city_id, hot=view.get("hot_skate"), intent="skate")
                if has_times
                else [],
            }
        )
    ohm = view["ohm_counts"]
    if int(ohm.get("all") or 0):
        n = int(view.get("ohm_arena_count") or 0)
        bits = [f"ОХМ на {n} {plural_ru(n, 'катке', 'катках', 'катках')}"]
        nxt = view.get("next_ohm")
        if isinstance(nxt, Mapping):
            hhmm, day = _session_when(nxt, today=view["today"])
            bits.append(f"ближайший в {hhmm}" if day == "сегодня" else f"ближайший {day} в {hhmm}")
        rows.append(
            {
                "key": "ohm",
                "title": "С клюшкой",
                "line": " · ".join(bits),
                "href": _ice_href(city_id, intent="ohm"),
                "windows": _windows(ohm, city_id=city_id, hot=view.get("hot_ohm"), intent="ohm"),
            }
        )
    services = int(view.get("service_count") or 0)
    if services:
        k = len(view.get("service_open") or [])
        line = f"{services} {plural_ru(services, 'место', 'места', 'мест')}"
        rows.append(
            {
                "key": "service",
                "title": "Заточка",
                "line": line + (f" · {k} открыт{'о' if k == 1 else 'ы'} сейчас" if k else ""),
                "href": _ice_href(city_id, intent="service"),
                "windows": [],
            }
        )
    shops = int(view.get("shop_count") or 0)
    if shops:
        k = len(view.get("shops_open") or [])
        rows.append(
            {
                "key": "shop",
                "title": "Магазины",
                "line": f"{shops} {plural_ru(shops, 'магазин', 'магазина', 'магазинов')}"
                + (f" · {k} {plural_ru(k, 'открыт', 'открыты', 'открыты')} сейчас" if k else ""),
                "href": _ice_href(city_id, venue="shop"),
                "windows": [],
            }
        )
    trainers = int(view.get("trainer_count") or 0)
    if trainers:
        rows.append(
            {
                "key": "coach",
                "title": "Тренеры",
                "line": f"{trainers} {plural_ru(trainers, 'тренер', 'тренера', 'тренеров')}",
                "href": f"catalog?city_id={city_id}",
                "windows": [],
            }
        )
    return rows


InviteLink = Callable[[int, int | None], str | None]


def _upcoming(view: Mapping[str, Any], invite_link: InviteLink | None) -> list[dict[str, Any]]:
    by_slug = {str(p.get("slug") or ""): p for p in view.get("places") or []}
    out = []
    for card in list(view.get("upcoming") or [])[:UPCOMING_LIMIT]:
        hhmm, day = _session_when(card, today=view["today"])
        place = by_slug.get(str(card.get("arena_slug") or "").strip()) or {}
        out.append(
            {
                "time": hhmm,
                "day": day,
                "badge": hhmm if day == "сегодня" else f"{day} {hhmm}",
                "place": format_public_name(str(card.get("arena_name") or "")),
                "price": _price_bits(card) or day,
                "arena_id": place.get("id"),
                "session_id": card.get("session_id"),
                "minutes_until": card.get("minutes_until"),
                "href": _place_href(place.get("id"), card.get("session_id")),
                "photo": _photo(place),
                # «Позвать»: ссылка в Mini App прямо на этот сеанс (arena_<id>_s_<сеанс>).
                "invite_url": invite_link(int(place["id"]), card.get("session_id"))
                if invite_link and place.get("id") is not None
                else None,
            }
        )
    return out


def city_block(view: Mapping[str, Any], *, invite_link: InviteLink | None = None) -> dict[str, Any]:
    """Всё, что главная берёт со страницы города, — готовыми строками и ссылками Mini App."""
    city = view["city"]
    city_id = int(city["id"])
    rinks = [p for p in view.get("places") or [] if str(p.get("venue_type") or "ice") in _RINK_TYPES]
    # Как на сайте: крытый каток с самым крупным кадром (Минск-Арена), не первый по алфавиту.
    # Дальше — запасные: у части катков файл в хранилище отсутствует, и клиент берёт следующий.
    with_photo = [p for p in rinks if p.get("photo_hero")]
    with_photo.sort(key=lambda p: (str(p.get("venue_type") or "") != "ice", -int(p.get("photo_width") or 0)))
    with_photo = with_photo[:4]  # клиент делает не больше 4 попыток (HERO_MAX_TRIES)
    today_n = int(view["skate_counts"].get("today") or 0)
    return {
        "id": city_id,
        "name": format_public_name(str(city["name"])),
        "kicker": _b_today_kicker(view),
        "counts_line": _b_counts_line(view),
        "hero_photo": _photo(with_photo[0]) if with_photo else None,
        "hero_photos": [_photo(p) for p in with_photo],
        "upcoming": _upcoming(view, invite_link),
        "upcoming_href": _ice_href(city_id, intent="skate", when="today" if today_n else ""),
        "upcoming_more": "Весь день" if today_n else "Все",
        "needs": _needs(view, city_id),
    }


def _booking_today(bookings: Mapping[str, Any] | None, *, local_now: datetime) -> dict[str, Any] | None:
    today = local_now.date().isoformat()
    for day in (bookings or {}).get("days") or []:
        if str(day.get("date")) != today:
            continue
        for b in day.get("bookings") or []:
            if str(b.get("status") or "").lower() in _DEAD_BOOKING:
                continue
            try:
                end = time.fromisoformat(str(b.get("end_time") or "23:59"))
            except ValueError:
                end = time(23, 59)
            if end <= local_now.time().replace(tzinfo=None):
                continue
            return dict(b)
    return None


def _minutes_until(hhmm: str, *, local_now: datetime) -> int | None:
    try:
        start = time.fromisoformat(hhmm)
    except ValueError:
        return None
    delta = datetime.combine(local_now.date(), start) - local_now.replace(tzinfo=None)
    return int(delta.total_seconds() // 60)


def _dinamo_card(hockey: Mapping[str, Any] | None) -> dict[str, Any] | None:
    mode = (hockey or {}).get("mode")
    # Итог месяца «Кто кого» (TASK-334) — сутки после финала, пока не открыли.
    if mode == "race_result" and (hockey or {}).get("race"):
        return {"kind": "kk_month", "hockey": dict(hockey or {})}
    # live — идущий домашний матч-событие (TASK-304); рисуется той же карточкой, что before.
    if mode in ("result", "before", "live") and (hockey or {}).get("match"):
        return {"kind": "kk_result" if mode == "result" else "kk_before", "hockey": dict(hockey or {})}
    return None


def now_slot(
    *,
    bookings: Mapping[str, Any] | None,
    hockey: Mapping[str, Any] | None,
    upcoming: Sequence[Mapping[str, Any]],
    now: datetime,
    has_city: bool = True,
    tz_name: str = "Europe/Minsk",
    extraliga: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Одна карточка «сейчас». Порядок — как на листе слота в макете (PDEC-023).

    Без города матч не встаёт: новому человеку сначала нужен лёд и выбор города, а не Динамо-Минск.
    Тогда None — главная показывает тизер льда по стране.
    """
    local_now = now.astimezone(ZoneInfo(tz_name))
    booking = _booking_today(bookings, local_now=local_now)
    if booking is not None:
        return {
            "kind": "booking",
            "booking": dict(booking),
            "minutes_until": _minutes_until(str(booking.get("start_time") or ""), local_now=local_now),
        }
    dinamo = _dinamo_card(hockey if has_city else None)
    # Экстралига (TASK-340, экран 11): слот становится лентой — матчи города, Динамо, «все матчи».
    matches = list((extraliga or {}).get("matches") or []) if has_city else []
    if matches:
        items: list[dict[str, Any]] = [dict(m) for m in matches]
        if dinamo is not None:
            items.append(dinamo)
        count = int((extraliga or {}).get("week_count") or 0)
        if count:
            items.append({"kind": "more", "count": count, "href": (extraliga or {}).get("all_href") or "client-matches"})
        return {"kind": "feed", "items": items}
    if dinamo is not None:
        return dinamo
    if upcoming:
        return {"kind": "ice", "session": dict(upcoming[0])}
    return None


__all__ = ["UPCOMING_LIMIT", "city_block", "now_slot"]
