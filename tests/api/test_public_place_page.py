"""TASK-146: публичная страница места — главный вирусный артефакт каталога."""

from __future__ import annotations

import io
import json
import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import city_slug
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _place(db_session, *, name: str | None = None, venue_type: str = "ice", **profile):
    city_name = f"Плейсск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=city_name)
    arena_name = name or f"Ледовая арена {uuid.uuid4().hex[:6]}"
    arena_id = await _insert_arena(
        db_session, city_id, name=arena_name, phone="+375 29 111-22-33", district="Фрунзенский"
    )
    await db_session.execute(
        text("UPDATE arenas SET venue_type = :vt WHERE id = :id"), {"vt": venue_type, "id": arena_id}
    )
    if profile:
        sets = ", ".join(
            f"{k} = CAST(:{k} AS jsonb)" if k in ("amenities", "opening_hours") else f"{k} = :{k}" for k in profile
        )
        params = {k: (json.dumps(v) if k in ("amenities", "opening_hours") else v) for k, v in profile.items()}
        params["id"] = arena_id
        await db_session.execute(text(f"UPDATE arena_profiles SET {sets} WHERE arena_id = :id"), params)
    slug = (
        await db_session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id = :id"), {"id": arena_id})
    ).scalar_one()
    await db_session.commit()
    return {
        "city_id": city_id,
        "city_name": city_name,
        "arena_id": arena_id,
        "name": arena_name,
        "path": f"/p/{city_slug(city_name)}/{slug}",
    }


def _meta(html: str, prop: str) -> str:
    m = re.search(rf'<meta (?:property|name)="{re.escape(prop)}" content="([^"]*)"', html)
    assert m, f"no meta {prop}"
    return m.group(1)


def _json_ld(html: str) -> dict:
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert m
    return json.loads(m.group(1))


