"""Сайт: «Зимой в <городе>» и страница зимней точки (TASK-343, волна 2).

Вёрстка по холсту «Сайт: матчи и зимний лёд», экраны 6–8. HTML целиком на сервере (поиск видит
список и страницу точки без JS); ``static/share/winter.js`` только сортирует по расстоянию, фильтрует,
рисует карту и отправляет отметки. Логика подписей и сортировки — в ``static/shared/winter-model.js``.

Что страница не делает намеренно:
  * не показывает «открыто сейчас» — часы прошлой зимы всегда подписаны «зимой 2025/26»;
  * не строит карту, расстояние и «Рядом» для неточных точек (``locating``);
  * не кладёт токен отметки в HTML — он приходит из ``no-store`` API, а страница может кэшироваться;
  * не кладёт статус в ``og:description`` — мессенджеры кэшируют превью неделями (O5).
"""
from __future__ import annotations

import html as html_lib
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlparse

from src.application.catalog_icons import icon_svg, rink_motif_svg
from src.application.ice_city_day import city_slug
from src.application.place_links import place_path
from src.application.public_site_footer import render_site_footer_html
from src.application.style_b import (
    COMPONENTS_VERSION,
    STYLE_VERSION,
    TOKENS_VERSION,
    _file_version,
    media_url,
    public_fonts_head_html,
)
from src.shared.city_locative import city_locative
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "winter-page.html"
WINTER_CSS_VERSION = _file_version("static/shared/winter.css")
WINTER_MODEL_VERSION = _file_version("static/shared/winter-model.js")
WINTER_JS_VERSION = _file_version("static/share/winter.js")

NBSP = " "
STATE_LABEL = {"flooded": "Залит", "waiting": "Ждём заливку", "stale": "Давно не отмечали", "closed": "Закрыт"}
STATE_TONE = {"flooded": "ok", "waiting": "wait", "stale": "quiet", "closed": "quiet"}
STATE_ICON = {"flooded": "check", "waiting": "clock", "stale": "clock", "closed": "clock"}
CROWD_LABEL = {"few": "Мало людей", "normal": "Людей нормально", "many": "Много людей"}
HOCKEY_LABEL = {"playing": "Идёт хоккей", "free": "Хоккея нет"}


def _esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


# --- адреса ---------------------------------------------------------------------------
def winter_city_path(city_name: str) -> str:
    return f"/c/{city_slug(city_name)}/zimoy"


