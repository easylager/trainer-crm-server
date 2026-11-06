"""TASK-350: страница тренера ``/t/{id}-{slug}`` — та же логика, что у карточки тренера в Mini App."""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.site_trainer_page import parse_trainer_ref, trainer_path, trainer_slug
from src.infrastructure.db.models import SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE
from tests.api.test_arena_trainer_windows import _slot
from tests.api.test_public_place_page import _place
from tests.api.test_site_trainers import _trainer_on
from tests.api.test_webapp_client_miniapp_integration import _ensure_trainer_subscription_tier


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.example")
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")


def test_slug_is_id_plus_transliterated_name() -> None:
    assert trainer_slug(9, "Александр Гаевский") == "9-aleksandr-gaevskiy"
    assert trainer_slug(9, "🪴 Максим") == "9-maksim"
    assert trainer_slug(9, "Тренер") == "9"
    assert trainer_path(9, "") == "/t/9"
    assert parse_trainer_ref("9-aleksandr-gaevskiy") == 9
    assert parse_trainer_ref("9") == 9
    assert parse_trainer_ref("abc") is None
    assert parse_trainer_ref("0-x") is None


async def _listed(db_session, client, *, tier: str | None) -> tuple[dict, int, str]:
    place = await _place(db_session)
    first = f"Анна{uuid.uuid4().hex[:4]}"
    tid = await _trainer_on(db_session, client, place, first_name=first)
    await db_session.execute(text("UPDATE trainers SET telegram_username = 'anna_coach' WHERE id = :t"), {"t": tid})
    if tier:
        await _ensure_trainer_subscription_tier(db_session, tid, tier)
    await db_session.commit()
    return place, tid, f"{first} Тренерова"


@pytest.mark.asyncio
async def test_listed_trainer_with_booking_has_page_windows_and_book_cta(app_use_test_db, db_session) -> None:
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        await _slot(db_session, tid, days=2, hour=12, arena_id=place["arena_id"])
        await db_session.commit()
        path = trainer_path(tid, name)
        short = await client.get(f"/t/{tid}", follow_redirects=False)
        wrong = await client.get(f"/t/{tid}-wrong?utm_source=x", follow_redirects=False)
        resp = await client.get(path)
        api = (await client.get(f"/api/public/trainers/{tid}")).json()

    assert short.status_code == 301 and short.headers["location"] == path
    assert wrong.status_code == 301 and wrong.headers["location"] == path + "?utm_source=x"
    assert resp.status_code == 200
    html = resp.text
    assert api["can_book"] is True
    assert f"<h1 class=\"tp-name\">{name}</h1>" in html
    assert 'content="index, follow"' in html
    assert f'rel="canonical" href="https://glide.example{path}"' in html
    assert '"@type": "Person"' in html
    # Главная кнопка — запись в Mini App на карточку этого тренера, через учётный прокси.
    assert "Записаться в Telegram" in html
    assert f"startapp=trainer_{tid}&amp;surface=trainer_page" in html
    assert "Свободные окна" in html
    # Каток — ссылкой на страницу катка сайта, не в Telegram.
    assert f'href="https://glide.example{place["path"]}"' in html
    assert "55 BYN" in html


@pytest.mark.asyncio
async def test_without_online_booking_page_offers_write_not_book(app_use_test_db, db_session) -> None:
    """Карточка без подписки — бесплатна: «Написать в Telegram», окон и «Записаться» нет (PDEC-025)."""
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_CRM)
        await _slot(db_session, tid, days=2, hour=12, arena_id=place["arena_id"])
        await db_session.commit()
        html = (await client.get(trainer_path(tid, name))).text
        api = (await client.get(f"/api/public/trainers/{tid}")).json()
    assert api["can_book"] is False
    assert "Записаться" not in html
    assert "Свободные окна" not in html
    assert f'href="/r/tg/{tid}"' in html and "Написать в Telegram" in html


