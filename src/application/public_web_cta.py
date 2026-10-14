"""Веб-CTA на SSR-страницах каталога (TASK-191-B): звонок, билеты, маршрут, город."""

from __future__ import annotations

import html as html_lib
from typing import Any, Mapping
from urllib.parse import urlencode

from src.application.selection_page import selection_path
from src.shared.html_template import safe_external_url
from src.shared.phone_guard import is_valid_public_phone, tel_href

CONTACT_ACTION_PHONE = "phone"
CONTACT_ACTION_TICKETS = "tickets"
CONTACT_ACTION_DIRECTION = "direction"

_ALLOWED_CONTACT_ACTIONS = frozenset(
    {CONTACT_ACTION_PHONE, CONTACT_ACTION_TICKETS, CONTACT_ACTION_DIRECTION}
)

_PHONE_BEACON_SCRIPT = (
    '<script>(function(){document.addEventListener("click",function(e){'
    'var a=e.target.closest("a[data-catalog-phone-beacon]");'
    'if(!a||!navigator.sendBeacon)return;'
    'navigator.sendBeacon(a.getAttribute("data-catalog-phone-beacon"));'
    '},true);})();</script>'
)


def _esc(value: Any) -> str:
    return html_lib.escape(str(value or ""), quote=True)


def _tel_href(phone: str) -> str | None:
    raw = str(phone or "").strip()
    if not raw or not is_valid_public_phone(raw):
        return None
    return f"tel:{tel_href(raw)}"


def _maps_href(lat: Any, lon: Any) -> str | None:
    if lat is None or lon is None:
        return None
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"


def public_outbound_url(
    base_url: str,
    *,
    action: str,
    surface: str,
    city_id: int | None = None,
    arena_id: int | None = None,
) -> str | None:
    """Прокси GET: пишем ``public_contact_click``, затем 302 на билеты / карту (не tel)."""
    act = (action or "").strip().lower()
    if act not in _ALLOWED_CONTACT_ACTIONS or act == CONTACT_ACTION_PHONE:
        return None
    surf = (surface or "").strip().lower() or "place_page"
    params: dict[str, str] = {"action": act, "surface": surf}
    if city_id is not None and int(city_id) > 0:
        params["city_id"] = str(int(city_id))
    if arena_id is not None and int(arena_id) > 0:
        params["arena_id"] = str(int(arena_id))
    path = f"/api/public/catalog/outbound?{urlencode(params)}"
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return path
    low = base.lower()
    if low.startswith("https://"):
        return f"{base}{path}"
    if low.startswith("http://") and ("localhost" in low or "127.0.0.1" in low):
        return f"{base}{path}"
    return None


PAGE_VIEW_BEACON_VERSION = "2"


def public_page_view_beacon_script(
    *,
    surface: str,
    city_id: int | None = None,
    arena_id: int | None = None,
) -> str:
    """``sendBeacon`` при разборе страницы (не на bfcache-возврате) — учёт просмотра публички."""
    attrs = [f'data-surface="{_esc(surface)}"']
    if city_id is not None and int(city_id) > 0:
        attrs.append(f'data-city-id="{int(city_id)}"')
    if arena_id is not None and int(arena_id) > 0:
        attrs.append(f'data-arena-id="{int(arena_id)}"')
    return (
        f'<script defer src="/static/shared/public-page-view-beacon.js?v={PAGE_VIEW_BEACON_VERSION}" '
        f'{" ".join(attrs)}></script>'
    )


def contact_click_beacon_url(
    *,
    action: str,
    surface: str,
    city_id: int | None = None,
    arena_id: int | None = None,
) -> str:
    """Относительный URL для ``navigator.sendBeacon`` (POST) — учёт клика «Позвонить»."""
    params: dict[str, str] = {
        "action": (action or "").strip().lower(),
        "surface": (surface or "place_page").strip().lower(),
    }
    if city_id is not None and int(city_id) > 0:
        params["city_id"] = str(int(city_id))
    if arena_id is not None and int(arena_id) > 0:
        params["arena_id"] = str(int(arena_id))
    return f"/api/public/catalog/contact-click?{urlencode(params)}"


def phone_beacon_script(body_html: str) -> str:
    """Скрипт учёта звонков — один на страницу и только если на ней есть кнопка звонка.

    Слушатель кликов один на документ: повтор на каждое место дал бы по событию на копию.
    """
    return _PHONE_BEACON_SCRIPT if "data-catalog-phone-beacon=" in body_html else ""


