"""TASK-425: свёрнутая карточка «Частые вопросы» хаба /c/minsk и ленты по каткам — из данных БД.

Только города из ``SEO_RICH_HUB_CITIES``: у регионов страница ранжируется как есть и не меняется.
Принцип PDEC-030: нет данных — нет вопроса. Один запрос на хаб (сеансы ближайших восьми дней),
дальше всё считается в памяти. Разметка — готовые классы style-b (details.b-details).
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_public_use_cases import _NOT_HOCKEY_CENTER_SQL
from src.application.ice_city_day import format_price_minor, plural_ru
from src.application.place_links import place_path
from src.application.place_visit_blocks import price_floors
from src.shared.city_locative import city_locative
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
from src.shared.public_display import format_public_name

# Город входит в список по слагу хаба (city_slug). Регионы сюда не добавляем без решения.
SEO_RICH_HUB_CITIES: frozenset[str] = frozenset({"minsk"})

SEO_DAYS = 8  # сегодня + неделя вперёд: хватает на «следующий день с сеансами» и на цены

_SEO_SESSIONS_SQL = text(
    f"""
    SELECT s.arena_id, s.kind, s.local_date, s.starts_at_local, s.ends_at_local,
           s.price_adult_minor, s.price_child_minor, s.price_rental_minor, s.currency_code
    FROM ice_sessions s
    JOIN arenas a ON a.id = s.arena_id
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    WHERE a.city_id = :city_id
      AND {PUBLIC_ARENA_VISIBLE_SQL}
      AND {_NOT_HOCKEY_CENTER_SQL}
      AND s.status = :st
      AND s.kind IN ('public_skate', 'open_ice', 'hockey_practice')
      AND s.starts_at_utc > :now
      AND (s.valid_until IS NULL OR s.valid_until >= :now)
      AND s.local_date >= :d_from AND s.local_date < :d_to
    ORDER BY s.local_date, s.starts_at_local, s.id
    """
)


def is_seo_rich(slug: str) -> bool:
    return slug in SEO_RICH_HUB_CITIES


async def load_seo_sessions(
    session: AsyncSession, *, city_id: int, now: datetime, today: date, status: str
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            _SEO_SESSIONS_SQL,
            {
                "city_id": city_id,
                "now": now,
                "st": status,
                "d_from": today,
                "d_to": today + timedelta(days=SEO_DAYS),
                **public_scope_params(),
            },
        )
    ).mappings()
    return [dict(r) for r in rows]


def _is_ohm(row: Mapping[str, Any]) -> bool:
    return row.get("kind") == "hockey_practice"


def _minutes(row: Mapping[str, Any]) -> int | None:
    start, end = row.get("starts_at_local"), row.get("ends_at_local")
    if not isinstance(start, time) or not isinstance(end, time):
        return None
    diff = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return diff if 0 < diff <= 360 else None


def build_seo_model(rows: Sequence[Mapping[str, Any]], places: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Модель ответов. ``None`` — массовых сеансов нет, карточки тоже."""
    index = {int(p["id"]): p for p in places}
    skate = [r for r in rows if not _is_ohm(r) and int(r["arena_id"]) in index]
    if not skate:
        return None
    by_arena: dict[int, list[Mapping[str, Any]]] = {}
    for r in skate:
        by_arena.setdefault(int(r["arena_id"]), []).append(r)
    prices = [{"arena_id": aid, "floors": price_floors(items)} for aid, items in by_arena.items()]
    currency = Counter(str(r.get("currency_code") or "BYN") for r in skate).most_common(1)[0][0]
    durations = [m for m in (_minutes(r) for r in skate) if m]
    return {"prices": prices, "currency": currency, "durations": durations, "index": index}


def _esc(value: Any) -> str:
    from src.application.city_hub_page import _esc as esc

    return esc(value)


def _link(view: Mapping[str, Any], place: Mapping[str, Any]) -> str:
    label = _esc(format_public_name(str(place["name"])))
    if not place.get("slug"):
        return label
    href = place_path(city_name=str(view["city"]["name"]), slug=str(place["slug"]))
    return f'<a href="{_esc(href)}">{label}</a>'


def _range(values: Sequence[int], cur: str) -> str:
    lo, hi = min(values), max(values)
    return (
        format_price_minor(lo, cur)
        if lo == hi
        else f"от {format_price_minor(lo, cur)} до {format_price_minor(hi, cur)}"
    )


def faq_items(view: Mapping[str, Any], model: Mapping[str, Any]) -> list[tuple[str, str]]:
    """До трёх вопросов; ответ без даты и без «сегодня»/«завтра». Пустой ответ — вопроса нет."""
    where = city_locative(str(view["city"]["name"]))
    cur = str(model["currency"])
    index = model["index"]
    out: list[tuple[str, str]] = []

    durations = model["durations"]
    if durations:
        common = Counter(durations).most_common(1)[0][0]
        lo, hi = min(durations), max(durations)
        ans = f"Чаще всего — {common} {plural_ru(common, 'минута', 'минуты', 'минут')}."
        if lo != hi:
            ans += f" Бывают сеансы от {lo} до {hi} минут: зависит от катка."
        out.append((f"Сколько длится сеанс массового катания в {where}?", _esc(ans)))

    adults = [p["floors"]["adult"][0] for p in model["prices"] if p["floors"].get("adult")]
    if adults:
        ans = f"Взрослый билет — {_range(adults, cur)}, в зависимости от катка."
        kids = [p["floors"]["child"][0] for p in model["prices"] if p["floors"].get("child")]
        if kids:
            ans += f" Детский — {_range(kids, cur)}."
        out.append((f"Сколько стоит массовое катание в {where}?", _esc(ans)))

    rentals = [p for p in model["prices"] if p["floors"].get("rental")]
    if rentals:
        rentals.sort(key=lambda p: (p["floors"]["rental"][0], str(index[p["arena_id"]]["name"]).casefold()))
        listed = "; ".join(
            f"{_link(view, index[p['arena_id']])} — {format_price_minor(p['floors']['rental'][0], cur)}"
            for p in rentals
        )
        out.append((f"Где в {where} взять коньки напрокат?", f"Цена проката указана у катков: {listed}."))
    return out


def faq_card_html(view: Mapping[str, Any]) -> str:
    """Одна свёрнутая карточка в стиле «Все места города»; пусто, если нет данных ни на один вопрос."""
    from src.application.catalog_icons import icon_svg

    model = view.get("seo_text")
    if not isinstance(model, Mapping) or not city_locative(str(view["city"]["name"])):
        return ""
    items = faq_items(view, model)
    if not items:
        return ""
    body = "".join(f"<p><b>{_esc(q)}</b><br>{a}</p>" for q, a in items)
    return (
        '<section class="b-sec"><details class="b-details">'
        f"<summary>Частые вопросы · {len(items)}{icon_svg('down')}</summary>"
        f'<div class="b-details__body">{body}</div></details></section>'
    )
