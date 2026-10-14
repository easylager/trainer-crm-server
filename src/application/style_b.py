"""Общие детали стиля B «Лёд и свет»: герой, плитки, «Позвать друзей».

Разметка — по доскам «B · …» на холсте дизайна; классы — в static/share/style-b.css.
Здесь только вёрстка из готовых данных: SQL и решения о том, что показать, живут в вызывающем коде.
"""

from __future__ import annotations

import html as html_lib
from typing import Any, Mapping
from urllib.parse import quote

from src.application.catalog_icons import icon_svg, rink_motif_svg
from src.shared.copy_ru import t

def _file_version(rel: str) -> str:
    """?v= по содержимому файла: поменяли CSS — поменялась ссылка, кэш браузера не держит старое."""
    import hashlib
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / rel
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    except OSError:
        return "0"


TOKENS_VERSION = _file_version("static/shared/glide-tokens.css")
STYLE_VERSION = _file_version("static/share/style-b.css")
# Отдельной ссылкой, не @import из style-b.css: импорт без ?v= шёл с no-store и ещё одним кругом до первой отрисовки.
COMPONENTS_VERSION = _file_version("static/shared/glide-components.css")
DOCK_SCRIPT_VERSION = _file_version("static/share/tg-dock.js")
PRESS_SCRIPT_VERSION = _file_version("static/share/b-press.js")
FONT_V_PLACEHOLDER = "__FONT_V__"


def _fonts_dir_version() -> str:
    import hashlib
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "static" / "fonts" / "glide-public"
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.woff2")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


PUBLIC_FONTS_ASSET_VERSION = _fonts_dir_version()


def public_fonts_head_html() -> str:
    """Self-hosted Golos Text + Dela Gothic One для публичных страниц стиля B."""
    v = PUBLIC_FONTS_ASSET_VERSION
    return (
        f'  <link rel="preload" href="/static/fonts/glide-public/dela-gothic-one-cyr-lat.woff2?v={v}" '
        f'as="font" type="font/woff2" crossorigin />\n'
        f'  <link rel="preload" href="/static/fonts/glide-public/dela-gothic-one-lat.woff2?v={v}" '
        f'as="font" type="font/woff2" crossorigin />\n'
        f'  <link rel="stylesheet" href="/static/shared/glide-public-fonts.css?v={v}" />'
    )


