"""Счётчики веб-аналитики на публичных SSR-страницах каталога (Метрика / GA4).

ID задаются в .env; без них фрагмент пустой — локаль и тесты без внешних скриптов.
"""

from __future__ import annotations

import re

from src.shared.config import get_settings

_GA4_ID_RE = re.compile(r"^G-[A-Z0-9]{6,}$")


def _normalize_ga4_id(raw: str | None) -> str | None:
    value = (raw or "").strip()
    if not value:
        return None
    if not _GA4_ID_RE.match(value):
        return None
    return value


def _normalize_metrika_id(raw: int | None) -> int | None:
    if raw is None:
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return n


def public_analytics_head_html(
    *,
    yandex_metrika_counter_id: int | None = None,
    google_analytics_measurement_id: str | None = None,
) -> str:
    """HTML для <head>: async-теги Метрики и GA4. Вебвизор выключен."""
    parts: list[str] = []
    counter = _normalize_metrika_id(yandex_metrika_counter_id)
    if counter is not None:
        cid = str(counter)
        parts.append(
            f"  <script>\n"
            f"    (function(m,e,t,r,i,k,a){{m[i]=m[i]||function(){{(m[i].a=m[i].a||[]).push(arguments)}};\n"
            f"    m[i].l=1*new Date();\n"
            f"    for (var j = 0; j < document.scripts.length; j++) {{\n"
            f"      if (document.scripts[j].src === r) {{ return; }}\n"
            f"    }}\n"
            f"    k=e.createElement(t);a=e.getElementsByTagName(t)[0];k.async=1;k.src=r;\n"
            f"    a.parentNode.insertBefore(k,a)}})\n"
            f'    (window, document, "script", "https://mc.yandex.ru/metrika/tag.js", "ym");\n'
            f"    ym({cid}, \"init\", {{"
            f"ssr:true, clickmap:true, trackLinks:true, accurateTrackBounce:true, webvisor:false"
            f"}});\n"
            f"  </script>\n"
            f'  <noscript><div><img src="https://mc.yandex.ru/watch/{cid}" '
            f'style="position:absolute; left:-9999px;" alt="" /></div></noscript>'
        )
    ga_id = _normalize_ga4_id(google_analytics_measurement_id)
    if ga_id is not None:
        parts.append(
            f'<script async src="https://www.googletagmanager.com/gtag/js?id={ga_id}"></script>\n'
            f"  <script>\n"
            f"    window.dataLayer = window.dataLayer || [];\n"
            f"    function gtag(){{dataLayer.push(arguments);}}\n"
            f"    gtag('js', new Date());\n"
            f"    gtag('config', '{ga_id}');\n"
            f"  </script>"
        )
    return "\n  ".join(parts)


def public_analytics_head_html_from_settings() -> str:
    settings = get_settings()
    return public_analytics_head_html(
        yandex_metrika_counter_id=settings.yandex_metrika_counter_id,
        google_analytics_measurement_id=settings.google_analytics_measurement_id,
    )
