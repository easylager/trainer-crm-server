"""TASK-448 (redesign_s3): серверные бандлы ассетов client-home-v2.

Без сборщика: склейка файлов, которые страница грузит сегодня, в два JS
(синхронные из <head> + defer/конец body) и один CSS. checkin-sheet.css
намеренно не входит — он ленивый. Версия ``?v=`` — sha256 содержимого,
ответ кэшируется надолго (immutable).

Списки держать синхронно с разметкой ``static/webapp/client-home-v2.html``
(регион ``<!-- s3:assets -->``) и с e2e-стабами (home-v2.check.mjs,
home-perf.mjs).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parents[2] / "static"

# Синхронные скрипты <head> — в порядке загрузки на странице.
HEAD_JS = [
    "webapp/glide-deeplink.js",
    "webapp/write-access.js",
    "webapp/client-mini-app-theme.js",
    "webapp/mini-app-client-shell.js",
    "webapp/ru-person-name.js",
]

# Отложенные скрипты + скрипты в конце <body> — в порядке исполнения как defer.
APP_JS = [
    "webapp/mini-app-telegram-chrome.js",
    "webapp/mini-app-empty-state.js",
    "webapp/mini-app-more-icons.js",
    "webapp/client-profile-switcher.js",
    "webapp/ga-press.js",
    "webapp/home-v2.js",
    "webapp/ga-touch.js",
]

CSS = [
    "shared/glide-public-fonts.css",
    "shared/glide-tokens.css",
    "webapp/mini-app-client-theme.css",
    "webapp/mini-app-client-shell.css",
    "webapp/home-v2.css",
]

# TASK-449: вкладка «Лёд» v2 — та же схема, свой префикс ``ice-v2.*``.
ICE_HEAD_JS = [
    "webapp/glide-deeplink.js",
    "webapp/write-access.js",
    "webapp/client-mini-app-theme.js",
    "webapp/mini-app-client-shell.js",
]

ICE_APP_JS = [
    "webapp/mini-app-telegram-chrome.js",
    "webapp/mini-app-empty-state.js",
    "webapp/mini-app-more-icons.js",
    "webapp/client-profile-switcher.js",
    "webapp/ga-press.js",
    "webapp/ice-v2.js",
    "webapp/ga-touch.js",
]

ICE_CSS = [
    "shared/glide-public-fonts.css",
    "shared/glide-tokens.css",
    "webapp/mini-app-client-theme.css",
    "webapp/mini-app-client-shell.css",
    "webapp/ice-v2.css",
]

_FILES = {
    "head.js": (HEAD_JS, ";\n", "application/javascript"),
    "app.js": (APP_JS, ";\n", "application/javascript"),
    "bundle.css": (CSS, "\n", "text/css"),
}

_ICE_FILES = {
    "head.js": (ICE_HEAD_JS, ";\n", "application/javascript"),
    "app.js": (ICE_APP_JS, ";\n", "application/javascript"),
    "bundle.css": (ICE_CSS, "\n", "text/css"),
}

ME_HEAD_JS = [
    "webapp/glide-deeplink.js",
    "webapp/write-access.js",
    "webapp/client-mini-app-theme.js",
    "webapp/mini-app-client-shell.js",    "webapp/ru-person-name.js",
]

ME_APP_JS = [
    "webapp/mini-app-telegram-chrome.js",
    "webapp/mini-app-empty-state.js",
    "webapp/mini-app-more-icons.js",
    "webapp/client-profile-switcher.js",
    "webapp/ga-press.js",
    "webapp/badge-art.js",
    "webapp/badge-award.js",
    "webapp/me-v2.js",
    "webapp/ga-touch.js",
]

ME_CSS = [
    "shared/glide-public-fonts.css",
    "shared/glide-tokens.css",
    "webapp/mini-app-client-theme.css",
    "webapp/mini-app-client-shell.css",
    "webapp/me-v2.css",
    "webapp/badge-award.css",
]

_ME_FILES = {
    "head.js": (ME_HEAD_JS, ";\n", "application/javascript"),
    "app.js": (ME_APP_JS, ";\n", "application/javascript"),
    "bundle.css": (ME_CSS, "\n", "text/css"),
}

_PAGES = {"home-v2": _FILES, "ice-v2": _ICE_FILES, "me-v2": _ME_FILES}

# Склейка — один раз на процесс (лениво по первому запросу).
_cache: dict[tuple[str, str], tuple[str, str]] = {}


def build_bundle(kind: str, *, page: str = "home-v2") -> tuple[str, str]:
    """``(version, body)`` для ``head.js`` / ``app.js`` / ``bundle.css`` страницы ``page``."""
    key = (page, kind)
    if key in _cache:
        return _cache[key]
    files, sep, _mt = _PAGES[page][kind]
    parts: list[str] = []
    for rel in files:
        path = _STATIC_DIR / rel
        if not path.is_file():
            raise FileNotFoundError(str(path))
        parts.append(f"/* file: {rel} */\n{path.read_text(encoding='utf-8')}")
    body = sep.join(parts)
    version = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    _cache[key] = (version, body)
    return _cache[key]


def media_type(kind: str, *, page: str = "home-v2") -> str:
    return _PAGES[page][kind][2]


def bundle_tags(*, page: str = "home-v2") -> str:
    """Три тега, которыми маршрут подменяет регион ``s3:assets`` в <head>."""
    head_v, _ = build_bundle("head.js", page=page)
    app_v, _ = build_bundle("app.js", page=page)
    css_v, _ = build_bundle("bundle.css", page=page)
    return (
        f'  <link rel="stylesheet" href="/webapp/{page}.bundle.css?v={css_v}" />\n'
        f'  <script src="/webapp/{page}.head.js?v={head_v}"></script>\n'
        f'  <script defer src="/webapp/{page}.app.js?v={app_v}"></script>\n'
    )


def apply_bundles(html: str, *, page: str = "home-v2") -> str | None:
    """Подменяет регионы ``s3:assets``: первый — тремя тегами, остальные — пусто.

    ``None``, если разметки нет или бандл не собрался (fail-safe: страница
    отдаётся как сегодня, с одиночными файлами).
    """
    import re

    regions = list(re.finditer(r"<!-- s3:assets -->.*?<!-- /s3:assets -->", html, flags=re.S))
    if not regions:
        return None
    try:
        tags = bundle_tags(page=page)
    except Exception:
        logger.exception("home-v2 s3 bundle build failed — serving unbundled page")
        return None
    out = html
    # Заменяем с конца, чтобы индексы ранних регионов не съезжали.
    for i, m in reversed(list(enumerate(regions))):
        out = out[: m.start()] + (tags if i == 0 else "") + out[m.end() :]
    return out
