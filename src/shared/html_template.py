"""Подстановка плейсхолдеров ``__NAME__`` в статический HTML-шаблон — за один проход.

Последовательные ``str.replace`` небезопасны: если значение, вставленное раньше (имя арены
в ``og:title``), содержит более поздний плейсхолдер (``__JSONLD__``), тот разворачивается
внутри уже вставленного текста — сырой JSON оказывается в атрибуте. Один проход ``re.sub``
смотрит только на исходный шаблон, вставленные значения повторно не сканируются.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

_PLACEHOLDER_RE = re.compile(r"__[A-Z][A-Z0-9_]*__")


def fill_placeholders(template: str, values: Mapping[str, str]) -> str:
    """Заменить известные плейсхолдеры шаблона; незнакомые ``__X__`` остаются как есть."""

    def _sub(match: re.Match[str]) -> str:
        key = match.group(0)
        return values[key] if key in values else key

    return _PLACEHOLDER_RE.sub(_sub, template)


def html_lang_for_country(country: str | None) -> tuple[str, str]:
    """``(html lang, og:locale)`` страницы каталога по стране города.

    Белорусский город говорит по-русски в Беларуси (``ru-BY``), российский — ``ru-RU``.
    Страна неизвестна — прежний ``ru`` / ``ru_RU``, без выдуманного региона.
    """
    code = (country or "").strip().upper()
    if code == "BY":
        return "ru-BY", "ru_BY"
    if code == "RU":
        return "ru-RU", "ru_RU"
    return "ru", "ru_RU"


def json_for_script(payload: Any) -> str:
    """JSON для ``<script type="application/ld+json">``: ни ``</script>``, ни ``<!--`` не закроют тег.

    ``<``, ``>`` и ``&`` уходят в ``\\u003c``/``\\u003e``/``\\u0026`` — для JSON-парсера это те же символы.
    """
    return (
        json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )


_SAFE_LINK_SCHEMES = ("https://", "http://")


def safe_external_url(value: Any) -> str | None:
    """Внешняя ссылка только со схемой http(s); ``javascript:``, ``data:`` и прочее — ``None``."""
    url = str(value or "").strip()
    return url if url.lower().startswith(_SAFE_LINK_SCHEMES) else None
