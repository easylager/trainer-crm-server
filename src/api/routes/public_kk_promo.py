"""Короткая рекламная ссылка «Кто кого»: /kk?s=<метка> — превью для соцсетей и вход в Telegram.

Без базы: метка только вшивается в ссылку на бота (start_param ``kks_<метка>``), считает её сама игра.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from src.application.hockey_promo import clean_src
from src.application.hockey_teams import TEAMS, logo_path
from src.application.place_links import public_telegram_entry_link
from src.application.style_b import _file_version, public_fonts_head_html
from src.shared.config import Settings

router = APIRouter(tags=["public-kk-promo"])

DEFAULT_SRC = "site"
_TITLE = "Кто кого — угадай, кто победит в матче Динамо-Минск"
_DESCRIPTION = "Тапни за команду, набирай очки и сравнивайся с друзьями. Бесплатно, в Telegram."
_LOGO = "/logos/01-icon/glide-icon-teal-square-512.png"
# Картинка превью 1200×630 и лёгкие копии логотипов для ленты: static/landing/kk, отдаёт /landing/{path}.
_KK_DIR = Path(__file__).resolve().parents[3] / "static" / "landing" / "kk"
_OG_REL = "static/landing/kk/og.png"
_OG_URL = "/landing/kk/og.png"
_OG_ALT = "Кто кого: стикер игры, шайба и логотипы клубов КХЛ и Экстралиги"
_RAIL_LOGO_URL = "/landing/kk/logos"
# Краулеры превью на t.me не уводим: иначе картинка и заголовок возьмутся с чужой страницы.
_PREVIEW_BOTS = ("telegrambot", "twitterbot", "facebookexternalhit", "slackbot", "vkshare", "discordbot", "whatsapp")


def _is_preview_bot(request: Request) -> bool:
    agent = (request.headers.get("user-agent") or "").lower()
    return any(bot in agent for bot in _PREVIEW_BOTS)


# Лента: два ряда навстречу друг другу. Передний — крупнее и быстрее, задний — мельче, медленнее и
# приглушён: так получается глубина без размытия и теней-подушек. Петля бесшовная: в треке набор
# дважды, сдвиг ровно на половину (у каждого диска отступ справа, поэтому половина = n × шаг).
# Скорость считается от длины ряда: передний ~23 px/с, задний ~16 px/с — логотип идёт через экран
# телефона 15–25 с, через десктоп — около минуты. Разгон: обёртка .e за 2,4 с отъезжает навстречу
# движению по квадратичной кривой, сумма скоростей растёт от нуля до крейсерской без рывка.
_A_DISC, _A_GAP, _A_DUR = 56, 20, 120
_B_DISC, _B_GAP, _B_DUR = 44, 18, 140
_EASE_S = 2.4


def _rail_css(n: int) -> str:
    a_shift = n * (_A_DISC + _A_GAP) / _A_DUR * _EASE_S / 2
    b_shift = n * (_B_DISC + _B_GAP) / _B_DUR * _EASE_S / 2
    return (
        ".rail{position:relative;overflow:hidden;width:100%;max-width:1440px;margin:0 auto;padding:28px 0 10px;"
        "animation:fade 1.2s ease-out both}"
        # Края гаснут в цвет фона: накладкой, а не mask-image — одинаково во всех встроенных браузерах.
        ".rail:before,.rail:after{content:'';position:absolute;top:0;bottom:0;width:18%;max-width:200px;z-index:1;"
        "pointer-events:none}"
        ".rail:before{left:0;background:linear-gradient(90deg,#1747b5,rgba(23,71,181,0))}"
        ".rail:after{right:0;background:linear-gradient(270deg,#1747b5,rgba(23,71,181,0))}"
        ".r+.r{margin-top:14px}"
        ".t{display:flex;width:max-content;will-change:transform;animation:crawl linear infinite}"
        ".t img{flex:none;display:block;box-sizing:border-box;border-radius:50%;background:#fff;object-fit:contain;"
        "box-shadow:0 2px 8px rgba(6,22,70,.28)}"
        f".a .t{{animation-duration:{_A_DUR}s}}"
        f".a img{{width:{_A_DISC}px;height:{_A_DISC}px;padding:8px;margin-right:{_A_GAP}px}}"
        f".b{{opacity:.72}}.b .t{{animation-duration:{_B_DUR}s;animation-direction:reverse}}"
        f".b img{{width:{_B_DISC}px;height:{_B_DISC}px;padding:6px;margin-right:{_B_GAP}px}}"
        f".a .e{{animation:ea {_EASE_S}s cubic-bezier(.33,.67,.67,1) both}}"
        f".b .e{{animation:eb {_EASE_S}s cubic-bezier(.33,.67,.67,1) both}}"
        "@keyframes crawl{from{transform:translate3d(0,0,0)}to{transform:translate3d(-50%,0,0)}}"
        f"@keyframes ea{{from{{transform:translate3d(0,0,0)}}to{{transform:translate3d({a_shift:.1f}px,0,0)}}}}"
        f"@keyframes eb{{from{{transform:translate3d(0,0,0)}}to{{transform:translate3d(-{b_shift:.1f}px,0,0)}}}}"
    )


# Герой: заставка игры (шайба влетает в стикер «КТО КОГО?», стикер качается), затем текст и кнопка.
# Один раз, 0–900 мс: шайба 80–500, стикер 480–760, текст 380–800, кнопка 480–900.
_PAGE_CSS = (
    ":root{color-scheme:light}"
    "html{-webkit-text-size-adjust:100%}"
    "body{margin:0;min-height:100vh;min-height:100dvh;display:flex;flex-direction:column;background:#1747b5;"
    "color:#fff;font:500 17px/1.45 'Golos Text',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;"
    "text-align:center;-webkit-tap-highlight-color:transparent}"
    "main{flex:1 0 auto;display:flex;flex-direction:column;align-items:center;justify-content:center;"
    "padding:28px 16px 48px;box-sizing:border-box}"
    ".brand{display:flex;align-items:center;justify-content:center;gap:8px;margin:0;min-height:64px}"
    ".puck{position:relative;flex:none;width:46px;height:29px;border-radius:50%;background:#0d0c0b;"
    "box-shadow:inset 0 -6px 0 #3a3632;animation:fly .42s cubic-bezier(.3,.1,.5,1) .08s both}"
    ".puck:after{content:'';position:absolute;left:9px;top:4px;width:15px;height:6px;border-radius:50%;"
    "background:rgba(255,255,255,.38)}"
    ".tag{display:block;height:56px;padding:0 18px;border-radius:14px;background:#ffd23f;color:#0d1424;"
    "font:400 30px/56px 'Dela Gothic One','Golos Text',system-ui,sans-serif;white-space:nowrap;"
    "transform:rotate(-3deg);animation:wob .28s ease-out .48s both}"
    ".vh{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}"
    "main p{max-width:340px;margin:22px 0 28px;color:rgba(255,255,255,.92);animation:up .42s ease-out .38s both}"
    ".go{display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;min-height:56px;"
    "width:100%;max-width:320px;padding:0 28px;border-radius:16px;background:#ffd23f;color:#0d1424;"
    "font:700 17px/1.2 'Golos Text',system-ui,sans-serif;text-decoration:none;"
    "transition:background-color .15s ease-out,transform .15s ease-out;animation:up .42s ease-out .48s both}"
    "@media (hover:hover){.go:hover{background:#ffdc5e}}"
    ".go:active{transform:translateY(1px)}"
    ".go:focus{outline:3px solid #fff;outline-offset:3px}"
    ".go:focus:not(:focus-visible){outline:none}"
    "@keyframes fade{from{opacity:0}to{opacity:1}}"
    "@keyframes up{from{opacity:0;transform:translate3d(0,8px,0)}to{opacity:1;transform:none}}"
    "@keyframes fly{0%{transform:translateX(-160px) rotate(-200deg) scaleX(.7);opacity:0}20%{opacity:1}"
    "80%{transform:translateX(3px) rotate(0) scaleX(1)}100%{transform:none}}"
    "@keyframes wob{0%{transform:rotate(-3deg)}30%{transform:rotate(-8deg) scale(1.06)}65%{transform:rotate(1deg)}"
    "100%{transform:rotate(-3deg)}}"
    "@media (max-width:359px){.tag{height:48px;font-size:25px;line-height:48px;padding:0 14px}"
    ".puck{width:38px;height:24px;box-shadow:inset 0 -5px 0 #3a3632}.puck:after{left:7px;top:3px;width:12px;height:5px}}"
)

# Меньше движения: лента стоит ровной композицией (тот же кадр без хода и разгона), заставки нет.
_REDUCED_MOTION_CSS = (
    "@media (prefers-reduced-motion:reduce){"
    ".rail,.r .t,.r .e,.puck,.tag,main p,.go{animation:none}"
    ".t{will-change:auto}.b .t{transform:translate3d(-31px,0,0)}"
    ".go{transition:none}}"
)

_NBSP_AFTER = re.compile(r"(?<![\w-])(в|с|к|и|на|до|за) ", flags=re.IGNORECASE)


def _typeset(text: str) -> str:
    """Неразрывный пробел после коротких предлогов и союзов (свод деталей, §3): «в Telegram» не рвётся."""
    return _NBSP_AFTER.sub(lambda m: m.group(1) + " ", text)


@lru_cache(maxsize=1)
def _rail_logos() -> tuple[str, ...]:
    """Слаги клубов ленты: весь реестр игры, у кого есть логотип, в порядке реестра (Динамо-Минск первым)."""
    return tuple(t.slug for t in TEAMS.values() if logo_path(t.slug).is_file())


@lru_cache(maxsize=1)
def _rail_version() -> str:
    """?v= для логотипов ленты по их содержимому: без него /landing/* отдаётся с no-store."""
    digest = hashlib.sha256()
    for slug in _rail_logos():
        path = _KK_DIR / "logos" / f"{slug}.webp"
        digest.update(slug.encode())
        digest.update(path.read_bytes() if path.is_file() else b"")
    return digest.hexdigest()[:8]


def _logo_src(slug: str) -> str:
    """Лёгкая копия 96 px; если её ещё не собрали (новый клуб) — исходный PNG игры."""
    if (_KK_DIR / "logos" / f"{slug}.webp").is_file():
        return f"{_RAIL_LOGO_URL}/{slug}.webp?v={_rail_version()}"
    return f"/static/webapp/hockey-logos/{slug}.png"


def _rail_row(slugs: list[str], cls: str, size: int) -> str:
    imgs = "".join(
        f'<img src="{html.escape(_logo_src(s))}" alt="" width="{size}" height="{size}" decoding="async">' for s in slugs
    )
    return f'<div class="r {cls}"><div class="e"><div class="t">{imgs}{imgs}</div></div></div>'


def _rail_html() -> str:
    """Лента логотипов клубов игры над заголовком: чисто декоративная, без скриптов."""
    slugs = list(_rail_logos())
    if not slugs:
        return ""
    half = len(slugs) // 2
    # Задний ряд начинается с середины реестра: соседние логотипы в рядах не совпадают.
    back = slugs[half:] + slugs[:half]
    return f'<div class="rail" aria-hidden="true">{_rail_row(slugs, "a", _A_DISC)}{_rail_row(back, "b", _B_DISC)}</div>'


@router.get("/kk", include_in_schema=False)
async def get_kk_promo_page(request: Request, s: str = Query("", max_length=64)) -> HTMLResponse:
    src = clean_src(s) or DEFAULT_SRC
    cfg = Settings()  # type: ignore[call-arg]
    base = (cfg.webapp_base_url or "").strip().rstrip("/")
    go = public_telegram_entry_link(cfg, start_param=f"kks_{src}") or f"{base}/webapp/kto-kogo?src={src}"
    e = html.escape
    if (_KK_DIR / "og.png").is_file():
        image = f"{base}{_OG_URL}?v={_file_version(_OG_REL)}"
        og_image = (
            f'<meta property="og:image" content="{e(image)}">\n'
            '<meta property="og:image:width" content="1200">\n'
            '<meta property="og:image:height" content="630">\n'
            f'<meta property="og:image:alt" content="{e(_OG_ALT)}">\n'
            '<meta name="twitter:card" content="summary_large_image">\n'
            f'<meta name="twitter:image" content="{e(image)}">'
        )
    else:
        og_image = (
            f'<meta property="og:image" content="{e(base + _LOGO)}">\n<meta name="twitter:card" content="summary">'
        )
    hop = ""
    if not _is_preview_bot(request):
        hop = (
            "<script>if(/Android|iPhone|iPad|iPod/i.test(navigator.userAgent)){"
            f"location.replace({json.dumps(go)});}}</script>"
        )
    css = _PAGE_CSS + _rail_css(len(_rail_logos())) + _REDUCED_MOTION_CSS
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="theme-color" content="#1747b5">
<title>{e(_TITLE)}</title>
<meta name="description" content="{e(_DESCRIPTION)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{e(_TITLE)}">
<meta property="og:description" content="{e(_DESCRIPTION)}">
{og_image}
<meta name="robots" content="noindex">
{public_fonts_head_html()}
<style>{css}</style>
</head><body>{_rail_html()}<main><h1 class="brand"><span class="puck" aria-hidden="true"></span><span class="tag" aria-hidden="true">КТО КОГО?</span><span class="vh">Кто кого</span></h1>
<p>{e(_typeset(_DESCRIPTION))}</p>
<a class="go" href="{e(go)}">Открыть в Telegram</a></main>{hop}
</body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=300"})