def _abs(base_url: str, path: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    return f"{base}{path}" if base else path


def yandex_open_url(lat: float, lon: float) -> str:
    return f"https://yandex.ru/maps/?pt={float(lon):.6f},{float(lat):.6f}&z=16&l=map"


def google_route_url(item: Mapping[str, Any]) -> str | None:
    if item.get("map_allowed") and item.get("lat") is not None:
        return f"https://www.google.com/maps/dir/?api=1&destination={float(item['lat']):.6f},{float(item['lon']):.6f}"
    addr = (item.get("address") or "").strip()
    if not addr:
        return None
    return "https://www.google.com/maps/search/?api=1&query=" + quote(f"{item.get('city') or ''} {addr}".strip())


def _icon(name: str, extra: str = "") -> str:
    return icon_svg(name, extra_class=extra)


def _kind_label(item: Mapping[str, Any], *, short: bool = False) -> str:
    if item.get("kind") == "hockey_box":
        return "Коробка" if short else "Хоккейная коробка"
    return "Каток"


def _price(item: Mapping[str, Any]) -> str:
    if item.get("is_paid") is False:
        return "Бесплатно"
    if item.get("is_paid") is True:
        return f"Платно, {item['price_note']}" if item.get("price_note") else "Платно"
    return str(item.get("price_note") or "Цена уточняется")


def _hours(item: Mapping[str, Any]) -> str:
    h = item.get("hours") or {}
    label = f" · {h['label']}" if h.get("label") else ""
    if h.get("known") and h.get("summary"):
        return f"{h['summary']}{label}"
    if h.get("known") and h.get("text"):
        return f"{h['text']}{label}"
    return str(h.get("fallback") or "Часы уточняйте по телефону")


def _distance(km: float | None) -> str:
    if km is None:
        return ""
    if km < 1:
        return f"{max(50, round(km * 1000 / 50) * 50)}{NBSP}м"
    return f"{round(km, 1):g}".replace(".", ",") + f"{NBSP}км"


def _tags(item: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    if item.get("crowd") in CROWD_LABEL:
        out.append(CROWD_LABEL[item["crowd"]])
    if item.get("hockey") in HOCKEY_LABEL:
        out.append(HOCKEY_LABEL[item["hockey"]])
    if item.get("quality") == "bad":
        out.append("Лёд плохой")
    return out


def pill(item: Mapping[str, Any]) -> str:
    state = str(item.get("state") or "waiting")
    tone = STATE_TONE.get(state, "wait")
    return (
        f'<span class="w-pill w-pill--{tone}">{_icon(STATE_ICON.get(state, "clock"))}'
        f"{_esc(STATE_LABEL.get(state, 'Ждём заливку'))}</span>"
    )


def checked_line(item: Mapping[str, Any]) -> str:
    """Для серверной отрисовки только то, что не стареет: дата админской проверки. «40 мин назад» дорисует JS."""
    if item.get("checked_by") == "admin" and item.get("state_at"):
        from datetime import datetime, timedelta, timezone

        try:
            moment = datetime.fromisoformat(str(item["state_at"])).astimezone(timezone(timedelta(hours=3)))
        except ValueError:
            return ""
        return f"Проверено {moment:%d.%m}"
    return ""


# --- головы страниц -------------------------------------------------------------------
def _shell(
    *, title: str, description: str, canonical: str, robots: str, og_image: str, body: str, jsonld: str,
    footer: str, extra_head: str = "", page_class: str = "", beacon: str = "", city_pin: str = "", lang_country: str = "BY",
) -> str:
    lang, og_locale = html_lang_for_country(lang_country)
    page = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return fill_placeholders(
        page,
        {
            "__LANG__": lang,
            "__OG_LOCALE__": og_locale,
            "__TITLE__": _esc(title),
            "__DESCRIPTION__": _esc(description),
            "__CANONICAL__": _esc(canonical),
            "__ROBOTS__": _esc(robots),
            "__OG_IMAGE__": _esc(og_image),
            "__JSONLD__": jsonld,
            "__HEAD_EXTRA__": extra_head,
            "__PUBLIC_FONTS_HEAD__": public_fonts_head_html(),
            "__TOKENS_V__": TOKENS_VERSION,
            "__COMPONENTS_V__": COMPONENTS_VERSION,
            "__STYLE_V__": STYLE_VERSION,
            "__WINTER_CSS_V__": WINTER_CSS_VERSION,
            "__WINTER_MODEL_V__": WINTER_MODEL_VERSION,
            "__WINTER_JS_V__": WINTER_JS_VERSION,
            "__PAGE_CLASS__": page_class,
            "__BODY__": body,
            "__SITE_FOOTER__": footer,
            "__PAGE_VIEW_BEACON__": beacon,
            "__GLIDE_CITY_PIN__": city_pin,
        },
    )


# --- список ---------------------------------------------------------------------------
def _thumb(item: Mapping[str, Any]) -> str:
    photos = item.get("photos") or []
    if photos:
        url = media_url({"variants": photos[0].get("variants")}, size="card")
        if url:
            n = len(photos)
            return (
                f'<span class="w-thumb"><img src="{_esc(url)}" alt="" loading="lazy" decoding="async">'
                f'<span class="w-thumb__label">{n}{NBSP}{_plural(n, "фото", "фото", "фото")}</span></span>'
            )
    if item.get("static_map_url"):  # миниатюры карт — только за флагом WINTER_STATIC_MAP_THUMBS
        return f'<span class="w-thumb"><img src="{_esc(item["static_map_url"])}" alt="" loading="lazy" decoding="async"></span>'
    return (
        f'<span class="w-thumb w-thumb--type">{rink_motif_svg(extra_class="w-thumb__motif", small=True)}'
        f'<span class="w-thumb__glyph">{_esc(_kind_label(item, short=True))}</span></span>'
    )


def _card(item: Mapping[str, Any], city_name: str) -> str:
    href = place_path(city_name=city_name, slug=str(item["slug"])) if item.get("slug") else f"/p/{int(item['id'])}"
    tags = "".join(f'<span class="w-tag">{_esc(t)}</span>' for t in _tags(item))
    if item.get("dispute"):
        tags += '<span class="w-tag w-tag--warn">Отметки расходятся</span>'
    checked = checked_line(item)
    meta = " · ".join(b for b in (_hours(item), _price(item), "точку уточняем" if item.get("locating") else "") if b)
    dist = _distance(item.get("distance_km"))
    label = f"{item['name']}, {STATE_LABEL.get(item.get('state'), 'Ждём заливку')}"
    return (
        f'<li class="w-li"><a class="w-card" href="{_esc(href)}" data-w-id="{int(item["id"])}" aria-label="{_esc(label)}">'
        f"{_thumb(item)}"
        '<span class="w-card__body">'
        f'<span class="w-card__top"><span>{_esc(_kind_label(item, short=True))}</span>'
        f'<span class="w-card__dist" data-w-dist>{_esc(dist)}</span></span>'
        f'<span class="w-card__name">{_esc(item["name"])}</span>'
        f'<span class="w-card__tags">{pill(item)}{tags}</span>'
        f'<span class="w-card__meta">{_esc(meta)}</span>'
        + (f'<span class="w-card__meta" data-w-checked>{_esc(checked)}</span>' if checked else '<span class="w-card__meta" data-w-checked hidden></span>')
        + "</span></a></li>"
    )


def _client_points(items: list[Mapping[str, Any]], city_name: str) -> list[dict[str, Any]]:
    """Что нужно скрипту: порядок, фильтры, карта. Ничего лишнего, токенов нет."""
    out = []
    for i in items:
        out.append(
            {
                "id": int(i["id"]), "name": i["name"], "kind": i["kind"], "state": i["state"], "dispute": bool(i["dispute"]),
                "district": i.get("district"), "pin": i.get("pin"), "map_allowed": bool(i["map_allowed"]),
                "lat": i.get("lat"), "lon": i.get("lon"), "locating": bool(i["locating"]),
                "href": place_path(city_name=city_name, slug=str(i["slug"])) if i.get("slug") else f"/p/{int(i['id'])}",
                "state_at": i.get("state_at"), "checked_by": i.get("checked_by"), "quality": i.get("quality"),
                "crowd": i.get("crowd"), "hockey": i.get("hockey"),
            }
        )
    return out


def _summary_line(total: int, flooded: int) -> str:
    noun = _plural(total, "уличная точка", "уличные точки", "уличных точек")
    line = f"{total}{NBSP}{noun}"
    if flooded:
        return f"{line} · залиты {flooded} · ждём {max(0, total - flooded)}"
    return f"{line} · ждём заливку"


def render_city_page(
    *, city: Mapping[str, Any], data: Mapping[str, Any], base_url: str, ymaps_key: str | None, suggest_href: str,
    city_href: str, beacon: str = "", city_pin: str = "", footer: str | None = None, og_image: str = "",
) -> str:
    name = str(city["name"])
    items: list[Mapping[str, Any]] = list(data.get("items") or [])
    total, flooded = int(data.get("total") or 0), int(data.get("flooded") or 0)
    where = city_locative(name)
    title_where = where or name
    canonical = _abs(base_url, winter_city_path(name))
    season = str(data.get("season_label") or "2026/27")
    bell = data.get("bell_near_link")

    if total:
        sub = _summary_line(total, flooded)
        if flooded == 0:
            head_note = (
                '<p class="w-sub"><b>Сезон открывается: ждём первые заливы.</b> '
                "Как только где-то зальют, напишем в Telegram. Были у льда — отметьте, это поможет другим.</p>"
            )
        else:
            head_note = f'<p class="w-sub">{_esc(sub)}</p>'
    else:
        head_note = '<p class="w-sub">Пока ни одной точки. Знаете, где в городе заливают лёд, — предложите.</p>'

    bell_html = ""
    if total and bell:
        # «Напишем, когда зальют» — только пока не залито; у залитой точки колокольчик ничего бы не обещал.
    bell_html = (
        f'<a class="w-btn w-btn--tg w-btn--wide" href="{_esc(bell)}" rel="noopener">{_icon("bell")}'
        "Написать в Telegram, когда зальют</a>"
        if bell and item.get("state") in ("waiting", "stale") and not item.get("doubtful")
        else ""
    )
    body = (
        f'<div class="w-page w-page--point" data-w-page="point" data-w-arena="{int(item["id"])}" data-w-state="{_esc(item.get("state"))}" '
        f'data-w-api="/api/public/winter/points/{int(item["id"])}">'
        f'{_hero(item, list_href=list_href, suggest_href=suggest_href)}'
        '<div class="w-pointbody">'
        '<div class="w-head">'
        f'<span class="w-kindbadge">{_esc(kind)} · {_esc(price_chip.lower() if item.get("is_paid") is not None else "цена уточняется")}</span>'
        f'<h1 class="w-h1">{_esc(item["name"])}</h1>'
        f'<p class="w-addr">{_esc(addr_line)}</p></div>'
        f'{_status_card(item, season_label=season_label, links=links)}'
        f"{bell_html}{_known(item)}{_gallery(item)}{_routes(item)}"
        "</div>"
        f"{_sheet(item)}</div>"
    )
    ld_obj: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "SportsActivityLocation",
        "name": item["name"],
        "url": canonical,
        "address": {"@type": "PostalAddress", "streetAddress": item.get("address") or "", "addressLocality": name, "addressCountry": "BY"},
        "isAccessibleForFree": item.get("is_paid") is False,
    }
    if item.get("map_allowed") and item.get("lat") is not None:
        ld_obj["geo"] = {"@type": "GeoCoordinates", "latitude": item["lat"], "longitude": item["lon"]}
    # O4: openingHours не отдаём — часы прошлой зимы; aggregateRating нет — оценок в этом релизе нет.
    crumbs = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": name, "item": _abs(base_url, f"/c/{city_slug(name)}")},
            {"@type": "ListItem", "position": 2, "name": "Зимой", "item": _abs(base_url, winter_city_path(name))},
            {"@type": "ListItem", "position": 3, "name": item["name"], "item": canonical},
        ],
    }
    description = (
        f"{kind}{' ' + item['name'] if item.get('name') else ''}, {item.get('address') or name}. "
        "Часы и цена сезона 2025/26, как добраться, отметки о льде от людей."
    )
    robots = "index, follow" if indexable and not item.get("doubtful") else "noindex, follow"
    title = f"{item['name']} — зимой {('в ' + where) if where else name} | Glideclub"
    return _shell(
        title=title,
        description=description,
        canonical=canonical,
        robots=robots,
        og_image=og_image,
        body=body,
        jsonld=json_for_script([ld_obj, crumbs]),
        footer=footer if footer is not None else render_site_footer_html(),
        beacon=beacon,
        city_pin=city_pin,
        lang_country=str(city.get("country") or "BY"),
        page_class="w-body",
    )