@pytest.mark.asyncio
async def test_hidden_trainer_page_opens_by_link_but_is_noindex_and_off_sitemap(app_use_test_db, db_session) -> None:
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        await db_session.execute(
            text("UPDATE trainers SET catalog_state = 'hidden', is_catalog_visible = false WHERE id = :t"), {"t": tid}
        )
        await db_session.commit()
        path = trainer_path(tid, name)
        resp = await client.get(path)
        sitemap = (await client.get("/sitemap.xml")).text
        api = await client.get(f"/api/public/trainers/{tid}")
        place_html = (await client.get(place["path"])).text
    assert api.status_code == 404
    assert resp.status_code == 200
    assert 'content="noindex, follow"' in resp.text
    assert '"@type": "Person"' not in resp.text
    # Не в каталоге — постоянная ссылка тренера: бот привяжет человека к нему.
    assert f"https://t.me/glide_test_bot?start=welcome_ref_{tid}" in resp.text
    assert path not in sitemap
    assert path not in place_html


@pytest.mark.asyncio
async def test_listed_trainer_in_sitemap_and_deactivated_is_404(app_use_test_db, db_session) -> None:
    async with _client() as client:
        _place_row, tid, name = await _listed(db_session, client, tier=None)
        path = trainer_path(tid, name)
        sitemap = (await client.get("/sitemap.xml")).text
        assert f"<loc>https://glide.example{path}</loc>" in sitemap
        await db_session.execute(text("UPDATE trainers SET status = 'deactivated' WHERE id = :t"), {"t": tid})
        await db_session.commit()
        gone = await client.get(path)
        missing = await client.get("/t/999999999-nobody")
    assert gone.status_code == 404
    assert missing.status_code == 404
    assert re.search(r'name="robots" content="noindex"', gone.text)


@pytest.mark.asyncio
async def test_trainer_shared_link_is_site_page_and_keeps_welcome_ref_binding(app_use_test_db, db_session) -> None:
    """Ссылка из кабинета — ``/t/…?via=link``; кнопка на ней — ``welcome_ref``, бот привяжет ученика."""
    from tests.api.test_webapp_trainer_catalog import HEADERS
    from tests.api.test_webapp_trainer_miniapp_profile_integration import (
        _fresh_trainer_telegram_id,
        patch_trainer_init_auth,
    )

    async with _client() as client:
        _place_row, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(text("UPDATE trainers SET telegram_id = :tg WHERE id = :t"), {"tg": tg, "t": tid})
    await db_session.commit()
    with patch_trainer_init_auth(tg):
        async with _client() as client:
            body = (await client.get("/api/webapp/trainer/hub/universal-invite-link", headers=HEADERS)).json()
    link = body["link"]
    assert link == f"https://glide.example{trainer_path(tid, name)}?via=link"
    assert link in body["share_text"]
    async with _client() as client:
        shared = (await client.get(link.replace("https://glide.example", ""))).text
        plain = (await client.get(link.replace("https://glide.example", "").split("?")[0])).text
    assert f"https://t.me/glide_test_bot?start=welcome_ref_{tid}" in shared
    # Тот же адрес без метки — витрина: карточка в Mini App через учётный прокси.
    assert f"startapp=trainer_{tid}&amp;surface=trainer_page" in plain
    # Канонический адрес один — метка ссылки на него не влияет.
    assert f'rel="canonical" href="https://glide.example{link.replace("https://glide.example", "").split("?")[0]}"' in shared


@pytest.mark.asyncio
async def test_page_from_client_recommendation_keeps_share_ref(app_use_test_db, db_session) -> None:
    """«Поделиться тренером» → ``/t/…?via=share``; кнопка — ``share_ref``, как прежняя рекомендация."""
    async with _client() as client:
        _place_row, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        html = (await client.get(f"{trainer_path(tid, name)}?via=share")).text
    assert f"https://t.me/glide_test_bot?start=share_ref_{tid}" in html
