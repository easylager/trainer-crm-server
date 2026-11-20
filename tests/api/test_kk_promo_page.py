"""Короткая рекламная страница /kk?s=<метка>: превью ссылки, кнопка в Telegram, без доступа к БД."""

from __future__ import annotations

import re
from collections import Counter

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.api.routes.public_kk_promo import _KK_DIR
from src.application.hockey_teams import TEAMS, logo_path


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _bot(monkeypatch):
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    monkeypatch.setenv("CLIENT_MINI_APP_SHORT_NAME", "")
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "1")
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.test")


@pytest.mark.asyncio
async def test_page_has_og_tags_and_telegram_button_with_label() -> None:
    async with _client() as client:
        resp = await client.get("/kk", params={"s": "Push1"})
    assert resp.status_code == 200
    page = resp.text
    assert 'property="og:title"' in page and "КТО КОГО" in page
    assert 'property="og:description"' in page
    # Первый шаг игры — один тап за команду: превью не обещает «угадай счёт».
    assert 'content="КТО КОГО — угадай, кто победит в матче Динамо-Минск"' in page
    assert 'content="Тапни за команду, набирай очки и соревнуйся с друзьями. Бесплатно, в Telegram."' in page
    assert "точный счёт" not in page and "угадай счёт" not in page
    assert 'href="https://t.me/glide_test_bot?startapp=kks_push1"' in page
    assert "Открыть в Telegram" in page
    # Мобильный автопереход — скриптом: настольный браузер остаётся на странице с кнопкой.
    assert "location.replace" in page and "Android|iPhone" in page


@pytest.mark.asyncio
async def test_bad_or_missing_label_falls_back_to_site() -> None:
    async with _client() as client:
        for params in ({}, {"s": ""}, {"s": "a"}, {"s": "x" * 17}, {"s": '"><script>alert(1)</script>'}):
            resp = await client.get("/kk", params=params)
            assert resp.status_code == 200
            assert "startapp=kks_site" in resp.text
            assert "<script>alert(1)" not in resp.text


@pytest.mark.asyncio
async def test_public_landing_stays_on_mobile_and_campaign_links_keep_their_tracking(monkeypatch) -> None:
    monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "1")
    monkeypatch.setenv("SITE_MATCHES_ENABLED", "1")
    async with _client() as client:
        plain = await client.get("/kk", headers={"user-agent": _MOBILE_UA})
        campaign = await client.get("/kk?s=insta", headers={"user-agent": _MOBILE_UA})
        landing_assets = re.findall(r'(?:src|href)="(/landing/kk/(?!logos/)[^"]+)"', plain.text)
        assert len(landing_assets) == 4
        for url in landing_assets:
            asset = await client.get(url)
            assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    assert plain.status_code == campaign.status_code == 200
    assert 'sizes="120x120" href="/favicon-120.png?v=2"' in plain.text
    assert 'sizes="120x120" href="/favicon-120.png?v=2"' in campaign.text
    assert '<meta property="og:site_name" content="Glide">' in plain.text
    assert '<a class="kk-glide" href="/">Glide</a>' in plain.text
    assert '<meta name="robots" content="index, follow">' in plain.text
    assert '<link rel="canonical" href="https://glide.test/kk">' in plain.text
    assert 'href="/hockey">Расписание матчей</a>' in plain.text
    assert "startapp=kks_site" in plain.text and "location.replace" not in plain.text
    assert 'href="#league">Лига друзей</a>' in plain.text
    assert 'class="kk-example"' in plain.text and 'class="rail"' not in plain.text
    example = plain.text.split('<figure class="kk-example">', 1)[1].split("</figure>", 1)[0]
    assert "Победитель угадан</span><strong>+20 очков</strong>" in example
    assert "<dt>Разница шайб</dt><dd>+10</dd>" in example
    assert "<dt>Шайбы каждой команды</dt><dd>+10 за команду</dd>" in example
    assert "<dt>Точный счёт</dt><dd><strong>50 всего</strong></dd>" in example
    assert "Козырь недели</span><strong>×2 за один матч</strong>" in example
    assert plain.text.index('id="league"') < plain.text.index("Свои команды") < plain.text.index("Корона каждый месяц")
    assert '<meta name="robots" content="noindex">' in campaign.text
    assert 'class="rail"' in campaign.text and not any(url in campaign.text for url in landing_assets)
    assert 'class="kk-scoring"' not in campaign.text
    assert "startapp=kks_insta" in campaign.text and "location.replace" in campaign.text
    assert "User-Agent" in campaign.headers["Vary"].split(", ")


