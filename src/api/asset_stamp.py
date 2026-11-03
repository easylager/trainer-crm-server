"""Метка кэша ``?v=`` для js/css Mini App ставится сервером, а не вручную в 60+ html.

Раньше после каждой правки статики метку приходилось поднимать во всех страницах, иначе Telegram
держал старый файл (маршрут отдаёт файл с ``?v=`` как immutable). Теперь страницы отдаются с одной
меткой: хэшем содержимого статики. Правка любого js/css/html меняет метку, без правок она та же —
в том числе у всех реплик одного деплоя. От переменных окружения Railway метка не зависит.

Метка — только цифры: ``mini-app-client-shell.js`` читает свою версию регуляркой ``v=(\\d+)`` и
префетчит остальные файлы с ней же. Одна метка на все файлы держит префетч в силе.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path

_STATIC = Path(__file__).resolve().parent.parent.parent / "static"
# Всё, что html Mini App подтягивает как js/css: сами страницы и общие стили/скрипты.
_ROOTS = (_STATIC / "webapp", _STATIC / "shared")
# Только адреса скриптов и стилей: числа в других местах страницы не трогаем.
_ASSET_V = re.compile(r"(\.(?:js|css)\?v=)\d+")
_DIGITS = 15
_SUFFIXES = (".js", ".css", ".html")


def _content_digest() -> str:
    h = hashlib.sha256()
    for root in _ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in _SUFFIXES:
                h.update(path.relative_to(root).as_posix().encode("utf-8"))
                h.update(b"\0")
                h.update(path.read_bytes())
                h.update(b"\0")
    return h.hexdigest()


@lru_cache(maxsize=1)
def asset_stamp() -> str:
    """Цифры из хэша содержимого статики: регулярка shell понимает только ``\\d+``."""
    return str(int(_content_digest()[:13], 16)).zfill(_DIGITS)[:_DIGITS]


def stamp_html(html: str) -> str:
    """Подменить ``?v=<число>`` у ``*.js`` и ``*.css`` на метку сборки."""
    stamp = asset_stamp()
    return _ASSET_V.sub(lambda m: m.group(1) + stamp, html)


def reset_asset_stamp_for_tests() -> None:
    asset_stamp.cache_clear()
