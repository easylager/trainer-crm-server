"""TASK-146: подборка /c/{город} — то, чем делятся из каталога (город + тип + окно)."""

from __future__ import annotations

import io
import re
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import city_slug
from tests.api.test_catalog_shops import _admin_create_shop
from tests.api.test_ice_windows_and_nearest import _session
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_city
from tests.api.test_schedule_staleness_surfaces import _job

_PHONE_GUARD_UNKNOWN = "unknown (только email/соцсети)"
_PHONE_GUARD_SHORT = "123-456"
_PHONE_GUARD_VALID = "+375 29 123-45-67"


def _selection_pick_block(html: str, arena_name: str) -> str:
    for block in re.findall(r'<section class="sec pick">.*?</section>', html, re.DOTALL):
        if arena_name in block:
            return block
    raise AssertionError(f"pick block for {arena_name!r} missing")


def _assert_invalid_phone_ssr(fragment: str, raw_phone: str) -> None:
    assert "tel:" not in fragment
    assert raw_phone not in fragment
    assert "уточните по телефону" not in fragment.lower()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_selection_page_shows_places_sessions_and_keeps_filters(app_use_test_db, db_session) -> None:
    name = f"Подборинск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    rink = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    await _session(db_session, rink, day=date.today() + timedelta(days=2), hhmm="18:45")
    await db_session.commit()
    slug = city_slug(name)
    async with _client() as client:
        page = await client.get(f"/c/{slug}")
        by_id = await client.get(f"/c/{city_id}")
        img = await client.get(f"/c/{slug}/og.png")
        missing = await client.get("/c/nowhere-at-all")
    assert page.status_code == 200
    assert "18:45" in page.text and "все места" in page.text.lower()
    assert f'href="/p/{slug}/' in page.text, "место в подборке ведёт на свою страницу"
    assert by_id.status_code == 301 and by_id.headers["location"] == f"/c/{slug}"
    assert Image.open(io.BytesIO(img.content)).size == (1200, 630)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_unfiltered_selection_matches_feed_without_shops(app_use_test_db, db_session) -> None:
    """TASK-217: «все места» — как лента. Магазин только по чипу, смесь не называется катками."""
    name = f"Лентаград {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name="Ледовый")
    gym_id = await _insert_arena(db_session, city_id, name="Зал Силы")
    await db_session.execute(
        text("UPDATE arenas SET venue_type = 'gym' WHERE id = :id"),
        {"id": gym_id},
    )
    await db_session.commit()
    shop = f"CCMshop {uuid.uuid4().hex[:4]}"
    await _admin_create_shop(city_id, shop)
    slug = city_slug(name)
    async with _client() as client:
        page = await client.get(f"/c/{slug}")
        share = await client.get(
            "/api/public/ice/selection/share",
            params={"city_id": city_id, "record": "false"},
        )
        shops = await client.get(f"/c/{slug}", params={"t": "shop"})
    assert page.status_code == 200
    assert "Ледовый" in page.text and "Зал Силы" in page.text
    assert shop not in page.text
    body = share.json()["share_body"]
    assert "Ледовый" in body and "Зал Силы" in body
    assert shop not in body
    assert "2 места" in body
    assert "каток" not in body.lower()
    assert shop in shops.text