def public_fonts_css_text() -> str:
    """Текст glide-public-fonts.css с подставленным ?v= (тот же, что в preload и @font-face)."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "static" / "shared" / "glide-public-fonts.css"
    return path.read_text(encoding="utf-8").replace(FONT_V_PLACEHOLDER, PUBLIC_FONTS_ASSET_VERSION)


def esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def b_photo_url(key: Any) -> str | None:
    """URL варианта фото по ключу хранилища: CDN, если настроен, иначе публичный прокси."""
    from src.application.photo_cdn import public_photo_url
    from src.shared.config import get_settings

    raw = str(key or "").strip()
    if not raw:
        return None
    # get_settings(), не Settings(): конструктор перечитывает .env, а фото на странице десятки.
    return public_photo_url(raw, get_settings().photo_cdn_base_url)


def media_url(media: Mapping[str, Any] | None, *, size: str = "hero") -> str | None:
    """Публичный URL варианта фото. ``size``: hero (1600) для героя, card (800) для плиток."""
    if not isinstance(media, Mapping):
        return None
    variants = media.get("variants")
    if not isinstance(variants, Mapping):
        return None
    order = ("hero", "card", "thumb") if size == "hero" else ("card", "hero", "thumb")
    for key in order:
        url = _variant_public_url(variants.get(key))
        if url:
            return url
    return None


_VARIANT_WIDTHS = {"thumb": 320, "card": 800, "hero": 1600}
_HERO_SIZES = "100vw"
_TILE_SIZES = "(max-width: 640px) calc((100vw - 42px) / 2), 230px"


def _variant_public_url(raw: Any) -> str | None:
    key = str(raw or "").strip()
    if not key:
        return None
    if key.lower().startswith(("https://", "http://", "/")):
        return key
    return b_photo_url(key)


def _photo_srcset(variants: Mapping[str, Any], *, layout: str) -> tuple[str | None, str]:
    """``src`` и атрибуты ``srcset``/``sizes`` для героя или плитки (экран ~390px)."""
    order = ("thumb", "card", "hero") if layout == "hero" else ("thumb", "card")
    src_order = ("card", "thumb", "hero") if layout == "hero" else ("card", "thumb")
    parts: list[str] = []
    seen: set[str] = set()
    for name in order:
        url = _variant_public_url(variants.get(name))
        if not url or url in seen:
            continue
        seen.add(url)
        parts.append(f"{esc(url)} {_VARIANT_WIDTHS[name]}w")
    src = None
    for name in src_order:
        url = _variant_public_url(variants.get(name))
        if url:
            src = url
            break
    if not src:
        return None, ""
    if len(parts) < 2:
        return src, ""
    sizes = _HERO_SIZES if layout == "hero" else _TILE_SIZES
    return src, f' srcset="{", ".join(parts)}" sizes="{sizes}"'


def hero_html(
    *,
    title: str,
    sub_html: str = "",
    kicker: str = "",
    photo_url: str | None = None,
    photo_alt: str = "",
    toned: bool = False,
    bar_html: str = "",
    variant: str = "",
    title_break: str = "",
    extra_html: str = "",
    sub_class: str = "",
    photo_variants: Mapping[str, Any] | None = None,
) -> str:
    """Герой на всю ширину: фото (или разметка катка), градиент, панель сверху, текст снизу."""
    klass = "b-hero"
    if variant:
        klass += f" b-hero--{variant}"
    src = photo_url
    srcset_attrs = ""
    if isinstance(photo_variants, Mapping):
        src, srcset_attrs = _photo_srcset(photo_variants, layout="hero")
    if toned and src:
        klass += " b-toned-wrap"
    if src:
        img_class = "b-hero__img b-toned" if toned else "b-hero__img"
        media = (
            f'<img class="{img_class}" src="{esc(src)}"{srcset_attrs} alt="{esc(photo_alt)}" '
            'width="1600" height="900" fetchpriority="high" decoding="async" />'
        )
    else:
        media = rink_motif_svg(extra_class="b-hero__motif")
    kicker_html = f'<p class="b-hero__kicker">{esc(kicker)}</p>' if kicker else ""
    title_class = "b-hero__title b-hero__title--long" if len(title) > 18 else "b-hero__title"
    # «Минск<br>на льду»: перенос перед хвостом, если он задан и стоит в конце заголовка.
    if title_break and title.endswith(" " + title_break) and len(title) <= 24:
        head = title[: -len(title_break) - 1]
        title_html = f"{esc(head)}<br>{esc(title_break)}"
        title_class = "b-hero__title"
    else:
        title_html = esc(title)
    sub_cls = f"b-hero__sub {sub_class}".strip()
    sub = f'<p class="{sub_cls}">{sub_html}</p>' if sub_html else ""
    return (
        f'<header class="{klass}">{media}<div class="b-hero__shade"></div>'
        f'<div class="b-hero__bar">{bar_html}</div>'
        f'<div class="b-hero__copy">{kicker_html}<h1 class="{title_class}">{title_html}</h1>{sub}{extra_html}</div>'
        "</header>"
    )


def brand_link(*, end: bool = False) -> str:
    klass = "b-brand b-brand--end" if end else "b-brand"
    return f'<a class="{klass}" href="/">{esc(t("brand.mark"))}</a>'


def back_pill(href: str, label: str) -> str:
    return f'<a class="b-pill b-pill--back" href="{esc(href)}">{icon_svg("back")}{esc(label)}</a>'


def city_pill(href: str, label: str) -> str:
    return f'<a class="b-pill b-pill--end" href="{esc(href)}">{esc(label)}{icon_svg("down")}</a>'


def section(title: str, body: str, *, aside_html: str = "", klass: str = "", sec_id: str = "") -> str:
    if not body:
        return ""
    id_attr = f' id="{esc(sec_id)}"' if sec_id else ""
    extra = f" {klass}" if klass else ""
    aside = aside_html if aside_html else ""
    head = f'<div class="b-sec__head"><h2 class="b-h2">{esc(title)}</h2>{aside}</div>'
    return f'<section class="b-sec{extra}"{id_attr}>{head}{body}</section>'


def tile_html(
    *,
    href: str,
    name: str,
    line: str,
    photo_url: str | None,
    photo_alt: str = "",
    toned: bool = False,
    badge: str = "",
    badge_kind: str = "",
    photo_variants: Mapping[str, Any] | None = None,
) -> str:
    """Карточка с фото (или разметкой катка) и двумя строками — для сеток и каруселей."""
    src = photo_url
    srcset_attrs = ""
    if isinstance(photo_variants, Mapping):
        src, srcset_attrs = _photo_srcset(photo_variants, layout="tile")
    if src:
        img_class = "b-toned" if toned else ""
        wrap = " b-toned-wrap" if toned else ""
        media = (
            f'<span class="b-tile__media{wrap}"><img class="{img_class}" src="{esc(src)}"{srcset_attrs} '
            f'alt="{esc(photo_alt)}" loading="lazy" decoding="async" width="460" height="240" />'
        )
    else:
        media = f'<span class="b-tile__media">{rink_motif_svg(small=True)}'
    if badge:
        kind = f" b-badge--{badge_kind}" if badge_kind else ""
        if not photo_url and badge_kind != "time":
            kind += " b-badge--light"
        media += f'<span class="b-badge{kind}">{esc(badge)}</span>'
    media += "</span>"
    return (
        f'<a class="b-tile" href="{esc(href)}">{media}'
        f'<span class="b-tile__body"><span class="b-tile__name">{esc(name)}</span>'
        f'<span class="b-tile__line">{esc(line)}</span></span></a>'
    )


_SHARE_ICONS = {
    "tg": "Telegram",
    "vb": "Viber",
    "wa": "WhatsApp",
    "vk": "VK",
}


def share_html(
    share: Mapping[str, str],
    *,
    telegram_url: str | None,
    story_image_url: str | None = None,
    zovi_path: str | None = None,
    telegram_link_only: bool = False,
) -> str:
    """«Позвать друзей» без JS: открытый ряд мессенджеров, под ним «Открыть в Telegram».

    С JS страницы показывают окно шеринга Mini App (кнопка подборки, «Позвать»), а этот блок
    прячет ``catalog-list-share.css``. Раскрывашки нет: в сетке из двух колонок она ломалась.
    """

    url = share["share_url"]
    body = share.get("share_body") or ""
    full = f"{body}\n{url}" if body else url
    tg = f"https://t.me/share/url?url={quote(url, safe='')}"
    if not telegram_link_only and body:
        tg += f"&text={quote(body, safe='')}"
    links = {
        "tg": (tg, True),
        "vb": (f"viber://forward?text={quote(full, safe='')}", False),
        "wa": (f"https://wa.me/?text={quote(full, safe='')}", True),
        "vk": (f"https://vk.com/share.php?url={quote(url, safe='')}", True),
    }
    row = "".join(
        f'<a href="{esc(href)}"' + (' rel="noopener" target="_blank"' if blank else "") + f">{esc(_SHARE_ICONS[k])}</a>"
        for k, (href, blank) in links.items()
    )
    row += f'<button type="button" data-copy="{esc(full)}">Скопировать</button>'
    extra: list[str] = []
    if story_image_url:
        extra.append(
            f'<a class="share__story" href="{esc(story_image_url)}" download="glide-story.png">'
            f"{esc(t('share.story'))}</a>"
        )
    if zovi_path:
        extra.append(f'<a href="{esc(zovi_path)}">{esc(t("share.card"))}</a>')
    extra_html = f'<div class="b-share__extra">{"".join(extra)}</div>' if extra else ""
    title = esc(t("cta.invite_friends"))
    bot = (
        f'<a class="b-btn b-share__bot" href="{esc(telegram_url)}">Открыть в Telegram</a>' if telegram_url else ""
    )
    return (
        f'<section class="b-share" aria-label="{title}">'
        f'<p class="b-share__title">{title}</p>'
        f'<div class="b-share__row share__row">{row}</div>{extra_html}{bot}</section>'
    )


def trainer_rows_html(
    trainers: list[Mapping[str, Any]],
    *,
    href_for: Any,
    cta: str | None = None,
) -> str:
    """Тренеры строками (TASK-265): лицо, имя, занятие и цена «от», справа — CTA.

    Вся строка — ссылка в Telegram на карточку тренера (``href_for(trainer)``), как тап по
    тренеру на карточке катка в Mini App. Без фото — первая буква имени, не пустой кружок.

    ``cta`` — фиксированная подпись справа (например ``t("cta.go")`` на SSR-карточке места).
    Иначе «Записаться» / «Написать» по ``can_book``.
    """
    rows: list[str] = []
    for trainer in trainers:
        href = href_for(trainer)
        if not href:
            continue
        photo = trainer.get("photo_url")
        if photo:
            ava = f'<img class="b-row__ava" src="{esc(photo)}" alt="" width="44" height="44" loading="lazy" decoding="async" fetchpriority="low" />'
        else:
            ava = f'<span class="b-row__ava b-row__ava--mono" aria-hidden="true">{esc(trainer.get("initial") or "")}</span>'
        line = str(trainer.get("line") or "")
        line_html = f'<span class="b-row__line">{esc(line)}</span>' if line else ""
        row_cta = cta if cta else (t("cta.enroll") if trainer.get("can_book") else t("cta.write"))
        rows.append(
            f'<div class="b-row b-row--coach">{ava}'
            f'<span class="b-row__body"><a class="b-row__title b-row__link" href="{esc(href)}">{esc(trainer.get("name"))}</a>'
            f"{line_html}</span>"
            f'<span class="b-row__cta">{esc(row_cta)}</span></div>'
        )
    if not rows:
        return ""
    return f'<div class="b-list">{"".join(rows)}</div>'


_TG_PLANE_SVG = (
    '<svg class="b-tgbtn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M21.5 4.5L2.5 11.8l6.2 2.1 2.2 6.4 3.3-4.1 5.4 4z"/><path d="M8.7 13.9l12.8-9.4"/></svg>'
)
_TG_MAP_SVG = (
    '<svg class="b-tghint__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/></svg>'
)


def telegram_button_html(href: str, *, short: bool = False) -> str:
    """Синяя «Открыть в Telegram» (TASK-278). ``short`` — ещё и «Telegram» для узкой кнопки рядом с «Позвать»."""
    label = f'<span class="b-tgbtn__long">{esc(t("tg.open"))}</span>'
    if short:
        label += f'<span class="b-tgbtn__short">{esc(t("tg.open_short"))}</span>'
    # aria-label: на узком экране рядом с «Позвать» остаётся только самолётик.
    return f'<a class="b-tgbtn tg-out" href="{esc(href)}" aria-label="{esc(t("tg.open"))}">{_TG_PLANE_SVG}{label}</a>'


def telegram_hint_html(text: str) -> str:
    """Тихая строка под кнопкой: что ждёт в Telegram (карта). Пустая подпись — строки нет."""
    if not text:
        return ""
    return f'<span class="b-tghint tg-out">{_TG_MAP_SVG}{esc(text)}</span>'


def city_map_hint(places: list[Mapping[str, Any]]) -> str:
    """«там все 10 катков на карте» — только если на карте действительно все катки города."""
    from src.application.ice_city_day import plural_ru

    rinks = [p for p in places if str(p.get("venue_type") or "ice") in ("ice", "outdoor")]
    if not rinks:
        return t("tg.map_all")
    on_map = [p for p in rinks if p.get("latitude") is not None and p.get("longitude") is not None]
    if len(on_map) != len(rinks):
        return t("tg.map_all")
    n = len(rinks)
    if n == 1:
        return t("tg.map_city_one")
    return t("tg.map_city_n", n=n, word=plural_ru(n, "каток", "катка", "катков"))


def telegram_dock_html(href: str | None, *, hint: str = "") -> str:
    """Плашка «Открыть в Telegram» (TASK-278): в потоке, после прокрутки — пилюля (tg-dock.js)."""
    if not href:
        return ""
    return (
        '<div class="b-tgdock-host tg-out"><div class="b-tgdock__spacer" aria-hidden="true"></div>'
        '<nav class="b-tgdock" aria-label="Telegram"><div class="b-tgdock__inner">'
        f"{telegram_button_html(href, short=True)}{telegram_hint_html(hint)}</div></nav></div>"
    )


def telegram_dock_script_html() -> str:
    """Скрипт плашки Telegram — только вне Mini App."""
    v = DOCK_SCRIPT_VERSION
    return f'<script defer src="/static/share/tg-dock.js?v={esc(v)}"></script>'


def b_press_script_html() -> str:
    """Отклик нажатия на публичке (iOS + защита от press при скролле)."""
    v = PRESS_SCRIPT_VERSION
    return f'<script defer src="/static/share/b-press.js?v={esc(v)}"></script>'
