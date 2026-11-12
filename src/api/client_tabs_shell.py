"""TASK-391 (PDEC-035): «Я» и «Записи» в одной оболочке по их же адресам.

Оболочка — это страница текущей вкладки как есть, плюс три вставки: метка ``data-ft-shell`` на
``<html>``, тело в контейнере вкладки (``display: contents`` — раскладка та же) и роутер
``client-tabs.js``. Вторая вкладка приходит фрагментом: тело её страницы без скриптов, её стили и
скрипты по порядку. Источник у обоих — тот же html страницы, копий разметки нет.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from src.api.asset_stamp import asset_stamp, stamp_html

_WEBAPP_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "webapp"

# id вкладки бара → (адрес страницы, файл). Порядок — порядок вкладок в баре.
SHELL_TABS: dict[str, tuple[str, str]] = {
    "bookings": ("client-bookings", "client-bookings.html"),
    "me": ("client-me", "client-me.html"),
}

_HEAD_RE = re.compile(r"<head\b[^>]*>(?P<head>.*?)</head>", re.IGNORECASE | re.DOTALL)
_BODY_RE = re.compile(r"<body\b(?P<attrs>[^>]*)>(?P<body>.*)</body>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
_CLASS_RE = re.compile(r'\bclass="(?P<cls>[^"]*)"', re.IGNORECASE)
# Стили и скрипты в порядке документа: каскад и порядок выполнения — как на странице.
_ASSET_RE = re.compile(
    r"<script\b(?P<sattrs>[^>]*)>(?P<code>.*?)</script>"
    r"|<style\b[^>]*>(?P<css>.*?)</style>"
    r"|<link\b(?P<lattrs>[^>]*)>",
    re.IGNORECASE | re.DOTALL,
)
_SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>.*?</script>\s*", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r'\b(?P<name>[a-z-]+)(?:="(?P<value>[^"]*)")?', re.IGNORECASE)

SHELL_HEAD = (
    "<style>.ft-tab{display:contents}.ft-tab[hidden]{display:none!important}</style>\n"
    '  <script defer src="client-tabs.js?v=0"></script>\n'
)


def _attrs(raw: str) -> dict[str, str]:
    return {m.group("name").lower(): m.group("value") or "" for m in _ATTR_RE.finditer(raw or "")}


def page_html(tab: str) -> str:
    """Страница вкладки ровно так, как её отдаёт сервер без флага (шрифты и метка ``?v=``)."""
    from src.application.style_b import FONT_V_PLACEHOLDER, PUBLIC_FONTS_ASSET_VERSION

    _, file_name = SHELL_TABS[tab]
    raw = (_WEBAPP_DIR / file_name).read_text(encoding="utf-8")
    return stamp_html(raw.replace(FONT_V_PLACEHOLDER, PUBLIC_FONTS_ASSET_VERSION))


def shell_tab_for_path(path_key: str) -> str | None:
    for tab, (key, _) in SHELL_TABS.items():
        if key == path_key:
            return tab
    return None


def shell_html(tab: str) -> str:
    """Оболочка с вкладкой ``tab`` на первом кадре."""
    path_key, _ = SHELL_TABS[tab]
    html = page_html(tab)
    html = re.sub(r"<html\b", f'<html data-ft-shell="{tab}"', html, count=1, flags=re.IGNORECASE)
    head_close = html.lower().index("</head>")
    html = html[:head_close] + stamp_html(SHELL_HEAD) + html[head_close:]
    body = _BODY_RE.search(html)
    if body is None:
        raise ValueError(f"{tab}: no <body>")
    open_end = body.start("body")
    close_start = body.end("body")
    container = f'<div class="ft-tab" data-ft-tab="{tab}" data-ft-path="{path_key}">'
    return html[:open_end] + container + html[open_end:close_start] + "</div>\n" + html[close_start:]


def _fragment(tab: str) -> dict:
    path_key, _ = SHELL_TABS[tab]
    html = page_html(tab)
    head = _HEAD_RE.search(html)
    body = _BODY_RE.search(html)
    if head is None or body is None:
        raise ValueError(f"{tab}: no <head>/<body>")
    css: list[dict[str, str]] = []
    scripts: list[dict[str, object]] = []
    for part in (head.group("head"), body.group("body")):
        for m in _ASSET_RE.finditer(part):
            if m.group("lattrs") is not None:
                a = _attrs(m.group("lattrs"))
                if a.get("rel", "").lower() == "stylesheet" and a.get("href"):
                    css.append({"href": a["href"]})
            elif m.group("css") is not None:
                css.append({"code": m.group("css")})
            else:
                a = _attrs(m.group("sattrs"))
                kind = a.get("type", "").lower()
                if kind and kind not in ("text/javascript", "application/javascript", "module"):
                    continue
                if a.get("src"):
                    scripts.append({"src": a["src"], "defer": "defer" in a})
                elif m.group("code").strip():
                    scripts.append({"code": m.group("code")})
    title = _TITLE_RE.search(head.group("head"))
    cls = _CLASS_RE.search(body.group("attrs"))
    markup = _SCRIPT_TAG_RE.sub("", body.group("body")).strip()
    return {
        "tab": tab,
        "path": path_key,
        "title": title.group("title").strip() if title else "",
        "bodyClass": cls.group("cls") if cls else "",
        "css": css,
        "scripts": scripts,
        "html": markup,
    }


@lru_cache(maxsize=8)
def _fragment_json(tab: str, stamp: str) -> str:
    del stamp  # ключ кэша: новая статика — новый фрагмент
    return json.dumps(_fragment(tab), ensure_ascii=False, separators=(",", ":"))


def fragment_json(tab: str) -> str:
    return _fragment_json(tab, asset_stamp())
