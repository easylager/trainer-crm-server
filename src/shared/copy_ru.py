"""Единый словарь подписей каталога (TASK-209) — Python-сторона.

Один источник ``copy_ru.json`` читается здесь и JS-модулем
``static/webapp/glide-copy.js``, чтобы сайт (``static/share/*``) и Mini App
(``static/webapp/*``) не могли разойтись в словах («В выходные» / «Выходные»).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PATH = Path(__file__).resolve().parent / "copy_ru.json"
COPY: dict[str, str] = json.loads(_PATH.read_text(encoding="utf-8"))


def t(key: str, **kw: Any) -> str:
    """Подпись по ``key``; без ``kw`` — шаблон как есть, с ``kw`` — подставленные ``{имя}``."""
    template = COPY[key]
    return template.format(**kw) if kw else template
