"""TASK-422: текстовые блоки хаба /c/minsk — расписание, цены, ответы — из данных БД.

Только города из ``SEO_RICH_HUB_CITIES``: у регионов страница ранжируется как есть и не меняется.
Принцип PDEC-030: нет данных — нет строки. Один запрос на хаб (сеансы ближайших восьми дней),
дальше всё считается в памяти. Разметка — готовые классы style-b, без data-nosnippet.
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
from src.shared.public_display import format_clock, format_public_name

# Город входит в список по слагу хаба (city_slug). Регионы сюда не добавляем без решения.
SEO_RICH_HUB_CITIES: frozenset[str] = frozenset({"minsk"})

SEO_DAYS = 8  # сегодня + неделя вперёд: хватает на «следующий день с сеансами» и на цены
MAX_TIMES = 14  # сеансов в строке расписания; остальное — «и ещё N»

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


def _money(minor: int, varies: bool, currency: str) -> str:
    out = format_price_minor(minor, currency)
    return f"от {out}" if varies else out


def _rink_index(places: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    return {int(p["id"]): p for p in places}


def build_seo_model(
    rows: Sequence[Mapping[str, Any]], places: Sequence[Mapping[str, Any]], *, today: date
) -> dict[str, Any] | None:
    """Модель блоков. ``None`` — массовых сеансов нет, блоков тоже."""
    index = _rink_index(places)
    skate = [r for r in rows if not _is_ohm(r) and int(r["arena_id"]) in index]
    ohm = [r for r in rows if _is_ohm(r) and int(r["arena_id"]) in index]
    if not skate:
        return None

    days = sorted({r["local_date"] for r in skate})[:2]
    day_blocks = []
    for day in days:
        by_arena: dict[int, list[Mapping[str, Any]]] = {}
        for r in skate:
            if r["local_date"] == day:
                by_arena.setdefault(int(r["arena_id"]), []).append(r)
        rinks = []
        for aid, items in by_arena.items():
            times = sorted({format_clock(str(r["starts_at_local"])) for r in items}, key=_clock_key)
            rinks.append({"arena_id": aid, "times": times, "floors": price_floors(items), "n": len(items)})
        rinks.sort(key=lambda x: (-x["n"], str(index[x["arena_id"]]["name"]).casefold()))
        day_blocks.append({"date": day, "rinks": rinks, "total": sum(x["n"] for x in rinks)})

    prices = []
    by_arena_all: dict[int, list[Mapping[str, Any]]] = {}
    for r in skate:
        by_arena_all.setdefault(int(r["arena_id"]), []).append(r)
    for aid, items in by_arena_all.items():
        prices.append({"arena_id": aid, "floors": price_floors(items), "n": len(items)})
    # Сначала дешевле (вопрос «сколько стоит»); без цены — в конце; дальше больше сеансов, по названию.
    prices.sort(
        key=lambda x: (
            x["floors"].get("adult") is None,
            x["floors"]["adult"][0] if x["floors"].get("adult") else 0,
            -x["n"],
            str(index[x["arena_id"]]["name"]).casefold(),
        )
    )
    currency = Counter(str(r.get("currency_code") or "BYN") for r in skate).most_common(1)[0][0]
    durations = [m for m in (_minutes(r) for r in skate) if m]
    ohm_arenas: dict[int, int] = {}
    for r in ohm:
        ohm_arenas[int(r["arena_id"])] = ohm_arenas.get(int(r["arena_id"]), 0) + 1
    return {
        "days": day_blocks,
        "prices": prices,
        "currency": currency,
        "durations": durations,
        "ohm_arenas": ohm_arenas,
        "today": today,
    }


def _clock_key(label: str) -> tuple[int, int]:
    h, _, m = label.partition(":")
    return int(h), int(m or 0)


# ── Разметка ───────────────────────────────────────────────────────────────


def _esc(value: Any) -> str:
    from src.application.city_hub_page import _esc as esc

    return esc(value)


def _link(view: Mapping[str, Any], place: Mapping[str, Any]) -> str:
    label = _esc(format_public_name(str(place["name"])))
    if not place.get("slug"):
        return label
    href = place_path(city_name=str(view["city"]["name"]), slug=str(place["slug"]))
    title = _esc(f"Расписание и цены: {format_public_name(str(place['name']))}")
    return f'<a href="{_esc(href)}" title="{title}">{label}</a>'


def _day_title(day: date, today: date) -> str:
    from src.application.city_hub_page import _MONTHS_GEN, _WEEKDAYS_FULL

    rel = {today: "Сегодня", today + timedelta(days=1): "Завтра"}.get(day)
    base = f"{_WEEKDAYS_FULL[day.weekday()]}, {day.day} {_MONTHS_GEN[day.month - 1]}"
    return f"{rel}, {base}" if rel else base[:1].upper() + base[1:]


def _day_phrase(day: date, today: date) -> str:
    from src.application.city_hub_page import _WEEKDAY_ACC

    if day == today:
        return "сегодня"
    if day == today + timedelta(days=1):
        return "завтра"
    return _WEEKDAY_ACC[day.weekday()]


def _schedule_html(view: Mapping[str, Any], model: Mapping[str, Any], index: Mapping[int, Mapping[str, Any]]) -> str:
    where = city_locative(str(view["city"]["name"]))
    cur = str(model["currency"])
    parts = []
    for block in model["days"]:
        items = []
        for r in block["rinks"]:
            times = r["times"]
            shown = ", ".join(times[:MAX_TIMES])
            if len(times) > MAX_TIMES:
                shown += f" и ещё {len(times) - MAX_TIMES}"
            bits = []
            adult, child = r["floors"].get("adult"), r["floors"].get("child")
            if adult:
                bits.append(f"взрослый {_money(adult[0], adult[1], cur)}")
            if child:
                bits.append(f"детский {_money(child[0], child[1], cur)}")
            price = f'<span class="b-seo__price">{_esc(" · ".join(bits))}</span>' if bits else ""
            items.append(
                f'<li class="b-seo__row"><b>{_link(view, index[r["arena_id"]])}</b>'
                f'<span class="b-seo__times">{_esc(shown)}</span>{price}</li>'
            )
        n = block["total"]
        head = f"{_day_title(block['date'], model['today'])} · {n} {plural_ru(n, 'сеанс', 'сеанса', 'сеансов')}"
        parts.append(f'<h3 class="b-seo__h3">{_esc(head)}</h3><ul class="b-seo__list">{"".join(items)}</ul>')
    title = f"Расписание массового катания в {where} по каткам"
    return _section(title, "".join(parts))


def _prices_html(view: Mapping[str, Any], model: Mapping[str, Any], index: Mapping[int, Mapping[str, Any]]) -> str:
    where = city_locative(str(view["city"]["name"]))
    cur = str(model["currency"])
    ask = '<td class="b-ptable__ask">уточняйте у катка</td>'
    rows = []
    for p in model["prices"]:
        place = index[p["arena_id"]]
        cells = []
        for key in ("adult", "child", "rental"):
            val = p["floors"].get(key)
            cells.append(f"<td>{_esc(_money(val[0], val[1], cur))}</td>" if val else ask)
        addr = str(place.get("address") or "").strip()
        sub = f'<small class="b-seo__addr">{_esc(addr)}</small>' if addr else ""
        rows.append(f"<tr><td>{_link(view, place)}{sub}</td>{''.join(cells)}</tr>")
    head = "<tr><th>Каток</th><th>Взрослый</th><th>Детский</th><th>Прокат</th></tr>"
    note = (
        '<p class="b-more-lead">Цены — минимальные из ближайших сеансов, «от» — если на разные сеансы они разные. '
        "Сначала дешевле.</p>"
    )
    table = f'<div class="b-seo__scroll"><table class="b-ptable"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'
    return _section(f"Сколько стоит покататься в {where}", table + note)


def _faq_items(
    view: Mapping[str, Any], model: Mapping[str, Any], index: Mapping[int, Mapping[str, Any]]
) -> list[tuple[str, str]]:
    from src.application.city_hub_page import _list_href

    where = city_locative(str(view["city"]["name"]))
    cur = str(model["currency"])
    today = model["today"]
    out: list[tuple[str, str]] = []

    durations = model["durations"]
    if durations:
        common = Counter(durations).most_common(1)[0][0]
        lo, hi = min(durations), max(durations)
        ans = f"Чаще всего — {common} {plural_ru(common, 'минута', 'минуты', 'минут')}."
        if lo != hi:
            ans += f" Бывают сеансы от {lo} до {hi} минут: длительность зависит от катка."
        out.append((f"Сколько длится сеанс массового катания в {where}?", _esc(ans)))

    priced = [p for p in model["prices"] if p["floors"].get("adult")]
    if priced:
        cheap, dear = priced[0], priced[-1]
        lo, hi = cheap["floors"]["adult"], dear["floors"]["adult"]
        if len(priced) > 1 and lo[0] != hi[0]:
            ans = (
                f"Взрослый билет — от {format_price_minor(lo[0], cur)} (дешевле всего — "
                f"{_link(view, index[cheap['arena_id']])}) до {format_price_minor(hi[0], cur)} "
                f"({_link(view, index[dear['arena_id']])}), в зависимости от катка."
            )
        else:
            ans = f"Взрослый билет — {_money(lo[0], lo[1], cur)}."
        kids = [p["floors"]["child"][0] for p in priced if p["floors"].get("child")]
        if kids:
            ans += f" Детский — от {format_price_minor(min(kids), cur)}."
        ans += " Сравнение по каткам — в таблице выше."
        out.append((f"Сколько стоит массовое катание в {where}?", ans))

    rentals = [p for p in model["prices"] if p["floors"].get("rental")]
    if rentals:
        rentals.sort(key=lambda p: (p["floors"]["rental"][0], str(index[p["arena_id"]]["name"]).casefold()))
        listed = "; ".join(
            f"{_link(view, index[p['arena_id']])} — {_money(*p['floors']['rental'], cur)}" for p in rentals
        )
        out.append((f"Где в {where} взять коньки напрокат?", f"Цена проката указана у катков: {listed}."))

    ohm = model["ohm_arenas"]
    if ohm:
        names = ", ".join(
            _link(view, index[a]) for a in sorted(ohm, key=lambda a: (-ohm[a], str(index[a]["name"]).casefold()))
        )
        out.append(
            (
                f"Где в {where} проходят открытые тренировки с клюшкой (ОХМ)?",
                f"В ближайшие дни они есть на катках: {names}. Время и цены — на страницах катков.",
            )
        )

    weekend = int((view.get("skate_counts") or {}).get("weekend") or 0)
    weekend_rinks = int((view.get("skate_window_arena_counts") or {}).get("weekend") or 0)
    if weekend:
        href = _esc(_list_href(str(view["slug"]), w="weekend"))
        ans = (
            f"В выходные в {where} {weekend} {plural_ru(weekend, 'сеанс', 'сеанса', 'сеансов')}"
            f" на {weekend_rinks} {plural_ru(weekend_rinks, 'катке', 'катках', 'катках')}. "
            f'<a href="{href}">Расписание на выходные по каткам</a>.'
        )
        out.append(("Как узнать расписание на выходные?", ans))

    first = model["days"][0]
    top_n = max(r["n"] for r in first["rinks"])
    top = [r for r in first["rinks"] if r["n"] == top_n]
    if len(first["rinks"]) > 1:
        names = ", ".join(_link(view, index[r["arena_id"]]) for r in top)
        word = plural_ru(top_n, "сеанс", "сеанса", "сеансов")
        out.append(
            (
                f"Где {_day_phrase(first['date'], today)} больше всего сеансов?",
                f"Больше всего — на {'катке' if len(top) == 1 else 'катках'} {names}: {top_n} {word}.",
            )
        )
    return out[:6]


def _faq_html(view: Mapping[str, Any], model: Mapping[str, Any], index: Mapping[int, Mapping[str, Any]]) -> str:
    items = _faq_items(view, model, index)
    if not items:
        return ""
    where = city_locative(str(view["city"]["name"]))
    body = "".join(f'<h3 class="b-seo__h3">{_esc(q)}</h3><p class="b-text b-seo__a">{a}</p>' for q, a in items)
    return _section(f"Частые вопросы про катание в {where}", body)


def _section(title: str, body: str) -> str:
    from src.application.style_b import section

    return section(title, body, klass="b-seo")


def seo_blocks_html(view: Mapping[str, Any]) -> str:
    """Три блока подряд; пусто, если модели нет (город не в списке или нет сеансов)."""
    model = view.get("seo_text")
    if not isinstance(model, Mapping) or not city_locative(str(view["city"]["name"])):
        return ""
    index = _rink_index(view.get("places") or [])
    return _schedule_html(view, model, index) + _prices_html(view, model, index) + _faq_html(view, model, index)
