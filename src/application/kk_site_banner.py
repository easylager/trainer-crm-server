"""Баннер игры «КТО КОГО» на главной и страницах городов (холст ULKL8uBbgyZBEznFLqgah2, «Баннер B», 2026-11-20).

Не матч и не ход: короткое приглашение на лендинг ``/kk``. Лента клубов, шайба со стикером, одна фраза и стрелка —
подробности и «Играть в Telegram» живут на самом лендинге. Стили — ``.kkb`` в ``static/shared/glide-components.css``.
"""

from __future__ import annotations

import html

from src.application import hockey_event

# Заставка (шайба влетает в стикер) — один раз, когда баннер показался на экране; без IntersectionObserver — сразу.
_INTRO_SCRIPT = (
    "<script>(function(){var b=document.querySelector('.kkb[data-kkb-intro]');if(!b)return;"
    "if(!('IntersectionObserver' in window)){b.classList.add('is-in');return;}"
    "var o=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){b.classList.add('is-in');"
    "o.disconnect();}});},{threshold:.4});o.observe(b);})();</script>"
)


def _rail() -> str:
    """Все клубы игры дважды: дорожка сдвигается ровно на половину — петля без шва на любой ширине."""
    from src.api.routes.public_kk_promo import _logo_src, _rail_logos

    imgs = "".join(
        f'<img src="{html.escape(_logo_src(slug))}" alt="" width="34" height="34" loading="lazy" decoding="async">'
        for slug in _rail_logos()
    )
    if not imgs:
        return ""
    return f'<div class="kkb__rail" aria-hidden="true"><div class="kkb__track">{imgs}{imgs}</div></div>'


def kk_banner_html(src: str, *, compact: bool = False, card: bool = False) -> str:
    """Баннер со ссылкой на ``/kk?from=<src>``; игра выключена — пусто. ``compact`` — поменьше; ``card`` — карточкой в ленте матчей."""
    if not hockey_event.enabled():
        return ""
    href = f"/kk?from={html.escape(src)}"
    return (
        f'<a class="kkb{" kkb--sm" if compact else ""}{" kkb--card" if card else ""}" href="{href}" data-kkb-intro aria-label="Игра «КТО КОГО»: хоккейная игра для своей компании">'
        f"{_rail()}"
        '<span class="kkb__body">'
        '<span class="kkb__brand" aria-hidden="true"><span class="kkb__puck"></span><span class="kkb__tag">КТО КОГО?</span></span>'
        '<span class="kkb__row"><span class="kkb__title">Хоккейная игра для своей компании</span>'
        '<span class="kkb__go"><span class="kkb__go-t">Об игре</span><span class="kkb__arrow" aria-hidden="true">→</span></span>'
        "</span></span></a>"
        f"{_INTRO_SCRIPT}"
    )


def kk_banner_section(src: str, title: str = "Хоккей") -> str:
    banner = kk_banner_html(src)
    if not banner:
        return ""
    return f'<section class="b-sec" id="kk"><div class="b-sec__head"><h2 class="b-h2">{html.escape(title)}</h2></div>{banner}</section>'
