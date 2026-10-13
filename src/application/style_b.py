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


def esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def b_photo_url(key: Any) -> str | None:
    """URL варианта фото по ключу хранилища: CDN, если настроен, иначе публичный прокси."""
    from src.application.photo_cdn import public_photo_url
    from src.shared.config import Settings

    raw = str(key or "").strip()
    if not raw:
        return None
    return public_photo_url(raw, Settings().photo_cdn_base_url)


def media_url(media: Mapping[str, Any] | None, *, size: str = "hero") -> str | None:
    """Публичный URL варианта фото. ``size``: hero (1600) для героя, card (800) для плиток."""
    if not isinstance(media, Mapping):
        return None
    variants = media.get("variants")
    if not isinstance(variants, Mapping):
        return None
    order = ("hero", "card", "thumb") if size == "hero" else ("card", "hero", "thumb")
    for key in order:
        url = str(variants.get(key) or "").strip()
        if url.lower().startswith(("https://", "http://", "/")):
            return url
    return None


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
) -> str:
    """Герой на всю ширину: фото (или разметка катка), градиент, панель сверху, текст снизу."""
    klass = "b-hero"
    if variant:
        klass += f" b-hero--{variant}"
    if toned and photo_url:
        klass += " b-toned-wrap"
    if photo_url:
        img_class = "b-hero__img b-toned" if toned else "b-hero__img"
        media = (
            f'<img class="{img_class}" src="{esc(photo_url)}" alt="{esc(photo_alt)}" '
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
) -> str:
    """Карточка с фото (или разметкой катка) и двумя строками — для сеток и каруселей."""
    if photo_url:
        img_class = "b-toned" if toned else ""
        wrap = " b-toned-wrap" if toned else ""
        media = (
            f'<span class="b-tile__media{wrap}"><img class="{img_class}" src="{esc(photo_url)}" '
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
    """«Позвать друзей» (бирюза) раскрывает мессенджеры; рядом «В Telegram». Без JS тоже работает."""
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
    invite = (
        '<details class="b-invite">'
        f'<summary class="b-btn b-btn--accent">{esc(t("cta.invite_friends"))}</summary>'
        f'<div class="b-share__row share__row">{row}</div>{extra_html}</details>'
    )
    tg_btn = f'<a class="b-btn" href="{esc(telegram_url)}">В Telegram</a>' if telegram_url else ""
    if tg_btn:
        top = f'<div class="b-btns">{invite}{tg_btn}</div>'
    else:
        top = invite
    return f'<section class="b-share" aria-label="{esc(t("cta.invite_friends"))}">{top}</section>'
