"""Города, где хаб показывает ленту «Лёд сегодня» по каткам (TASK-425).

Только города из ``SEO_RICH_HUB_CITIES``: у регионов страница ранжируется как есть и не меняется.
Текстовые блоки TASK-422 и карточка «Частые вопросы» убраны: хаб остаётся лёгким, без текста ради текста.
"""

from __future__ import annotations

# Город входит в список по слагу хаба (city_slug). Регионы сюда не добавляем без решения.
SEO_RICH_HUB_CITIES: frozenset[str] = frozenset({"minsk"})


def is_seo_rich(slug: str) -> bool:
    return slug in SEO_RICH_HUB_CITIES