def render_gone_page(*, city: Mapping[str, Any] | None, name: str | None, list_href: str | None, home_href: str, footer: str | None = None) -> str:
    """Точку убрали из каталога: человек не получает голый 404, а понимает, что случилось, и видит выход."""
    city_name = str(city["name"]) if city else ""
    links = ""
    if list_href and city_name:
        links += f'<a class="w-btn w-btn--tg w-btn--wide" href="{_esc(list_href)}">Другие зимние точки: {_esc(city_name)}</a>'
    links += f'<a class="w-btn w-btn--soft w-btn--wide" href="{_esc(home_href)}">Открыть каталог Glide</a>'
    heading = f"«{name}» больше нет в зимнем каталоге" if name else "Этой точки больше нет в зимнем каталоге"
    body = (
        '<div class="w-page" data-w-page="gone">'
        f'<h1 class="w-title">{_esc(heading)}</h1>'
        '<p class="w-sub">Возможно, каток закрыли или точка оказалась ошибкой в таблицах. Рядом наверняка есть другие.</p>'
        f"{links}</div>"
    )
    return _shell(
        title="Точки больше нет в каталоге | Glideclub",
        description="Эту зимнюю точку убрали из каталога Glide.",
        canonical="",
        robots="noindex, follow",
        og_image="",
        body=body,
        jsonld="{}",
        footer=footer if footer is not None else render_site_footer_html(),
    )
