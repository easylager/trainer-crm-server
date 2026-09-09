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
    return '<li class="slot">' + "".join(lines) + "</li>"


def _arena_html(arena: Mapping[str, Any]) -> str:
    where = _arena_where(arena)
    slots = "".join(_slot_html(s) for s in arena.get("sessions") or [])
    parts = [
        '<article class="arena">',
        f'<h2 class="arena__name">{_esc(arena.get("name"))}</h2>',
    ]
    if where:
        parts.append(f'<p class="arena__where">{_esc(where)}</p>')
    parts.append(f'<ul class="slots">{slots}</ul>')
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
        f'<p class="muted">Каткам {_esc(city_name)} мы обновляем расписание каждый день — '
        "загляните в приложение, там видны ближайшие дни.</p>"
        "</div>"
    )


def render_ice_city_day_page(
    *,
    city_name: str,
    day: Mapping[str, Any],
    canonical_url: str,
    og_image_url: str,
    cta_url: str | None,
) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    day_label = str(day.get("day_label") or "сегодня")
    arenas = list(day.get("arenas") or [])
    description = summary_line(day, city_name=city_name)
    title = f"Лёд в городе {city_name} — расписание на {day_label}"

    if arenas:
        body = "".join(_arena_html(a) for a in arenas)
    else:
        body = _empty_html(city_name, day_label)

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
    html = html.replace("__TITLE__", _esc(title))
    html = html.replace("__DESCRIPTION__", _esc(description))
    html = html.replace("__CANONICAL__", _esc(canonical_url))
    html = html.replace("__OG_IMAGE__", _esc(og_image_url))
    html = html.replace("__DAY_LABEL_UPPER__", _esc(day_label.upper()))
    html = html.replace("__CITY__", _esc(city_name))
    html = html.replace("__FOOTER__", footer)
    html = html.replace("__BODY__", body)

    if cta_url:
        html = html.replace("__CTA_URL__", _esc(cta_url))
    else:
        # Кнопка без адреса — мёртвая кнопка. Лучше её не рисовать вовсе.
        start = html.find('<a class="cta"')
        end = html.find("</a>", start)
        if start != -1 and end != -1:
            html = html[:start] + html[end + 4 :]
    return html


def ice_city_day_paths(city_name: str) -> tuple[str, str]:
    """``("/ice/minsk/today", "/ice/minsk/today/og.png")``."""
    slug = city_slug(city_name)
    return f"/ice/{slug}/today", f"/ice/{slug}/today/og.png"
