"""
Сборка публичной страницы «Лёд сегодня в городе» (TASK-096 S3).

Рендер серверный и без клиентского JS: страницу открывает получатель пересланного
сообщения, у которого нет ни приложения, ни бота, часто на чужом телефоне. Всё, что
он должен увидеть — расписание и цены — обязано быть в первом же ответе, иначе
превью в чате обещает больше, чем страница отдаёт.

Шаблон и подстановка сделаны по образцу лендинга (``landing_manifest.inject_landing_html``):
статический файл с ``__PLACEHOLDER__`` + замена на сервере.
"""

from __future__ import annotations

import html as html_lib
from pathlib import Path
from typing import Any, Mapping

from src.application.ice_city_day import (
    city_slug,
    plural_ru,
    price_range_line,
    summary_line,
)
from src.application.place_links import join_public_origin, place_path
from src.shared.copy_ru import t
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script
from src.shared.public_display import format_public_name, format_street_address
from src.shared.schedule_basis import public_basis_css_class

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "ice-city-day.html"


def _esc(value: Any) -> str:
    return html_lib.escape(str(value or ""), quote=True)


def _arena_where(arena: Mapping[str, Any], *, city_name: str) -> str:
    district = str(arena.get("district") or "").strip()
    street = format_street_address(str(arena.get("address") or ""), city=city_name)
    return " · ".join(p for p in (district, street) if p)


def _slot_html(slot: Mapping[str, Any]) -> str:
    starts = str(slot.get("starts_at_local") or "").strip()
    ends = str(slot.get("ends_at_local") or "").strip()
    time_text = f"{starts}–{ends}" if starts and ends else (starts or ends or "—")
    price = str(slot.get("price_adult") or "").strip()
    note = str(slot.get("price_note") or "").strip()
    # Пустая цена остаётся пустой. «0 BYN» или «уточняйте» здесь были бы выдуманными
    # данными: мы просто не знаем цену этого сеанса (AC-005).
    second = price or note
    lines = [f'<span class="slot__time">{_esc(time_text)}</span>']
    if second:
        lines.append(f'<span class="slot__price">{_esc(second)}</span>')
    basis_cls = public_basis_css_class(str(slot.get("schedule_basis") or "live"))
    cls = "slot" + (f" {basis_cls}" if basis_cls else "")
    return f'<li class="{cls}">' + "".join(lines) + "</li>"


def _basis_note_html(sessions: list[Mapping[str, Any]]) -> str:
    """Источник сеанса в публичный текст не пишем."""
    del sessions
    return ""


def _arena_html(arena: Mapping[str, Any], *, city_name: str = "") -> str:
    where = _arena_where(arena, city_name=city_name)
    sessions = list(arena.get("sessions") or [])
    slots = "".join(_slot_html(s) for s in sessions)
    name = _esc(format_public_name(str(arena.get("name") or "")))
    slug = str(arena.get("slug") or "").strip()
    if slug and city_name:
        # TASK-146: у каждого катка своя публичная страница — расписание на неделю,
        # цены, как добраться. Ссылка отсюда — и путь человеку, и связность для поиска.
        name = f'<a href="{_esc(place_path(city_name=city_name, slug=slug))}">{name}</a>'
    parts = [
        '<article class="arena">',
        f'<h2 class="arena__name">{name}</h2>',
    ]
    if where:
        parts.append(f'<p class="arena__where">{_esc(where)}</p>')
    note = str(arena.get("stale_note") or "").strip()
    if note:
        # TASK-180: парсер давно не читал сайт катка — сеансы показываем, но честно.
        parts.append(f'<p class="arena__stale">{_esc(note)}</p>')
    parts.append(f'<ul class="slots">{slots}</ul>')
    parts.append(_basis_note_html(sessions))
    parts.append("</article>")
    return "".join(parts)


def _empty_html(city_name: str, day_label: str) -> str:
    """
    Пустой день — это состояние с выходом, а не тупик (тот же принцип, что в AC-002).

    Здесь выход — кнопка «Открыть в Glide» ниже по странице: в приложении видно
    расписание на другие дни, а не только на этот.
    """
    return (
        '<div class="empty">'
        f"<p>На {_esc(day_label)} массовых катаний в расписании нет.</p>"
        f'<p class="muted">Катки {_esc(city_name)} на другие дни — на странице города.</p>'
        "</div>"
    )