@pytest.mark.asyncio
async def test_preview_crawler_is_not_redirected() -> None:
    async with _client() as client:
        resp = await client.get("/kk", params={"s": "insta"}, headers={"user-agent": "TelegramBot (like TwitterBot)"})
    assert "location.replace" not in resp.text
    assert 'property="og:title"' in resp.text


@pytest.mark.asyncio
async def test_without_bot_button_leads_to_the_miniapp_page(monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "")
    async with _client() as client:
        resp = await client.get("/kk", params={"s": "insta"})
    assert resp.status_code == 200
    assert 'href="https://glide.test/webapp/kto-kogo?src=insta"' in resp.text


# ---------- лента клубов, превью, вес ----------

_MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Instagram 300.0"


async def _page(**headers) -> str:
    async with _client() as client:
        resp = await client.get("/kk", params={"s": "insta"}, headers=headers)
    assert resp.status_code == 200
    return resp.text


def _rail(page: str) -> str:
    match = re.search(r'<div class="rail"[^>]*>.*?</div></div></div></div>(?=<main>)', page, re.S)
    assert match, "лента клубов пропала со страницы"
    return match.group(0)


@pytest.mark.asyncio
async def test_rail_shows_every_club_with_a_logo_and_is_decorative() -> None:
    rail = _rail(await _page())
    assert rail.startswith('<div class="rail" aria-hidden="true">')
    with_logo = [t.slug for t in TEAMS.values() if logo_path(t.slug).is_file()]
    assert len(with_logo) >= 30
    slugs = re.findall(r'src="/landing/kk/logos/([a-z-]+)\.webp\?v=[0-9a-f]{8}"', rail)
    # Два ряда, в каждом набор дважды (бесшовная петля): каждый клуб ровно четыре раза, чужих нет.
    assert Counter(slugs) == {slug: 4 for slug in with_logo}
    imgs = re.findall(r"<img [^>]*>", rail)
    assert len(imgs) == 4 * len(with_logo)
    for tag in imgs:
        assert 'alt=""' in tag and 'decoding="async"' in tag
        assert re.search(r'width="\d+" height="\d+"', tag)


def test_every_rail_logo_has_a_light_copy_and_the_game_pngs_stay() -> None:
    light = _KK_DIR / "logos"
    for team in TEAMS.values():
        if logo_path(team.slug).is_file():
            copy = light / f"{team.slug}.webp"
            assert copy.is_file(), f"нет {copy.name}: python scripts/build_kk_promo_logos.py"
            assert copy.stat().st_size < 8_000
    assert sum(p.stat().st_size for p in light.glob("*.webp")) < 150_000


@pytest.mark.asyncio
async def test_rail_logo_and_preview_image_are_served_with_long_cache() -> None:
    page = await _page(**{"user-agent": "TelegramBot (like TwitterBot)"})
    logo = re.search(r'src="(/landing/kk/logos/[^"]+)"', page).group(1)
    image = re.search(r'property="og:image" content="https://glide\.test(/landing/kk/og\.png\?v=\w+)"', page).group(1)
    async with _client() as client:
        for url, kind in ((logo, "image/webp"), (image, "image/png")):
            resp = await client.get(url)
            assert resp.status_code == 200, url
            assert resp.headers["content-type"] == kind
            assert "immutable" in resp.headers["cache-control"]
    assert (_KK_DIR / "og.png").stat().st_size <= 150_000


