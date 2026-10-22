"""Карточка катка v2 на сайте: блоки поверх модели ``arena_visit_info.visit_view``.

Вся разметка отдаётся сервером: свёрнутое (абонементы, аренда льда, «Ещё N»)
лежит в ``<details>`` и видно поисковику так же, как человеку.
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import Any

from src.application.catalog_icons import PENGUIN_SVG, icon_svg
from src.application.ice_city_day import format_price_minor

_FACT_ICON = {"cup": "cafe"}


def _esc(value: Any) -> str:
    return escape(str(value or ""), quote=True)


def _icon(name: str) -> str:
    return icon_svg(_FACT_ICON.get(name, name)) or icon_svg("info")


def price_floors(slots: list[Mapping[str, Any]]) -> dict[str, tuple[int, bool]]:
    """Минимум недели по взрослому, детскому и прокату: ``{"adult": (minor, varies)}``."""
    seen: dict[str, set[int]] = {"adult": set(), "child": set(), "rental": set()}
    for slot in slots:
        adult = slot.get("price_adult_minor")
        if adult is None:
            adult = slot.get("price_minor")
        for key, value in (("adult", adult), ("child", slot.get("price_child_minor")),
                           ("rental", slot.get("price_rental_minor"))):
            if value is not None:
                seen[key].add(int(value))
    return {k: (min(v), len(v) > 1) for k, v in seen.items() if v}


def prices_html(slots: list[Mapping[str, Any]], vv: Mapping[str, Any], *, currency: str) -> str:
    """Три цены под заголовком: вход, детский, прокат — и итог «с прокатом»."""
    floors = price_floors(slots)
    if not floors:
        return ""

    def money(key: str) -> str:
        minor, varies = floors[key]
        text = format_price_minor(minor, currency)
        return f"от {text}" if varies else text

    age = vv.get("child_age_max")
    sizes = vv.get("sizes") or ""
    cells: list[tuple[str, str, str]] = []
    if "adult" in floors:
        cells.append(("Вход", money("adult"), "свои коньки" if "rental" in floors else "взрослый"))
    if "child" in floors:
        cells.append(("Детский", money("child"), f"до {age} лет" if age else ""))
    if "rental" in floors:
        cells.append(("Прокат", money("rental"), f"размеры {sizes}" if sizes else "коньки"))
    body = "".join(
        f'<div class="b-price"><span class="b-price__k">{_esc(k)}</span>'
        f'<b class="b-price__v">{_esc(v)}</b>'
        + (f'<span class="b-price__s">{_esc(s)}</span>' if s else "")
        + "</div>"
        for k, v, s in cells
    )
    total = ""
    if "adult" in floors and "rental" in floors:
        sum_minor = floors["adult"][0] + floors["rental"][0]
        prefix = "от " if floors["adult"][1] or floors["rental"][1] else ""
        total = f'<p class="b-price-sum">Взрослому с прокатом — {prefix}{_esc(format_price_minor(sum_minor, currency))}.</p>'
    return f'<div class="b-prices b-prices--{len(cells)}">{body}</div>{total}'


def ticket_line_html(vv: Mapping[str, Any]) -> str:
    """Строка «как купить» под ценами. Онлайн-касса — кнопка в шапке, тут только условия."""
    t = vv.get("tickets") or {}
    mode = t.get("mode")
    detail = str(t.get("detail") or "")
    note = str(t.get("note") or "")
    if mode == "box_office":
        tail = " · ".join(x for x in (detail, note.rstrip(".")) if x)
        rest = f" · {_esc(tail)}" if tail else ""
        return (
            f'<p class="b-buyline b-buyline--desk">{icon_svg("ticket")}'
            f"<span><b>Билеты только в кассе</b>{rest}</span></p>"
        )
    if mode == "same_day":
        extra = f" {_esc(detail)}." if detail else ""
        return (
            f'<p class="b-buyline b-buyline--soft">{icon_svg("clock")}'
            f"<span><b>Онлайн продают только в день сеанса.</b> Заранее — в кассе.{extra}</span></p>"
        )
    bits = " · ".join(x for x in (detail, note.rstrip(".")) if x)
    if bits:
        return f'<p class="b-buyline b-buyline--plain">{icon_svg("ticket")}<span>{_esc(bits)}</span></p>'
    return ""


def facts_html(vv: Mapping[str, Any], *, cafe_offer: str = "") -> str:
    from src.application.style_b import section

    facts = list(vv.get("facts") or [])
    if not facts:
        return ""
    visible = int(vv.get("facts_visible") or 4)

    def cell(f: Mapping[str, Any]) -> str:
        badge = ""
        tag, href = "div", ""
        if f.get("key") == "cafe" and cafe_offer:
            badge = f'<span class="b-fact__badge">{_esc(cafe_offer)}</span>'
            tag, href = "a", ' href="#partners"'
        note = f'<span class="b-fact__n">{_esc(f.get("note"))}</span>' if f.get("note") else ""
        return (
            f'<{tag} class="b-fact"{href}><span class="b-fact__ic">{_icon(str(f.get("icon") or "info"))}</span>'
            f'<b class="b-fact__t">{_esc(f.get("title"))}{badge}</b>{note}</{tag}>'
        )

    head = "".join(cell(f) for f in facts[:visible])
    body = f'<div class="b-facts">{head}</div>'
    rest = facts[visible:]
    if rest:
        body += (
            f'<details class="b-facts-more"><summary>Ещё {len(rest)}</summary>'
            f'<div class="b-facts">{"".join(cell(f) for f in rest)}</div></details>'
        )
    return section("Что важно знать", body, klass="b-sec--place", sec_id="facts")


def services_html(vv: Mapping[str, Any], *, title: str = "Прокат и услуги") -> str:
    from src.application.style_b import section

    services = vv.get("services") or {}
    rows = list(services.get("rows") or [])
    if not rows:
        return ""
    items: list[str] = []
    for row in rows:
        if row.get("icon") == "penguin":
            media = f'<span class="b-svc__pic">{PENGUIN_SVG}</span>'
        else:
            media = f'<span class="b-svc__ic">{_icon(str(row.get("icon") or "info"))}</span>'
        note = f'<span class="b-svc__n">{_esc(row.get("note"))}</span>' if row.get("note") else ""
        price = f'<span class="b-svc__p">{_esc(row.get("price"))}</span>' if row.get("price") else ""
        items.append(
            f'<div class="b-svc">{media}<span class="b-svc__b"><b>{_esc(row.get("title"))}</b>{note}</span>{price}</div>'
        )
    notes = "".join(f'<p class="b-buyline b-buyline--soft">{icon_svg("info")}<span>{_esc(n)}</span></p>'
                    for n in services.get("notes") or [])
    aside = '<span class="b-aside">в кассе</span>' if any(r.get("price") for r in rows) else ""
    return section(title, f'<div class="b-svcs">{"".join(items)}</div>{notes}', aside_html=aside,
                   klass="b-sec--place", sec_id="services")


def school_table_html(school: Mapping[str, Any]) -> str:
    rows = list(school.get("rows") or [])
    has_child = any(r.get("child") for r in rows)
    has_adult = any(r.get("adult") for r in rows)
    head = "<th></th>" + ("<th>Детям</th>" if has_child else "") + ("<th>Взрослым</th>" if has_adult else "")
    body = "".join(
        f"<tr><td>{_esc(r.get('label'))}</td>"
        + (f"<td>{_esc(r.get('child') or '—')}</td>" if has_child else "")
        + (f"<td>{_esc(r.get('adult') or '—')}</td>" if has_adult else "")
        + "</tr>"
        for r in rows
    )
    contact = ""
    phone = str(school.get("phone") or "").strip()
    if phone:
        digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
        who = f" · {_esc(school.get('contact'))}" if school.get("contact") else ""
        contact = f'<a class="b-more-call" href="tel:{_esc(digits)}">{icon_svg("phone")}Записаться: {_esc(phone)}{who}</a>'
    return f'<table class="b-ptable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{contact}'


def _passes_table_html(passes: Mapping[str, Any]) -> str:
    cols = list(passes.get("columns") or [])
    head = "<th></th>" + "".join(f"<th>{_esc(c)}</th>" for c in cols)
    body = "".join(
        f"<tr><td>{_esc(r.get('label'))}</td>"
        + "".join(f"<td>{_esc(v or '—')}</td>" for v in (r.get("values") or [])[: len(cols)])
        + "</tr>"
        for r in passes.get("rows") or []
    )
    return f'<table class="b-ptable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _rink_html(rink: Mapping[str, Any], *, tel_href: str) -> str:
    rows = "".join(
        f'<div class="b-rinkrow"><span>{_esc(r.get("label"))}'
        + (f', {int(r["minutes"])} минут' if r.get("minutes") else "")
        + f'</span><b>{_esc(r.get("price"))}</b></div>'
        for r in rink.get("rows") or []
    )
    phone = str(rink.get("phone") or "").strip()
    href = tel_href
    if phone:
        href = "tel:" + "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    call = f'<a class="b-more-call" href="{_esc(href)}">{icon_svg("phone")}Позвонить и забронировать</a>' if href else ""
    lead = "<p class=\"b-more-lead\">Весь каток на вашу компанию: день рождения, хоккей с друзьями, корпоратив.</p>"
    return f"{lead}<div class=\"b-rinkrows\">{rows}</div>{call}"


def more_html(vv: Mapping[str, Any], *, coach_html: str = "", tel_href: str = "") -> str:
    """«Ещё на катке»: редкие сценарии строками, подробности раскрываются на месте."""
    from src.application.style_b import section

    items: list[str] = []
    for m in vv.get("more") or []:
        detail = m.get("detail") or {}
        if m.get("key") == "school":
            inner = school_table_html(detail)
        elif m.get("key") == "passes":
            inner = _passes_table_html(detail)
        else:
            inner = _rink_html(detail, tel_href=tel_href)
        note = f'<span class="b-more-row__n">{_esc(m.get("note"))}</span>' if m.get("note") else ""
        items.append(
            f'<details class="b-more-row" id="more-{_esc(m.get("key"))}"><summary>'
            f'<span class="b-svc__ic">{_icon(str(m.get("icon") or "info"))}</span>'
            f'<span class="b-svc__b"><b>{_esc(m.get("title"))}</b>{note}</span>'
            f'{icon_svg("down")}</summary><div class="b-more-row__body">{inner}</div></details>'
        )
    if not items and not coach_html:
        return ""
    body = f'<div class="b-more-list">{"".join(items)}{coach_html}</div>'
    return section("Ещё на катке", body, klass="b-sec--place", sec_id="more")


def school_in_trainers_html(school: Mapping[str, Any] | None) -> str:
    if not school or not school.get("rows"):
        return ""
    age = f"с {int(school['age_from'])} лет" if school.get("age_from") else ""
    note = f'<span class="b-more-row__n">{_esc(age)}</span>' if age else ""
    return (
        '<details class="b-more-row" id="more-school"><summary>'
        f'<span class="b-svc__ic">{icon_svg("child")}</span>'
        f'<span class="b-svc__b"><b>Школа катка</b>{note}</span>{icon_svg("down")}</summary>'
        f'<div class="b-more-row__body">{school_table_html(school)}</div></details>'
    )


def json_ld_extras(vv: Mapping[str, Any], *, currency: str, slots: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Поля schema.org для катка: удобства, оплата, цены услуг."""
    out: dict[str, Any] = {}
    features = [
        {"@type": "LocationFeatureSpecification", "name": f["title"], "value": True}
        for f in vv.get("facts") or []
        if f.get("key") in ("locker_rooms", "lockers", "cafe", "parking") and not str(f["title"]).endswith("нет")
    ]
    if features:
        out["amenityFeature"] = features
    for f in vv.get("facts") or []:
        if f.get("key") == "payment":
            pay = {"Карта и наличные": "Cash, Credit Card", "Только карта": "Credit Card",
                   "Можно картой": "Credit Card", "Только наличные": "Cash", "Наличными": "Cash"}.get(f["title"])
            if pay:
                out["paymentAccepted"] = pay
    floors = price_floors(slots)
    if floors:
        lo = min(v[0] for v in floors.values())
        hi = max(v[0] for v in floors.values())
        out["priceRange"] = (
            format_price_minor(lo, currency) if lo == hi
            else f"{format_price_minor(lo, currency)}–{format_price_minor(hi, currency)}"
        )
    offers = []
    for row in (vv.get("services") or {}).get("rows") or []:
        if not row.get("price"):
            continue
        offers.append({
            "@type": "Offer",
            "itemOffered": {"@type": "Service", "name": row["title"]},
            "description": row["price"],
        })
    if offers:
        out["hasOfferCatalog"] = {"@type": "OfferCatalog", "name": "Прокат и услуги", "itemListElement": offers}
    return out


def search_bits(vv: Mapping[str, Any], *, currency: str, slots: list[Mapping[str, Any]]) -> list[str]:
    """Факты для meta description: цены входа, услуги, как купить."""
    bits: list[str] = []
    floors = price_floors(slots)
    parts = []
    for key, label in (("adult", "вход"), ("child", "детский"), ("rental", "прокат")):
        if key in floors:
            minor, varies = floors[key]
            parts.append(f"{label} {'от ' if varies else ''}{format_price_minor(minor, currency)}")
    if parts:
        bits.append(", ".join(parts).capitalize())
    names = [str(r["title"]).lower() for r in (vv.get("services") or {}).get("rows") or []
             if r.get("kind") in ("aid", "sharpening", "protection", "helmet")]
    if names:
        bits.append(", ".join(dict.fromkeys(names)).capitalize())
    mode = (vv.get("tickets") or {}).get("mode")
    if mode == "box_office":
        bits.append("Билеты в кассе")
    elif mode == "same_day":
        bits.append("Онлайн-билеты в день сеанса")
    elif mode == "online":
        bits.append("Билеты онлайн")
    return bits