@pytest.mark.asyncio
async def test_place_page_opens_without_auth_and_is_a_complete_answer(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    await _add_future_session(db_session, place["arena_id"], days_ahead=1, starts_at_local="19:30")
    await db_session.commit()

    async with _client() as client:
        resp = await client.get(place["path"])
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "public, max-age=300"
    html = resp.text
    assert place["name"] in _meta(html, "og:title")
    assert "расписание массового катания" in _meta(html, "og:title")
    assert _meta(html, "og:image").endswith(place["path"] + "/og.png")
    assert _meta(html, "robots") == "index, follow"
    assert "19:30" in html and "8.50 BYN" in html
    # Шеринг дальше — во все мессенджеры, без Telegram у получателя.
    assert "https://t.me/share/url?url=" in html
    assert "https://wa.me/?text=" in html
    assert "viber://forward?text=" in html
    ld = _json_ld(html)
    assert ld["@type"] == "IceRink"
    assert ld["telephone"] == "+375 29 111-22-33"
    assert ld["event"][0]["offers"]["price"] == "8.50"


@pytest.mark.asyncio
async def test_slot_link_puts_that_session_first_and_out_of_index(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    sid = await _add_future_session(db_session, place["arena_id"], days_ahead=2, starts_at_local="20:30")
    await db_session.commit()

    async with _client() as client:
        resp = await client.get(place["path"], params={"s": sid})
        invite = await client.get(place["path"], params={"s": sid, "i": "1"})
    html = resp.text
    assert 'id="plan"' in html and "Выбранный сеанс" in html
    assert _meta(html, "og:title").endswith("20:30 · " + place["name"])
    assert _meta(html, "robots") == "noindex, follow"
    assert f"og.png?s={sid}" in _meta(html, "og:image")
    assert f"?s={sid}" in _meta(html, "og:url")
    # Канонический адрес — без параметров: в поиске одна страница на место.
    assert re.search(rf'<link rel="canonical" href="[^"]*{re.escape(place["path"])}"', html)

    ihtml = invite.text
    assert _meta(ihtml, "og:title").startswith("Погнали кататься?")
    assert "Тебя зовут кататься" in ihtml
    assert "i=1" in _meta(ihtml, "og:image")


@pytest.mark.asyncio
async def test_link_to_a_past_session_says_so_and_shows_whats_next(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    await _add_future_session(db_session, place["arena_id"], days_ahead=1, starts_at_local="18:00")
    await db_session.commit()
    async with _client() as client:
        resp = await client.get(place["path"], params={"s": "999999999"})
    assert resp.status_code == 200
    assert "Этот сеанс уже прошёл" in resp.text
    # «Сегодня/Завтра» считается по Минску, а фикстура — по дате контейнера; проверяем суть.
    assert re.search(r"Ближайший — [^<]*, 18:00", resp.text)


@pytest.mark.asyncio
async def test_id_link_and_wrong_city_redirect_to_canonical(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    async with _client() as client:
        by_id = await client.get(f"/p/{place['arena_id']}?s=5")
        by_city_id = await client.get(place["path"].replace(city_slug(place["city_name"]), str(place["city_id"])))
    assert by_id.status_code == 301
    assert by_id.headers["location"] == place["path"] + "?s=5"
    assert by_city_id.status_code == 301
    assert by_city_id.headers["location"] == place["path"]


@pytest.mark.asyncio
async def test_unknown_place_is_a_friendly_404(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    async with _client() as client:
        resp = await client.get(place["path"] + "-nope")
        img = await client.get(place["path"] + "-nope/og.png")
        archived_slug = place["path"]
        await db_session.execute(
            text("UPDATE arena_profiles SET status = 'archived' WHERE arena_id = :id"), {"id": place["arena_id"]}
        )
        await db_session.commit()
        archived = await client.get(archived_slug)
    assert resp.status_code == 404
    assert "Этого места больше нет в каталоге" in resp.text
    assert img.status_code == 404
    assert archived.status_code == 404


@pytest.mark.asyncio
async def test_og_and_story_images_are_real_pngs(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    sid = await _add_future_session(db_session, place["arena_id"], days_ahead=1)
    await db_session.commit()
    async with _client() as client:
        og = await client.get(place["path"] + "/og.png", params={"s": sid})
        story = await client.get(place["path"] + "/story.png", params={"i": "1"})
    assert og.status_code == 200 and og.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(og.content)).size == (1200, 630)
    assert Image.open(io.BytesIO(story.content)).size == (1080, 1920)


@pytest.mark.asyncio
async def test_shop_page_shows_services_not_a_schedule(app_use_test_db, db_session) -> None:
    place = await _place(
        db_session,
        name=f"Коньки и Точка {uuid.uuid4().hex[:4]}",
        venue_type="shop",
        amenities={"retail": True, "skate_sharpening": True, "repair": False},
        opening_hours={"daily": {"open": "10:00", "close": "20:00"}},
    )
    async with _client() as client:
        resp = await client.get(place["path"])
    html = resp.text
    assert resp.status_code == 200
    assert "Что здесь можно сделать" in html
    assert "Розница" in html and "Заточка" in html
    assert "Ремонт" not in html, "repair=false — известно, что нет; плитку не рисуем"
    assert "Массовое катание" not in html
    assert "розница, заточка" in _meta(html, "og:title")
    assert "10:00–20:00" in html
    assert _json_ld(html)["@type"] == "SportingGoodsStore"
    assert _json_ld(html)["openingHours"] == "Mo-Su 10:00-20:00"


@pytest.mark.asyncio
async def test_out_of_season_rink_says_when_it_opens(app_use_test_db, db_session) -> None:
    from datetime import date

    month = date.today().month
    start = (month % 12) + 1  # следующий месяц
    end = start  # сезон — один месяц, и это не текущий
    place = await _place(db_session, season_start_month=start, season_end_month=end)
    async with _client() as client:
        resp = await client.get(place["path"])
    assert "Сезон закрыт · откроется в" in resp.text
    assert "Массовое катание</h2>" not in resp.text


@pytest.mark.asyncio
async def test_hostile_name_is_escaped_everywhere(app_use_test_db, db_session) -> None:
    place = await _place(db_session, name='Каток </script><script>alert(1)</script> "x"')
    async with _client() as client:
        resp = await client.get(place["path"])
    assert resp.status_code == 200
    assert "<script>alert(1)</script>" not in resp.text
    _json_ld(resp.text)  # JSON-LD остаётся валидным JSON


@pytest.mark.asyncio
async def test_share_api_points_at_the_page_and_counts_the_click(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    sid = await _add_future_session(db_session, place["arena_id"], days_ahead=1, starts_at_local="20:30")
    await db_session.commit()
    async with _client() as client:
        resp = await client.get(
            f"/api/public/arenas/{place['arena_id']}/share",
            params={"session_id": sid, "invite": "true", "share_context": "arena_card"},
        )
        missing = await client.get("/api/public/arenas/999999999/share")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["share_url"].endswith(f"{place['path']}?s={sid}&i=1")
    assert body["place_share_url"].endswith(f"{place['path']}?s={sid}")
    assert body["share_text"].startswith(body["share_url"])
    assert body["share_body"].startswith("Погнали кататься?")
    assert re.search(r", 20:30 — " + re.escape(place["name"]) + r", 8\.50 BYN", body["share_body"])
    assert body["place_share_body"].startswith(place["name"] + " — массовое катание")
    assert body["story_image_url"].endswith(f"/story.png?s={sid}&i=1")
    assert missing.status_code == 404

    row = (
        await db_session.execute(
            text(
                "SELECT kind, share_context, arena_id, city_id, payload FROM client_share_events "
                "WHERE arena_id = :aid ORDER BY id DESC LIMIT 1"
            ),
            {"aid": place["arena_id"]},
        )
    ).one()
    assert row[0] == "place" and row[1] == "arena_card"
    assert row[3] == place["city_id"]
    assert row[4]["session_id"] == sid and row[4]["invite"] is True


@pytest.mark.asyncio
async def test_sitemap_lists_places_and_city_days_for_search(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    hidden = await _place(db_session)
    await db_session.execute(
        text("UPDATE arena_profiles SET status = 'draft' WHERE arena_id = :id"), {"id": hidden["arena_id"]}
    )
    await db_session.commit()
    async with _client() as client:
        sm = await client.get("/sitemap.xml")
        robots = await client.get("/robots.txt")
    assert sm.status_code == 200 and sm.headers["content-type"].startswith("application/xml")
    assert place["path"] + "</loc>" in sm.text
    assert f"/ice/{city_slug(place['city_name'])}/today</loc>" in sm.text
    assert hidden["path"] + "</loc>" not in sm.text
    assert "Sitemap: " in robots.text and "/sitemap.xml" in robots.text
    assert "Disallow: /api/" in robots.text


def test_city_day_page_links_every_rink_to_its_place_page() -> None:
    from src.application.ice_city_day_page import _arena_html

    html = _arena_html({"name": "Минск-Арена", "slug": "minsk-arena", "sessions": []}, city_name="Минск")
    assert '<a href="/p/minsk/minsk-arena">Минск-Арена</a>' in html
    # Без slug ссылки нет — мёртвой ссылки лучше не рисовать.
    assert "<a " not in _arena_html({"name": "Каток", "slug": None, "sessions": []}, city_name="Минск")