def place_action_links(
    card: Mapping[str, Any],
    *,
    base_url: str,
    surface: str,
    city_id: int | None,
) -> dict[str, Any]:
    """Ссылки действий места для стиля B: звонок (с маяком), маршрут и билеты (через прокси учёта).

    Вёрстку делает вызывающий код. Ключа нет — действия нет. Скрипт маяка — ``phone_beacon_script``,
    один на страницу.
    """
    arena_id = int(card["id"]) if card.get("id") is not None else None
    out: dict[str, Any] = {}
    tel = _tel_href(str(card.get("phone") or ""))
    if tel:
        out["tel"] = tel
        out["tel_beacon"] = contact_click_beacon_url(
            action=CONTACT_ACTION_PHONE, surface=surface, city_id=city_id, arena_id=arena_id
        )
    maps = _maps_href(card.get("latitude"), card.get("longitude"))
    if maps:
        proxied = public_outbound_url(
            base_url, action=CONTACT_ACTION_DIRECTION, surface=surface, city_id=city_id, arena_id=arena_id
        )
        out["route"] = (proxied, False) if proxied else (maps, True)
    tickets = safe_external_url(card.get("tickets_url"))
    if tickets:
        proxied = public_outbound_url(
            base_url, action=CONTACT_ACTION_TICKETS, surface=surface, city_id=city_id, arena_id=arena_id
        )
        out["tickets"] = (proxied, False) if proxied else (tickets, True)
    return out


def render_place_primary_actions(
    card: Mapping[str, Any],
    *,
    base_url: str,
    surface: str,
    city_id: int | None,
    city_name: str,
    telegram_url: str | None,
) -> str:
    """Верхний ряд CTA на /p/: звонок, билеты, маршрут; Telegram — вторичный в dock."""
    arena_id = int(card["id"]) if card.get("id") is not None else None
    phone = str(card.get("phone") or "").strip()
    del city_name  # «‹ город» живёт в шапке страницы, не в этом ряду
    tickets = safe_external_url(card.get("tickets_url"))
    maps = _maps_href(card.get("latitude"), card.get("longitude"))
    buttons: list[str] = []
    phone_beacon = False
    tel = _tel_href(phone)
    if tel:
        beacon = contact_click_beacon_url(
            action=CONTACT_ACTION_PHONE,
            surface=surface,
            city_id=city_id,
            arena_id=arena_id,
        )
        buttons.append(
            f'<a class="cta cta--ghost" href="{_esc(tel)}" data-catalog-phone-beacon="{_esc(beacon)}">Позвонить</a>'
        )
        phone_beacon = True
    if tickets and public_outbound_url(
        base_url, action=CONTACT_ACTION_TICKETS, surface=surface, city_id=city_id, arena_id=arena_id
    ):
        url = public_outbound_url(
            base_url, action=CONTACT_ACTION_TICKETS, surface=surface, city_id=city_id, arena_id=arena_id
        )
        buttons.append(f'<a class="cta cta--ghost" href="{_esc(url)}" rel="nofollow">Билеты</a>')
    elif tickets:
        buttons.append(
            f'<a class="cta cta--ghost" href="{_esc(tickets)}" rel="noopener nofollow" target="_blank">Билеты</a>'
        )
    pair: list[str] = []
    if tel:
        pair.append(buttons[0])
    route_btn = ""
    if maps and public_outbound_url(
        base_url, action=CONTACT_ACTION_DIRECTION, surface=surface, city_id=city_id, arena_id=arena_id
    ):
        url = public_outbound_url(
            base_url, action=CONTACT_ACTION_DIRECTION, surface=surface, city_id=city_id, arena_id=arena_id
        )
        route_btn = f'<a class="cta cta--ghost" href="{_esc(url)}" rel="nofollow">Как добраться</a>'
    elif maps:
        route_btn = (
            f'<a class="cta cta--ghost" href="{_esc(maps)}" rel="noopener nofollow" target="_blank">Как добраться</a>'
        )
    if route_btn:
        pair.append(route_btn)
    # «Позвонить» уже в buttons[0], билеты — остальное. Город — ссылка в шапке, не кнопка.
    extras = buttons[1:] if tel else buttons
    if not pair and not extras and not telegram_url:
        return ""
    pair_html = f'<div class="actions actions--pair">{"".join(pair)}</div>' if pair else ""
    extra_html = f'<div class="actions">{"".join(extras)}</div>' if extras else ""
    dock = ""
    if telegram_url:
        dock = (
            f'<div class="dock"><a class="cta cta--secondary" href="{_esc(telegram_url)}">'
            "Открыть в Telegram</a></div>"
        )
    beacon_js = _PHONE_BEACON_SCRIPT if phone_beacon else ""
    return pair_html + extra_html + dock + beacon_js


def render_generic_web_dock(
    *,
    base_url: str,
    surface: str,
    city_id: int | None,
    city_name: str | None,
    telegram_url: str | None,
    card: Mapping[str, Any] | None = None,
) -> str:
    """Dock для /c/, главной, «лёд сегодня»: город + вторичный Telegram."""
    row: list[str] = []
    if city_name:
        row.append(
            f'<a class="cta cta--ghost" href="{_esc(selection_path(city_name=city_name, venue=None, when=None))}">'
            "Все места города</a>"
        )
    if card and card.get("id"):
        return render_place_primary_actions(
            card,
            base_url=base_url,
            surface=surface,
            city_id=city_id,
            city_name=city_name or "",
            telegram_url=telegram_url,
        )
    tg = ""
    if telegram_url:
        tg = (
            f'<div class="dock"><a class="cta cta--secondary" href="{_esc(telegram_url)}">'
            "Открыть в Telegram</a></div>"
        )
    actions = f'<div class="actions">{"".join(row)}</div>' if row else ""
    return actions + tg
