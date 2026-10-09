"""TASK-192: sitemap, HTML-404, canonical /c/, JSON-LD «лёд сегодня», язык, slug+город."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.routes.public_place_page import _sitemap_lastmod
from src.application.ice_city_day import city_slug
from src.shared.config import Settings
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_bare_trainer, _insert_city
from tests.api.test_public_ice_city_day import _add_today_session
from tests.api.test_public_place_page import _json_ld, _meta, _place


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _canonical(html: str) -> str:
    match = re.search(r'<link rel="canonical" href="([^"]*)"', html)
    assert match, "canonical"
    return match.group(1)


def _url_block(xml: str, path: str) -> str:
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        if f"{path}</loc>" in block:
            return block
    raise AssertionError(path)


def _events(ld: dict) -> list[dict]:
    events = []
    for element in ld.get("itemListElement") or []:
        item = element.get("item") if isinstance(element, dict) else None
        if isinstance(item, dict) and item.get("@type") == "Event":
            events.append(item)
        elif isinstance(element, dict) and element.get("@type") == "Event":
            events.append(element)
    return events


@pytest.mark.asyncio
async def test_sitemap_lists_catalog_home_and_trainers_landing_with_lastmod(app_use_test_db, db_session) -> None:
    """«/» — каталог, «/trainers» — лендинг. lastmod места — более поздний из профиля и сеанса."""
    older = await _place(db_session, name=f"Старее {uuid.uuid4().hex[:4]}")
    newer = await _place(db_session, name=f"Новее {uuid.uuid4().hex[:4]}")
    await _add_future_session(db_session, older["arena_id"], days_ahead=3, starts_at_local="11:00")
    await _add_future_session(db_session, newer["arena_id"], days_ahead=3, starts_at_local="12:00")
    await db_session.execute(
        text("UPDATE arena_profiles SET updated_at = :ts WHERE arena_id = :id"),
        {"ts": datetime(2020, 1, 1, tzinfo=timezone.utc), "id": older["arena_id"]},
    )
    profile_stamp = datetime(2099, 6, 1, 12, 0, tzinfo=timezone.utc)
    await db_session.execute(
        text("UPDATE arena_profiles SET updated_at = :ts WHERE arena_id = :id"),
        {"ts": profile_stamp, "id": newer["arena_id"]},
    )
    session_stamp = (
        await db_session.execute(
            text("SELECT MAX(starts_at_utc) FROM ice_sessions WHERE arena_id = :id"),
            {"id": older["arena_id"]},
        )
    ).scalar_one()
    trainer_id = await _insert_bare_trainer(db_session)
    hidden_name = f"Скрытск {uuid.uuid4().hex[:4]}"
    hidden_city = await _insert_city(db_session, name=hidden_name)
    hidden_id = await _insert_arena(
        db_session,
        hidden_city,
        name=f"Каток без фото {uuid.uuid4().hex[:4]}",
        has_photo=False,
        created_by_trainer_id=trainer_id,
    )
    hidden_slug = (
        await db_session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id = :id"), {"id": hidden_id})
    ).scalar_one()
    hidden_path = f"/p/{city_slug(hidden_name)}/{hidden_slug}"
    await db_session.commit()

    async with _client() as client:
        sm = await client.get("/sitemap.xml")
    assert sm.status_code == 200
    xml = sm.text
    base = Settings().webapp_base_url.rstrip("/")
    assert f"<loc>{base}/</loc>" in xml
    assert f"<loc>{base}/trainers</loc>" in xml
    home_block = _url_block(xml, f"{base}/")
    trainers_block = _url_block(xml, f"{base}/trainers")
    assert "<lastmod>" in home_block
    assert "<lastmod>" in trainers_block
    assert "?t=" not in xml and "?w=" not in xml
    assert hidden_path not in xml

    older_block = _url_block(xml, older["path"])
    newer_block = _url_block(xml, newer["path"])
    assert f"<lastmod>{_sitemap_lastmod(session_stamp)}</lastmod>" in older_block
    assert f"<lastmod>{_sitemap_lastmod(profile_stamp)}</lastmod>" in newer_block
    city_block = _url_block(xml, f"/c/{city_slug(older['city_name'])}")
    assert "<lastmod>" in city_block
    ice_block = _url_block(xml, f"/ice/{city_slug(older['city_name'])}/today")
    assert "<lastmod>" in ice_block


@pytest.mark.asyncio
async def test_unknown_ice_city_is_html_404_and_empty_day_is_noindex(app_use_test_db, db_session) -> None:
    empty_name = f"Пустоград {uuid.uuid4().hex[:6]}"
    await _insert_city(db_session, name=empty_name)
    quiet_name = f"Тихий {uuid.uuid4().hex[:6]}"
    quiet_id = await _insert_city(db_session, name=quiet_name)
    await _insert_arena(db_session, quiet_id, name="Каток без сеансов")
    await db_session.commit()

    async with _client() as client:
        missing = await client.get("/ice/nowhere/today")
        empty = await client.get(f"/ice/{city_slug(empty_name)}/today")
        quiet = await client.get(f"/ice/{city_slug(quiet_name)}/today")

    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("text/html")
    assert "City not found" not in missing.text
    assert "Glide" in missing.text
    assert _meta(missing.text, "robots") == "noindex"
    assert "Открыть каталог Glide" in missing.text

    assert empty.status_code == 200
    assert _meta(empty.text, "robots") == "noindex"
    assert quiet.status_code == 200
    assert _meta(quiet.text, "robots") == "noindex"


@pytest.mark.asyncio
async def test_selection_variants_canonicalize_to_the_city_and_drop_out_of_index(
    app_use_test_db, db_session
) -> None:
    name = f"Канонск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    await db_session.commit()
    slug = city_slug(name)
    async with _client() as client:
        base = await client.get(f"/c/{slug}")
        filtered = await client.get(f"/c/{slug}", params={"t": "shop", "w": "today"})
        weekend = await client.get(f"/c/{slug}", params={"w": "weekend"})
    assert base.status_code == 200 and filtered.status_code == 200
    assert _meta(base.text, "robots") == "index, follow"
    assert _meta(filtered.text, "robots") == "noindex, follow"
    assert _meta(weekend.text, "robots") == "noindex, follow"
    assert _canonical(filtered.text) == _canonical(base.text) == _canonical(weekend.text)
    assert _canonical(base.text).endswith(f"/c/{slug}")
    assert "?" not in _canonical(filtered.text)
    listed = _json_ld(base.text)["itemListElement"]
    assert listed
    assert f"/p/{slug}/" in listed[0]["url"]


@pytest.mark.asyncio
async def test_ice_today_jsonld_is_an_item_list_of_events_and_survives_markup(
    app_use_test_db, db_session
) -> None:
    evil = '</script><img src=x onerror=alert(1)>'
    name = f"Разметск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name=evil)
    sid, _starts = await _add_today_session(db_session, arena_id, price_adult_minor=50000)
    await db_session.execute(
        text("UPDATE ice_sessions SET currency_code = 'RUB' WHERE id = :id"),
        {"id": sid},
    )
    await db_session.commit()
    slug = city_slug(name)
    async with _client() as client:
        page = await client.get(f"/ice/{slug}/today")
    assert page.status_code == 200, page.text
    assert _meta(page.text, "robots") == "index, follow"
    # JSON-LD must be a single block; page may also load list-scroll / other scripts.
    assert page.text.count('<script type="application/ld+json">') == 1
    assert "<img" not in page.text
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', page.text, re.S)
    assert raw
    assert "<" not in raw.group(1) and ">" not in raw.group(1)
    ld = json.loads(raw.group(1))
    assert ld["@type"] == "ItemList"
    events = _events(ld)
    assert len(events) == 1
    event = events[0]
    assert event["@type"] == "Event"
    assert event["location"]["@type"] == "Place"
    assert event["location"]["name"] == evil
    assert event["startDate"] and event["endDate"]
    assert datetime.fromisoformat(event["endDate"]) > datetime.fromisoformat(event["startDate"])
    assert event["offers"]["@type"] == "Offer"
    assert event["offers"]["price"] == "500.00"
    assert event["offers"]["priceCurrency"] == "RUB"
    assert f"/p/{slug}/" in event["url"]


@pytest.mark.asyncio
async def test_catalog_pages_use_country_locale(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ICE_DISCOVERY_COUNTRIES", "BY,RU")
    minsk_name = f"Минск {uuid.uuid4().hex[:6]}"
    spb_name = f"Санкт-Петербург {uuid.uuid4().hex[:6]}"
    minsk_id = await _insert_city(db_session, name=minsk_name, country="BY")
    spb_id = await _insert_city(db_session, name=spb_name, country="RU")
    await _insert_arena(db_session, minsk_id, name="Минск-Арена")
    await _insert_arena(db_session, spb_id, name="СКА Арена")
    await db_session.commit()

    async def _page_langs(city_name: str, city_id: int) -> list[tuple[str, str]]:
        slug = city_slug(city_name)
        arena_slug = (
            await db_session.execute(
                text("SELECT slug FROM arena_profiles WHERE city_id = :cid"),
                {"cid": city_id},
            )
        ).scalar_one()
        async with _client() as client:
            pages = [
                await client.get(f"/ice/{slug}/today"),
                await client.get(f"/p/{slug}/{arena_slug}"),
                await client.get(f"/c/{slug}"),
            ]
        pairs = []
        for page in pages:
            assert page.status_code == 200, page.text
            lang = re.search(r'<html lang="([^"]+)"', page.text).group(1)
            pairs.append((lang, _meta(page.text, "og:locale")))
        return pairs

    assert set(await _page_langs(minsk_name, minsk_id)) == {("ru-BY", "ru_BY")}
    assert set(await _page_langs(spb_name, spb_id)) == {("ru-RU", "ru_RU")}


@pytest.mark.asyncio
async def test_ambiguous_bare_arena_slug_is_404_until_the_city_is_known(app_use_test_db, db_session) -> None:
    """Один и тот же slug в двух городах — не «меньший id», а 404 без города (старые ссылки: однозначный slug — 200)."""
    first_name = f"Первый {uuid.uuid4().hex[:6]}"
    second_name = f"Второй {uuid.uuid4().hex[:6]}"
    empty_name = f"Третий {uuid.uuid4().hex[:6]}"
    first = await _insert_city(db_session, name=first_name)
    second = await _insert_city(db_session, name=second_name)
    empty = await _insert_city(db_session, name=empty_name)
    arena_name = f"Ледовая арена {uuid.uuid4().hex[:4]}"
    first_id = await _insert_arena(db_session, first, name=arena_name)
    second_id = await _insert_arena(db_session, second, name=arena_name)
    slugs = (
        await db_session.execute(
            text("SELECT arena_id, slug FROM arena_profiles WHERE arena_id IN (:a, :b) ORDER BY arena_id"),
            {"a": first_id, "b": second_id},
        )
    ).all()
    assert slugs[0][1] == slugs[1][1]
    slug = str(slugs[0][1])
    await db_session.commit()

    async with _client() as client:
        bare = await client.get(f"/api/public/arenas/{slug}")
        by_first = await client.get(f"/api/public/arenas/{slug}", params={"city_id": first})
        by_second = await client.get(f"/api/public/arenas/{slug}", params={"city": city_slug(second_name)})
        by_empty = await client.get(f"/api/public/arenas/{slug}", params={"city_id": empty})
        by_id = await client.get(f"/api/public/arenas/{first_id}")
    assert bare.status_code == 404
    assert by_empty.status_code == 404
    assert by_first.status_code == 200 and by_first.json()["id"] == first_id
    assert by_second.status_code == 200 and by_second.json()["id"] == second_id
    assert by_id.status_code == 200 and by_id.json()["id"] == first_id


@pytest.mark.asyncio
async def test_unique_bare_arena_slug_still_resolves_on_every_public_route(app_use_test_db, db_session) -> None:
    """Старые ссылки ``arena_<slug>`` (до TASK-146): slug один на весь каталог → 200 везде."""
    city = await _insert_city(db_session, name=f"Старый {uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, city, name=f"Уникальный каток {uuid.uuid4().hex[:8]}")
    slug = str(
        (
            await db_session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id = :id"), {"id": arena_id})
        ).scalar_one()
    )
    await db_session.commit()

    async with _client() as client:
        card = await client.get(f"/api/public/arenas/{slug}")
        sessions = await client.get(f"/api/public/arenas/{slug}/sessions")
        trainers = await client.get(f"/api/public/arenas/{slug}/trainers")
        share = await client.get(f"/api/public/arenas/{slug}/share", params={"record": "false"})
        by_id = await client.get(f"/api/public/arenas/{arena_id}")
        unknown_city = await client.get(f"/api/public/arenas/{slug}", params={"city": "net-takogo"})
    assert card.status_code == 200 and card.json()["id"] == arena_id
    assert sessions.status_code == 200, sessions.text
    assert trainers.status_code == 200, trainers.text
    assert share.status_code == 200, share.text
    assert by_id.status_code == 200 and by_id.json()["id"] == arena_id
    assert unknown_city.status_code == 404


@pytest.mark.asyncio
async def test_ambiguous_bare_slug_is_404_on_every_public_route(app_use_test_db, db_session) -> None:
    first = await _insert_city(db_session, name=f"Раз {uuid.uuid4().hex[:6]}")
    second = await _insert_city(db_session, name=f"Два {uuid.uuid4().hex[:6]}")
    arena_name = f"Ледовая арена {uuid.uuid4().hex[:6]}"
    first_id = await _insert_arena(db_session, first, name=arena_name)
    await _insert_arena(db_session, second, name=arena_name)
    slug = str(
        (
            await db_session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id = :id"), {"id": first_id})
        ).scalar_one()
    )
    await db_session.commit()

    async with _client() as client:
        for suffix in ("", "/sessions", "/trainers", "/share"):
            resp = await client.get(f"/api/public/arenas/{slug}{suffix}")
            assert resp.status_code == 404, (suffix, resp.status_code)
