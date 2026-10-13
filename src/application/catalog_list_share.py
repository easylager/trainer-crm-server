"""TASK-253: «Позвать» с плиток списка/хаба и «Поделиться подборкой» через GlideShareSheet."""

from __future__ import annotations

import html as html_lib
import re
from typing import Any, Mapping
from urllib.parse import urlencode

from src.application.selection_page import KIND_OHM, clean_venue, clean_when
from src.shared.public_display import format_clock, session_day_phrase

_REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


def _esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _file_version(rel: str) -> str:
    import hashlib

    path = _REPO_ROOT / rel
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    except OSError:
        return "0"


CATALOG_LIST_SHARE_VERSION = _file_version("static/share/catalog-list-share.js")


def _webapp_bundle_version() -> str:
    try:
        text = (_REPO_ROOT / "static" / "webapp" / "arena.html").read_text(encoding="utf-8")
    except OSError:
        return "0"
    match = re.search(r"minsk-time\.js\?v=(\d+)", text)
    return match.group(1) if match else "0"


def selection_share_endpoint(view: Mapping[str, Any]) -> str:
    """Query для ``GlideShareSheet.open({ endpoint })`` — как ``openIceShareDialog`` в ice-tab.js."""
    params: dict[str, str] = {"city_id": str(int(view["city"]["id"]))}
    venue = view.get("venue")
    if venue and str(venue) not in ("service", KIND_OHM):
        cleaned = clean_venue(str(venue))
        if cleaned:
            params["venue_type"] = cleaned
    when = view.get("when")
    if when:
        cleaned_when = clean_when(str(when))
        if cleaned_when:
            params["when"] = cleaned_when
    return "/api/public/ice/selection/share?" + urlencode(params)


def city_hub_share_endpoint(view: Mapping[str, Any]) -> str:
    return "/api/public/ice/selection/share?" + urlencode({"city_id": str(int(view["city"]["id"]))})


def invite_label_for_slot(slot: Mapping[str, Any], *, today) -> str:
    day = slot.get("local_date")
    clock = str(slot.get("starts_at_local") or "")
    if hasattr(day, "year"):
        return session_day_phrase(day, clock, today=today)
    return format_clock(clock)


def catalog_invite_link(
    *,
    arena_ref: int | str,
    session_id: int,
    invite_label: str,
    place_name: str,
    fallback_href: str,
    css_class: str = "b-card2__invite",
) -> str:
    """Сосед карточки: без JS — ссылка на место с ``?s=``, с JS — шит приглашения."""
    return (
        f'<a class="{css_class}" href="{_esc(fallback_href)}" '
        f'data-invite-arena="{_esc(arena_ref)}" '
        f'data-invite-session="{_esc(session_id)}" '
        f'data-invite-label="{_esc(invite_label)}" '
        f'data-invite-place="{_esc(place_name)}">Позвать</a>'
    )


def catalog_selection_share_button(*, endpoint: str, button_id: str = "catalogSelectionShareBtn") -> str:
    return (
        f'<section class="b-sec b-sec--share-pick" aria-label="Поделиться подборкой">'
        f'<button type="button" class="b-btn b-btn--wide" id="{_esc(button_id)}" '
        f'data-catalog-selection-share="{_esc(endpoint)}">Поделиться подборкой</button>'
        f"</section>"
    )


def catalog_list_share_scripts_html() -> str:
    wv = _webapp_bundle_version()
    cv = CATALOG_LIST_SHARE_VERSION
    return (
        f'<link rel="stylesheet" href="/webapp/mini-app-share-sheet.css?v={_esc(wv)}" />\n'
        f'<link rel="stylesheet" href="/static/share/catalog-list-share.css?v={_esc(cv)}" />\n'
        f'<script src="/webapp/minsk-time.js?v={_esc(wv)}"></script>\n'
        f'<script src="/webapp/public-display-model.js?v={_esc(wv)}"></script>\n'
        f'<script src="/webapp/arena-card-model.js?v={_esc(wv)}"></script>\n'
        f'<script src="/webapp/mini-app-share-sheet.js?v={_esc(wv)}"></script>\n'
        f'<script src="/static/share/catalog-list-share.js?v={_esc(cv)}"></script>'
    )


def catalog_list_share_css_html() -> str:
    cv = CATALOG_LIST_SHARE_VERSION
    return f'<link rel="stylesheet" href="/static/share/catalog-list-share.css?v={_esc(cv)}" />'


def catalog_list_share_tail(*, scripts: bool, css: bool = False) -> dict[str, str]:
    """Плейсхолдеры b.html для списка и хаба (не страница места)."""
    css = css or scripts
    scripts_html = catalog_list_share_scripts_html() if scripts else ""
    if css and not scripts:
        scripts_html = catalog_list_share_css_html()
    return {
        "__PLACE_SHARE_BAR__": "",
        "__PLACE_SHARE_SCRIPTS__": scripts_html,
    }
