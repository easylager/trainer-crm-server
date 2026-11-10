"""Короткая рекламная страница /kk?s=<метка>: превью ссылки, кнопка в Telegram, без доступа к БД."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


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
    assert 'property="og:title"' in page and "Кто кого" in page
    assert 'property="og:description"' in page
    # Первый шаг игры — один тап за команду: превью не обещает «угадай счёт».
    assert 'content="Кто кого — угадай, кто победит в матче Динамо-Минск"' in page
    assert 'content="Тапни за команду, набирай очки и сравнивайся с друзьями. Бесплатно, в Telegram."' in page
    assert "точный счёт" not in page and "угадай счёт" not in page
    assert 'property="og:image" content="https://glide.test/logos/' in page
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
