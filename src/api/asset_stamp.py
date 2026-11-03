"""Метка кэша ``?v=`` для js/css Mini App ставится сервером, а не вручную в 60+ html.

Раньше после каждой правки статики метку приходилось поднимать во всех страницах, иначе Telegram
держал старый файл (маршрут отдаёт файл с ``?v=`` как immutable). Теперь страницы отдаются с одной
меткой сборки: в html остаётся любое число, а сервер подменяет его на метку деплоя.

Метка — только цифры: ``mini-app-client-shell.js`` читает свою версию регуляркой ``v=(\\d+)`` и
префетчит остальные файлы с ней же. Одна метка на все файлы держит префетч в силе.
"""

from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path

_WEBAPP_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "webapp"
# Только адреса скриптов и стилей: числа в других местах страницы не трогаем.
_ASSET_V = re.compile(r"(\.(?:js|css)\?v=)\d+")
_DIGITS = 15


def _digits(raw: str) -> str:
    """Стабильные цифры из любой строки: регулярка shell понимает только ``\\d+``."""
    return str(int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:13], 16)).zfill(_DIGITS)[:_DIGITS]


def _tree_signature() -> str:
    """Без id деплоя (локально, тесты): подпись по именам, размерам и времени правки файлов статики."""
    parts: list[str] = []
    if _WEBAPP_DIR.is_dir():
        for path in sorted(_WEBAPP_DIR.rglob("*")):
            if path.is_file() and path.suffix in (".js", ".css", ".html"):
                stat = path.stat()
                parts.append(f"{path.name}:{stat.st_size}:{int(stat.st_mtime)}")
    return "|".join(parts)


@lru_cache(maxsize=1)
def asset_stamp() -> str:
    """Один и тот же у всех реплик одного деплоя: берётся id коммита, который Railway кладёт в окружение."""
    sha = (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("GIT_COMMIT_SHA") or "").strip()
    return _digits(sha) if sha else _digits(_tree_signature())


def stamp_html(html: str) -> str:
    """Подменить ``?v=<число>`` у ``*.js`` и ``*.css`` на метку сборки."""
    stamp = asset_stamp()
    return _ASSET_V.sub(lambda m: m.group(1) + stamp, html)


def reset_asset_stamp_for_tests() -> None:
    asset_stamp.cache_clear()
