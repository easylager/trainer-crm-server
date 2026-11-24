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

_FILES = {
    "head.js": (HEAD_JS, ";\n", "application/javascript"),
    "app.js": (APP_JS, ";\n", "application/javascript"),
    "bundle.css": (CSS, "\n", "text/css"),
}

# Склейка — один раз на процесс (лениво по первому запросу).
_cache: dict[str, tuple[str, str]] = {}


def build_bundle(kind: str) -> tuple[str, str]:
    """``(version, body)`` для ``head.js`` / ``app.js`` / ``bundle.css``."""
    if kind in _cache:
        return _cache[kind]
    files, sep, _mt = _FILES[kind]
    parts: list[str] = []
    for rel in files:
        path = _STATIC_DIR / rel
        if not path.is_file():
            raise FileNotFoundError(str(path))
        parts.append(f"/* file: {rel} */\n{path.read_text(encoding='utf-8')}")
    body = sep.join(parts)
    version = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    _cache[kind] = (version, body)
    return _cache[kind]


def media_type(kind: str) -> str:
    return _FILES[kind][2]


def bundle_tags() -> str:
    """Три тега, которыми маршрут подменяет регион ``s3:assets`` в <head>."""
    head_v, _ = build_bundle("head.js")
    app_v, _ = build_bundle("app.js")
    css_v, _ = build_bundle("bundle.css")
    return (
        f'  <link rel="stylesheet" href="/webapp/home-v2.bundle.css?v={css_v}" />\n'
        f'  <script src="/webapp/home-v2.head.js?v={head_v}"></script>\n'
        f'  <script defer src="/webapp/home-v2.app.js?v={app_v}"></script>\n'
    )


def apply_bundles(html: str) -> str | None:
    """Подменяет регионы ``s3:assets``: первый — тремя тегами, остальные — пусто.

    ``None``, если разметки нет или бандл не собрался (fail-safe: страница
    отдаётся как сегодня, с одиночными файлами).
    """
    import re

    regions = list(re.finditer(r"<!-- s3:assets -->.*?<!-- /s3:assets -->", html, flags=re.S))
    if not regions:
        return None
    try:
        tags = bundle_tags()
    except Exception:
        logger.exception("home-v2 s3 bundle build failed — serving unbundled page")
        return None
    out = html
    # Заменяем с конца, чтобы индексы ранних регионов не съезжали.
    for i, m in reversed(list(enumerate(regions))):
        out = out[: m.start()] + (tags if i == 0 else "") + out[m.end() :]
    return out
