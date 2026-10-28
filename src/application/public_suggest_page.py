"""Страница «Предложить место» ``/suggest`` (PDEC-028): оболочка для общей формы заявки."""

from __future__ import annotations

import html as html_lib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.public_site_footer import render_site_footer_html
from src.application.style_b import (
    COMPONENTS_VERSION,
    STYLE_VERSION,
    SUGGEST_FORM_CSS_VERSION,
    SUGGEST_FORM_JS_VERSION,
    TOKENS_VERSION,
    public_fonts_head_html,
)
from src.shared.html_template import fill_placeholders, html_lang_for_country
from src.shared.ice_discovery_scope import public_city_scope_sql, public_scope_params

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "suggest-page.html"


async def load_prefill_city(session: AsyncSession, city_id: int | None) -> dict[str, Any] | None:
    """Публичный город для предзаполнения формы (ссылка со страницы города ``?city=<id>``)."""
    if not city_id:
        return None
    row = (
        await session.execute(
            text(
                f"SELECT c.id, c.name, c.region, c.country FROM cities c "
                f"WHERE c.id = :id AND {public_city_scope_sql('c')}"
            ),
            {"id": city_id, **public_scope_params()},
        )
    ).fetchone()
    if not row:
        return None
    return {"city_id": int(row[0]), "name": row[1], "region": row[2], "country": row[3], "is_new": False}


def render_suggest_page(*, trainers_href: str = "/trainers", prefill_city: dict[str, Any] | None = None) -> str:
    lang, og_locale = html_lang_for_country((prefill_city or {}).get("country") or "BY")
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return fill_placeholders(
        template,
        {
            "__LANG__": lang,
            "__OG_LOCALE__": og_locale,
            "__PUBLIC_FONTS_HEAD__": public_fonts_head_html(),
            "__TOKENS_V__": TOKENS_VERSION,
            "__STYLE_V__": STYLE_VERSION,
            "__COMPONENTS_V__": COMPONENTS_VERSION,
            "__FORM_CSS_V__": SUGGEST_FORM_CSS_VERSION,
            "__FORM_JS_V__": SUGGEST_FORM_JS_VERSION,
            "__PREFILL_CITY__": html_lib.escape(json.dumps(prefill_city, ensure_ascii=False), quote=True),
            # своя нижняя панель формы — плавающая «Приложение» перекрыла бы «Дальше»
            "__SITE_FOOTER__": render_site_footer_html(trainers_href=trainers_href, show_app_button=False),
        },
    )
