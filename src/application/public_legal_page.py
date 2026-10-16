"""Простые legal-страницы /privacy и /terms (заглушки под юриста)."""

from __future__ import annotations

import html as html_lib
from pathlib import Path

from src.application.public_site_footer import render_site_footer_html
from src.application.style_b import COMPONENTS_VERSION, STYLE_VERSION, TOKENS_VERSION, public_fonts_head_html
from src.shared.html_template import fill_placeholders, html_lang_for_country

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "legal-page.html"

_PAGES: dict[str, dict[str, str]] = {
    "privacy": {
        "title": "Политика конфиденциальности",
        "description": "Как Glide обрабатывает персональные данные на сайте и в Telegram.",
        "heading": "Политика конфиденциальности",
        "body": (
            "<p>Это черновик страницы. Здесь будет описано, какие данные мы собираем "
            "(например, при открытии сайта, в боте и при записи к тренеру), зачем они нужны, "
            "как долго хранятся и как с нами связаться по вопросам персональных данных.</p>"
            "<p><strong>Нужно заполнить:</strong> наименование оператора, юридический адрес, "
            "перечень целей обработки, основания (согласие/договор), права субъекта данных, "
            "cookies и аналитика (если используем), контакт для запросов.</p>"
        ),
    },
    "terms": {
        "title": "Условия использования",
        "description": "Правила использования сайта Glide и сервиса расписания катков.",
        "heading": "Условия использования",
        "body": (
            "<p>Это черновик страницы. Здесь будут правила пользования каталогом расписания, "
            "ограничение ответственности за актуальность данных с катков, поведение пользователей "
            "и условия для тренеров, если они отличаются.</p>"
            "<p><strong>Нужно заполнить:</strong> предмет сервиса, отказ от гарантий по расписанию, "
            "интеллектуальная собственность, порядок изменения условий, применимое право.</p>"
        ),
    },
}


def _esc(value: object) -> str:
    return html_lib.escape(str(value), quote=True)


def render_legal_page(page_key: str, *, trainers_href: str = "/trainers") -> str:
    meta = _PAGES.get(page_key)
    if meta is None:
        raise KeyError(page_key)
    lang, og_locale = html_lang_for_country("BY")
    path = f"/{page_key}"
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return fill_placeholders(
        template,
        {
            "__LANG__": lang,
            "__OG_LOCALE__": og_locale,
            "__TITLE__": _esc(meta["title"]),
            "__DESCRIPTION__": _esc(meta["description"]),
            "__CANONICAL__": _esc(path),
            "__ROBOTS__": "index, follow",
            "__PUBLIC_FONTS_HEAD__": public_fonts_head_html(),
            "__TOKENS_V__": TOKENS_VERSION,
            "__STYLE_V__": STYLE_VERSION,
            "__COMPONENTS_V__": COMPONENTS_VERSION,
            "__H1__": _esc(meta["heading"]),
            "__BODY__": meta["body"],
            "__SITE_FOOTER__": render_site_footer_html(trainers_href=trainers_href),
        },
    )