@pytest.mark.asyncio
async def test_shop_selection_and_share_api(app_use_test_db, db_session) -> None:
    name = f"Магазинск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await db_session.commit()
    await _admin_create_shop(city_id, f"Лезвие {uuid.uuid4().hex[:4]}")
    async with _client() as client:
        page = await client.get(f"/c/{city_slug(name)}", params={"t": "shop"})
        share = await client.get(
            "/api/public/ice/selection/share",
            params={"city_id": city_id, "venue_type": "shop", "channel": "copy"},
        )
        preview = await client.get(
            "/api/public/ice/selection/share", params={"city_id": city_id, "when": "auto", "record": "false"}
        )
    assert "магазины и заточка" in page.text
    body = share.json()
    assert body["share_url"].endswith(f"/c/{city_slug(name)}?t=shop")
    assert body["share_body"].startswith(f"{name} · магазины и заточка")
    assert body["og_image_url"].split("?")[0].endswith("/og.png")
    assert body["story_image_url"].split("?")[0].endswith("/story.png")
    # TASK-222: ?v= — хэш данных превью, иначе Telegram держит старую картинку по URL.
    assert "?t=shop" in body["og_image_url"] and "v=" in body["og_image_url"]
    assert "?t=shop" in body["story_image_url"] and "v=" in body["story_image_url"]
    assert preview.json()["when"] in ("today_evening", "tomorrow", "weekend")
    assert "/story.png" in preview.json()["story_image_url"]
    rows = (
        (
            await db_session.execute(
                text("SELECT payload FROM client_share_events WHERE kind = 'selection' AND city_id = :c"),
                {"c": city_id},
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0]["channel"] == "copy" and rows[0]["venue_type"] == "shop"


def _og(html: str, prop: str) -> str:
    import re

    match = re.search(rf'<meta property="{prop}" content="([^"]*)"', html)
    assert match, prop
    return match.group(1)


@pytest.mark.asyncio
async def test_selection_preview_and_telegram_keep_the_window(
    app_use_test_db, db_session, monkeypatch
) -> None:
    """Превью не говорит «сегодня», а «Открыть в Telegram» открывает то же окно."""
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_bot")
    monkeypatch.setenv("CLIENT_MINI_APP_SHORT_NAME", "")
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "true")
    name = f"Окноград {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await db_session.commit()
    slug = city_slug(name)
    async with _client() as client:
        page = await client.get(f"/c/{slug}", params={"w": "weekend"})
        share = await client.get(
            "/api/public/ice/selection/share",
            params={"city_id": city_id, "when": "weekend", "record": "false"},
        )
    assert page.status_code == 200
    og_title = _og(page.text, "og:title").lower()
    for stale in ("сегодня", "завтра", "выходн"):
        assert stale not in og_title
        assert stale not in share.json()["share_body"].lower()
    assert _og(page.text, "og:image").startswith("http")
    assert f"startapp=catalog_{city_id}_skate_weekend" in page.text
    assert "/api/public/catalog/open-telegram" in page.text
    assert "В выходные" in page.text, "живая страница говорит ту же подпись, что и меню Mini App"


@pytest.mark.asyncio
async def test_selection_page_ssr_phone_guard(app_use_test_db, db_session) -> None:
    """TASK-207: невалидные телефоны не попадают в SSR подборки (/c/)."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stale_at = now - timedelta(hours=80)
    city_label = f"Телподбор{uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=city_label)
    cases = (
        ("Каток без связи", _PHONE_GUARD_UNKNOWN),
        ("Каток короткий", _PHONE_GUARD_SHORT),
        ("Каток валидный", _PHONE_GUARD_VALID),
    )
    for arena_name, phone in cases:
        arena_id = await _insert_arena(db_session, city_id, name=arena_name, phone=phone)
        await _add_future_session(db_session, arena_id, days_ahead=2, observed_at=stale_at)
        await _job(db_session, arena_id, last_ok_at=stale_at)
    await db_session.commit()

    async with _client() as client:
        page = await client.get(f"/c/{city_slug(city_label)}")
    assert page.status_code == 200, page.text
    html = page.text
    _assert_invalid_phone_ssr(_selection_pick_block(html, "Каток без связи"), _PHONE_GUARD_UNKNOWN)
    _assert_invalid_phone_ssr(_selection_pick_block(html, "Каток короткий"), _PHONE_GUARD_SHORT)
    valid_block = _selection_pick_block(html, "Каток валидный")
    assert 'href="tel:+375291234567"' in valid_block
    assert "уточните по телефону" in valid_block.lower()


@pytest.mark.asyncio
async def test_selection_preview_counts_the_whole_selection_and_bumps_image_version(
    app_use_test_db, db_session, monkeypatch
) -> None:
    """TASK-222: «15 катков · 10 сеансов» — на странице, на og.png, story.png и в строках шера."""
    import src.application.selection_page as selection_page
    from src.application import png_render_cache as pc

    name = f"Счётск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    total, with_sessions = 15, 10
    for n in range(total):
        arena_id = await _insert_arena(db_session, city_id, name=f"Каток {n:02d} {uuid.uuid4().hex[:4]}")
        if n < with_sessions:
            await _add_future_session(db_session, arena_id, days_ahead=1 + (n % 3), starts_at_local="13:00")
    await db_session.commit()
    slug = city_slug(name)

    drawn: list[str] = []
    original = selection_page.selection_share_description

    def spy(view):
        value = original(view)
        drawn.append(value)
        return value

    monkeypatch.setattr(selection_page, "selection_share_description", spy)

    async with _client() as client:
        page = await client.get(f"/c/{slug}")
        share = await client.get(
            "/api/public/ice/selection/share", params={"city_id": city_id, "record": "false"}
        )

    assert page.status_code == 200 and share.status_code == 200
    description = "15 катков · 10 сеансов"
    # Страница показывает 12 карточек, но обещает всю подборку — и в HTML-превью, и в строках шера.
    assert _og(page.text, "og:description") == description, _og(page.text, "og:description")
    body = share.json()
    assert description in body["share_body"]
    assert description in body["share_text"]

    # og.png и story.png рисуются из той же подписи: одна правда, а не два счёта.
    pc.reset_png_cache_for_tests()
    drawn.clear()
    async with _client() as client:
        og = await client.get(f"/c/{slug}/og.png")
        story = await client.get(f"/c/{slug}/story.png")
    assert og.status_code == 200 and story.status_code == 200
    assert drawn == [description, description], drawn

    # Лишние query-параметры внутренний кэш PNG не видит: ?v= — для Telegram, не для рендера.
    async with _client() as client:
        plain = await client.get(f"/c/{slug}/og.png")
        with_param = await client.get(f"/c/{slug}/og.png", params={"v": "manual"})
    assert plain.content == with_param.content
    stats = pc.png_cache_stats()
    assert stats["renders"] == 2, stats
    assert stats["hits"] >= 2, stats

    # Данные изменились — ?v= в og:image тоже: иначе Telegram оставит старую картинку.
    image_url = _og(page.text, "og:image")
    assert "v=" in image_url, image_url
    first_version = image_url.split("v=")[1]
    extra_id = await _insert_arena(db_session, city_id, name=f"Каток новый {uuid.uuid4().hex[:4]}")
    await _add_future_session(db_session, extra_id, days_ahead=2, starts_at_local="09:00")
    await db_session.commit()
    async with _client() as client:
        again = await client.get(f"/c/{slug}")
    assert again.status_code == 200
    assert _og(again.text, "og:image").split("v=")[1] != first_version
