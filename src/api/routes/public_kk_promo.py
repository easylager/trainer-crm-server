"""Страница игры «Кто кого» и рекламные ссылки /kk?s=<метка> для входа в Telegram.

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

from src.application import hockey_event, site_matches
from src.application.hockey_game import POINTS_DIFF, POINTS_EXACT, POINTS_GOALS, POINTS_WINNER
from src.application.hockey_promo import clean_src
from src.application.hockey_teams import TEAMS, logo_path
from src.application.place_links import public_telegram_entry_link
from src.application.public_analytics import public_analytics_head_html_from_settings
from src.application.style_b import _file_version, public_fonts_head_html
from src.shared.config import Settings
from src.shared.html_template import PUBLIC_ICON_LINKS

router = APIRouter(tags=["public-kk-promo"])

DEFAULT_SRC = "site"
_TITLE = "КТО КОГО — угадай, кто победит в матче Динамо-Минск"
_DESCRIPTION = "Тапни за команду, набирай очки и соревнуйся с друзьями. Бесплатно, в Telegram."
_LANDING_DESCRIPTION = (
    "«КТО КОГО» — бесплатная хоккейная игра в Telegram. Угадывай победителей матчей, набирай очки "
    "и создай свою лигу для друзей."
)
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


@lru_cache
def _landing_asset(filename: str) -> str:
    return f"/landing/kk/{filename}?v={_file_version(f'static/landing/kk/{filename}')}"


def _banner(filename: str, alt: str) -> str:
    return (
        f'<img src="{_landing_asset(filename)}" alt="{html.escape(alt)}" '
        'width="400" height="320" loading="lazy" decoding="async">'
    )


# Лента лендинга: один тихий ряд над шапкой, ~24 px/с — логотип идёт через десктоп примерно минуту.
_LANDING_DISC, _LANDING_GAP, _LANDING_SPEED = 36, 18, 24


def _landing_rail_html() -> str:
    """Лента клубов над шапкой лендинга: декоративная, без скриптов; петля — набор дважды, сдвиг на половину."""
    slugs = list(_rail_logos())
    if not slugs:
        return ""
    imgs = "".join(
        f'<img src="{html.escape(_logo_src(s))}" alt="" width="{_LANDING_DISC}" height="{_LANDING_DISC}" decoding="async">'
        for s in slugs
    )
    duration = round(len(slugs) * (_LANDING_DISC + _LANDING_GAP) / _LANDING_SPEED)
    return (
        f'<div class="kk-rail" aria-hidden="true" style="--kk-rail-dur:{duration}s">'
        f'<div class="kk-rail-track">{imgs}{imgs}</div></div>'
    )


def _landing_body(go: str, *, show_matches: bool) -> str:
    play = html.escape(go)
    matches = '<a href="/hockey">Расписание матчей</a>' if show_matches else ""
    return f"""{_landing_rail_html()}
<header class="kk-header kk-frame">
  <a class="kk-glide" href="/">Glide</a>
  <nav class="kk-nav" aria-label="Навигация">
    <a href="#league">Лига друзей</a>{matches}
  </nav>