@pytest.mark.asyncio
async def test_preview_is_a_large_card() -> None:
    page = await _page()
    assert '<meta property="og:image:width" content="1200">' in page
    assert '<meta property="og:image:height" content="630">' in page
    assert '<meta name="twitter:card" content="summary_large_image">' in page
    assert re.search(r'<meta name="twitter:image" content="https://glide\.test/landing/kk/og\.png\?v=\w+">', page)
    assert 'property="og:image:alt"' in page
    assert '<meta name="robots" content="noindex">' in page


@pytest.mark.asyncio
async def test_page_has_no_third_party_hosts_and_stays_light() -> None:
    page = await _page()
    hosts = set(re.findall(r"https?://([^/\"'\s)]+)", page))
    assert hosts <= {"t.me", "glide.test"}
    # Наш домен — только в метатегах превью (crawler-у нужен абсолютный адрес), не в разметке страницы.
    body = page.split("</head>", 1)[1]
    assert set(re.findall(r"https?://([^/\"'\s)]+)", body)) == {"t.me"}
    assert len(page.encode()) < 25_000


@pytest.mark.asyncio
async def test_motion_has_a_reduced_variant_and_uses_only_transform_and_opacity() -> None:
    page = await _page()
    css = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    reduced = re.search(r"@media \(prefers-reduced-motion:reduce\)\{(.*)\}", css)
    assert reduced, "нет варианта для «меньше движения»"
    assert ".r .t" in reduced.group(1) and "animation:none" in reduced.group(1)
    for frames in re.findall(r"@keyframes \w+\{(.*?\})\}", css):
        props = set(re.findall(r"([a-z-]+):", frames))
        assert props <= {"transform", "opacity"}, props


@pytest.mark.asyncio
async def test_hero_keeps_texts_and_an_accessible_button() -> None:
    page = await _page()
    assert '<span class="tag" aria-hidden="true">КТО КОГО?</span><span class="vh">Кто кого</span></h1>' in page
    # Тот же текст, только «в Telegram» и короткие слова не отрываются от следующего.
    assert "<p>Тапни за команду, набирай очки и соревнуйся с друзьями. Бесплатно, в Telegram.</p>" in page
    assert ">Открыть в Telegram</a>" in page
    assert "min-height:56px" in page and ".go:focus{outline:3px solid #fff" in page


@pytest.mark.asyncio
@pytest.mark.parametrize("via_start", [False, True])
async def test_mobile_browser_hops_and_preview_bot_does_not(monkeypatch, via_start) -> None:
    monkeypatch.setenv("PUBLIC_ENTRY_VIA_START", "1" if via_start else "0")
    go = (
        "https://t.me/glide_test_bot?start=kks_insta" if via_start else "https://t.me/glide_test_bot?startapp=kks_insta"
    )
    mobile = await _page(**{"user-agent": _MOBILE_UA})
    assert f'href="{go}"' in mobile and f'location.replace("{go}")' in mobile
    for bot in ("TelegramBot (like TwitterBot)", "facebookexternalhit/1.1", "WhatsApp/2.23"):
        page = await _page(**{"user-agent": bot})
        assert f'href="{go}"' in page
        assert "<script" not in page and "location.replace" not in page
        assert _rail(page)


@pytest.mark.asyncio
async def test_site_placement_keeps_the_landing_and_labels_the_game_link(monkeypatch) -> None:
    """``?from=`` — место на сайте: та же индексируемая страница, но кнопка в игру несёт свою метку."""
    monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "1")
    async with _client() as client:
        page = (await client.get("/kk", params={"from": "sitehub"})).text
        junk = (await client.get("/kk", params={"from": "a b"})).text
    assert 'class="kk-hero"' in page and "index, follow" in page
    assert "kks_sitehub" in page and "kks_site" in junk and "kks_a" not in junk