def _event_json(arena: Mapping[str, Any], slot: Mapping[str, Any], *, place_url: str) -> dict[str, Any]:
    """Один сеанс дня как schema.org Event: место, интервал, цена в валюте сеанса."""
    event: dict[str, Any] = {
        "@type": "Event",
        "name": f"Массовое катание — {arena.get('name')}",
        "startDate": slot.get("starts_at_utc"),
        "endDate": slot.get("ends_at_utc"),
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "url": place_url,
        "location": {
            "@type": "Place",
            "name": arena.get("name"),
            "url": place_url,
        },
    }
    address = str(arena.get("address") or "").strip()
    if address:
        event["location"]["address"] = address
    minor = slot.get("price_adult_minor")
    if minor is not None:
        event["offers"] = {
            "@type": "Offer",
            "price": f"{int(minor) / 100:.2f}",
            "priceCurrency": slot.get("currency_code") or "BYN",
            "url": place_url,
        }
    return event


def _day_json_ld(day: Mapping[str, Any], *, city_name: str, canonical_url: str) -> str:
    """ItemList сеансов дня. Сериализация — только ``json_for_script`` (TASK-181)."""
    elements: list[dict[str, Any]] = []
    for arena in day.get("arenas") or []:
        slug = str(arena.get("slug") or "").strip()
        place_url = join_public_origin(canonical_url, place_path(city_name=city_name, slug=slug)) if slug else ""
        for slot in arena.get("sessions") or []:
            if not place_url or not slot.get("starts_at_utc"):
                continue
            elements.append(
                {
                    "@type": "ListItem",
                    "position": len(elements) + 1,
                    "url": place_url,
                    "item": _event_json(arena, slot, place_url=place_url),
                }
            )
    return json_for_script(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": f"Лёд в городе {city_name}",
            "url": canonical_url,
            "itemListElement": elements,
        }
    )


def render_ice_city_day_page(
    *,
    city_name: str,
    day: Mapping[str, Any],
    canonical_url: str,
    og_image_url: str,
    cta_url: str | None,
    country: str | None = None,
) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    day_label = str(day.get("day_label") or "сегодня")
    shown_city = format_public_name(city_name)
    arenas = list(day.get("arenas") or [])
    description = summary_line(day, city_name=shown_city)
    og_title = t("ice.today.h1", city=shown_city)
    og_description = summary_line(day, city_name=shown_city, absolute=True)

    if arenas:
        body = "".join(_arena_html(a, city_name=city_name) for a in arenas)
    else:
        body = _empty_html(shown_city, day_label)

    session_count = int(day.get("session_count") or 0)
    if session_count:
        s_word = plural_ru(session_count, "сеанс", "сеанса", "сеансов")
        footer = f"{session_count} {s_word} сегодня"
        prices = price_range_line(day)
        if prices:
            footer += f" · {prices}"
    else:
        footer = ""

    html = template
    lang, og_locale = html_lang_for_country(country)
    # Пустой день и город без опубликованных сеансов — 200 для человека, но не для индекса.
    robots = "index, follow" if int(day.get("session_count") or 0) > 0 else "noindex"
    from src.application.style_b import public_fonts_head_html

    values = {
        "__PUBLIC_FONTS_HEAD__": public_fonts_head_html(),
        "__DESCRIPTION__": _esc(description),
        "__OG_TITLE__": _esc(og_title),
        "__OG_DESCRIPTION__": _esc(og_description),
        "__CANONICAL__": _esc(canonical_url),
        "__OG_IMAGE__": _esc(og_image_url),
        "__LANG__": lang,
        "__OG_LOCALE__": og_locale,
        "__ROBOTS__": robots,
        "__JSONLD__": _day_json_ld(day, city_name=city_name, canonical_url=canonical_url),
        "__BRAND__": _esc(t("brand.mark")),
        "__H1__": _esc(og_title),
        "__FOOTER__": footer,
        "__BODY__": body,
    }
    if cta_url:
        values["__CTA_URL__"] = _esc(cta_url)
    else:
        # Кнопка без адреса — мёртвая кнопка. Лучше её не рисовать вовсе.
        # Вырезаем из шаблона до подстановки: в теле могут быть свои «<a class="cta"».
        start = html.find('<a class="cta"')
        end = html.find("</a>", start)
        if start != -1 and end != -1:
            html = html[:start] + html[end + 4 :]
    # Один проход: вставленные имена арен не разворачивают чужие плейсхолдеры.
    return fill_placeholders(html, values)


def ice_city_day_paths(city_name: str) -> tuple[str, str]:
    """``("/ice/minsk/today", "/ice/minsk/today/og.png")``."""
    slug = city_slug(city_name)
    return f"/ice/{slug}/today", f"/ice/{slug}/today/og.png"