</header>
<main class="kk-frame">
  <section class="kk-hero" aria-labelledby="kk-title">
    <div>
      <span class="kk-logo">КТО КОГО?</span>
      <h1 id="kk-title">Угадай, кто победит</h1>
      <p>Выбери команду до начала хоккейного матча. За верный выбор получишь очки.</p>
      <a class="kk-button" href="{play}">Играть в Telegram</a>
    </div>
    <figure class="kk-example">
      <figcaption>Пример хода</figcaption>
      <div class="kk-teams">
        <div class="kk-team kk-team--picked">
          <span class="kk-pick" aria-hidden="true">✓</span>
          <img src="{_logo_src('dinamo-minsk')}" width="50" height="50" alt="">
          <b>Динамо-Минск</b>
        </div>
        <div class="kk-team">
          <img src="{_logo_src('lokomotiv')}" width="50" height="50" alt="">
          <b>Локомотив</b>
        </div>
      </div>
      <div class="kk-earned"><span>Победитель угадан</span><strong>+{POINTS_WINNER} очков</strong></div>
      <div class="kk-scoring">
        <h2>Если прогнозируешь счёт</h2>
        <dl>
          <div><dt>Разница шайб</dt><dd>+{POINTS_DIFF}</dd></div>
          <div><dt>Шайбы каждой команды</dt><dd>+{POINTS_GOALS} за команду</dd></div>
          <div><dt>Точный счёт</dt><dd><strong>{POINTS_EXACT} всего</strong></dd></div>
        </dl>
      </div>
      <div class="kk-trump"><span>Козырь недели</span><strong>×2 за один матч</strong></div>
    </figure>
  </section>
  <section class="kk-league" id="league" aria-labelledby="league-title">
    <div>
      <h2 id="league-title">Лига друзей</h2>
      <p>В игре открой «Лиги», нажми «+&nbsp;Создать» и отправь ссылку друзьям. После матчей сравнивайте очки в своей таблице.</p>
      <a class="kk-button" href="{play}">Открыть игру в Telegram</a>
    </div>
    {_banner('friends-league.webp', 'Пример таблицы друзей после четырёх матчей')}
  </section>
  <div class="kk-features">
    <section class="kk-feature">
      <h2>Свои команды</h2>
      <p>Выбирайте, какие матчи идут в зачёт вашей лиги. Можно взять все, только минское «Динамо» или несколько любимых клубов.</p>
      {_banner('favorite-teams.webp', 'Выбор матчей при настройке лиги')}
    </section>
    <section class="kk-feature">
      <h2>Корона каждый месяц</h2>
      <p>Лидер по очкам за месяц получает корону. Все твои короны видны друзьям на «Трибуне».</p>
      {_banner('monthly-crowns.webp', 'Пример «Трибуны» игрока с пятью коронами')}
    </section>
  </div>
</main>
<footer class="kk-footer kk-frame"><a href="/">Катки и массовое катание на Glide</a></footer>
"""


@router.get("/kk", include_in_schema=False)
async def get_kk_promo_page(
    request: Request,
    s: str | None = Query(None, max_length=64),
    from_: str | None = Query(None, alias="from", max_length=16),
) -> HTMLResponse:
    # ``?s=`` — рекламная ссылка (сразу в игру); ``?from=`` — место на самом сайте: лендинг тот же, метка своя.
    src = clean_src(s) or clean_src(from_) or DEFAULT_SRC
    cfg = Settings()  # type: ignore[call-arg]
    base = (cfg.webapp_base_url or "").strip().rstrip("/")
    go = public_telegram_entry_link(cfg, start_param=f"kks_{src}") or f"{base}/webapp/kto-kogo?src={src}"
    e = html.escape
    landing = s is None and hockey_event.enabled(cfg)
    robots = "index, follow" if landing else "noindex"
    title = "КТО КОГО — игра с прогнозами на хоккей | Glide" if landing else _TITLE
    description = _LANDING_DESCRIPTION if landing else _DESCRIPTION
    canonical = (
        f'<link rel="canonical" href="{e(base)}/kk">\n<meta property="og:url" content="{e(base)}/kk">'
        if landing else ""
    )
    analytics = public_analytics_head_html_from_settings() if landing else ""
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
    if not landing and not _is_preview_bot(request):
        hop = (
            "<script>if(/Android|iPhone|iPad|iPod/i.test(navigator.userAgent)){"
            f"location.replace({json.dumps(go)});}}</script>"
        )
    color_scheme = "light dark" if landing else "light"
    theme_color = "#19212a" if landing else "#1747b5"
    if landing:
        style = f'<link rel="stylesheet" href="{_landing_asset("landing.css")}">'
        body = _landing_body(go, show_matches=site_matches.site_enabled(cfg))
    else:
        style = f"<style>{_PAGE_CSS}{_rail_css(len(_rail_logos()))}{_REDUCED_MOTION_CSS}</style>"
        body = f"""{_rail_html()}<main><h1 class="brand"><span class="puck" aria-hidden="true"></span><span class="tag" aria-hidden="true">КТО КОГО?</span><span class="vh">Кто кого</span></h1>
<p>{e(_typeset(_DESCRIPTION))}</p>
<a class="go" href="{e(go)}">Открыть в Telegram</a></main>"""
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="{color_scheme}">
<meta name="theme-color" content="{theme_color}">
<title>{e(title)}</title>
{PUBLIC_ICON_LINKS}
<meta name="description" content="{e(description)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Glide">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
{og_image}
<meta name="robots" content="{robots}">
{canonical}
{public_fonts_head_html()}
{analytics}
{style}
</head><body>{body}{hop}
</body></html>"""
    headers = {"Cache-Control": "public, max-age=300"}
    if not landing:
        headers["Vary"] = "User-Agent"
    return HTMLResponse(page, headers=headers)
