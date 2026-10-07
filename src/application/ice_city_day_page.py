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
    cacheable_day_label,
    city_slug,
    plural_ru,
    price_range_line,
    summary_line,
)
from src.application.place_links import join_public_origin, place_path
from src.application.schedule_staleness import UNCONFIRMED_HEADING
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script
from src.shared.schedule_basis import basis_hint_ru, public_basis_css_class

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "ice-city-day.html"


def _esc(value: Any) -> str:
    return html_lib.escape(str(value or ""), quote=True)


def _arena_where(arena: Mapping[str, Any]) -> str:
    parts = [str(arena.get("district") or "").strip(), str(arena.get("address") or "").strip()]
    return " · ".join(p for p in parts if p)


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
    """TASK-179: откуда расписание — видимой строкой, а не только ``title`` (на телефоне его не видно)."""
    for slot in sessions:
        hint = basis_hint_ru(str(slot.get("schedule_basis") or "live"))
        if hint:
            return f'<p class="arena__basis">{_esc(hint)}</p>'
    return ""


def _arena_html(arena: Mapping[str, Any], *, city_name: str = "") -> str:
    where = _arena_where(arena)
    sessions = list(arena.get("sessions") or [])
    slots = "".join(_slot_html(s) for s in sessions)
    name = _esc(arena.get("name"))
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


def _unconfirmed_html(items: list[Mapping[str, Any]], *, city_name: str) -> str:
    """TASK-180: катки, чьё расписание > 72 ч не подтверждалось, — не в списке дня, а здесь."""
    if not items:
        return ""
    rows = []
    for item in items:
        name = _esc(item.get("name"))
        slug = str(item.get("slug") or "").strip()
        if slug and city_name:
            name = f'<a href="{_esc(place_path(city_name=city_name, slug=slug))}">{name}</a>'
        phone = str(item.get("phone") or "").strip()
        phone_html = ""
        if phone and _has_valid_phone_digits(phone):
            tel = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
            phone_html = f' · <a href="tel:{_esc(tel)}">{_esc(phone)}</a>'
        rows.append(f"<li><b>{name}</b> — {_esc(item.get('note'))}{phone_html}</li>")
    return (
        '<section class="unconfirmed">'
        f'<p class="unconfirmed__title">{_esc(UNCONFIRMED_HEADING)}</p>'
        f"<ul>{''.join(rows)}</ul></section>"
    )


def _empty_html(city_name: str, day_label: str) -> str:
    """
    Пустой день — это состояние с выходом, а не тупик (тот же принцип, что в AC-002).

    Здесь выход — кнопка «Открыть в Glide» ниже по странице: в приложении видно
    расписание на другие дни, а не только на этот.
    """
    return (
        '<div class="empty">'
        f"<p>На {_esc(day_label)} массовых катаний в расписании нет.</p>"
        f'<p class="muted">Каткам {_esc(city_name)} мы обновляем расписание каждый день — '
        "загляните в приложение, там видны ближайшие дни.</p>"
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
    arenas = list(day.get("arenas") or [])
    description = summary_line(day, city_name=city_name)
    # og и <title> кэширует мессенджер. Живой lede ниже по-прежнему говорит «сегодня».
    og_label = cacheable_day_label(day) or day_label
    og_title = f"Лёд в городе {city_name} — расписание на {og_label}"
    og_description = summary_line(day, city_name=city_name, absolute=True)

    if arenas:
        body = "".join(_arena_html(a, city_name=city_name) for a in arenas)
    else:
        body = _empty_html(city_name, day_label)
    body += _unconfirmed_html(list(day.get("unconfirmed") or []), city_name=city_name)

    session_count = int(day.get("session_count") or 0)
    if session_count:
        s_word = plural_ru(session_count, "сеанс", "сеанса", "сеансов")
        footer = f"{session_count} {s_word} на {_esc(day.get('local_date'))}"
        prices = price_range_line(day)
        if prices:
            footer += f" · {prices}"
        footer += ". Данные с сайтов и от администраций катков — время и цену уточняйте на месте."
    else:
        footer = "Расписание обновляется по данным катков."

    html = template
    lang, og_locale = html_lang_for_country(country)
    # Пустой день и город без опубликованных сеансов — 200 для человека, но не для индекса.
    robots = "index, follow" if int(day.get("session_count") or 0) > 0 else "noindex"
    values = {
        "__DESCRIPTION__": _esc(description),
        "__OG_TITLE__": _esc(og_title),
        "__OG_DESCRIPTION__": _esc(og_description),
        "__CANONICAL__": _esc(canonical_url),
        "__OG_IMAGE__": _esc(og_image_url),
        "__LANG__": lang,
        "__OG_LOCALE__": og_locale,
        "__ROBOTS__": robots,
        "__JSONLD__": _day_json_ld(day, city_name=city_name, canonical_url=canonical_url),
        "__DAY_LABEL_UPPER__": _esc(day_label.upper()),
        "__CITY__": _esc(city_name),
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
