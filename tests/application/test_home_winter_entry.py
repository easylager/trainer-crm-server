"""TASK-436 AC-1: на главной вход «Зимой» в город — тот же предикат, что у строки на хабе."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.application import city_hub_page, winter_public
from src.application.catalog_home_page import _b_home_city_card

CITY = {"slug": "minsk", "name": "Минск", "href": "/c/minsk", "session_count": 3}
NOW = datetime(2026, 12, 5, 12, tzinfo=timezone.utc)


def test_card_shows_winter_entry_when_city_has_points() -> None:
    html = _b_home_city_card({**CITY, "winter": {"total": 3, "flooded": 0}})
    assert 'href="/c/minsk/zimoy"' in html
    assert "Уличные катки и коробки" in html
    assert "3\u00a0места · ждём заливку" in html


def test_card_counts_flooded_points() -> None:
    html = _b_home_city_card({**CITY, "winter": {"total": 5, "flooded": 2}})
    assert "залиты 2" in html


def test_card_without_winter_has_no_entry() -> None:
    assert "zimoy" not in _b_home_city_card({**CITY, "winter": None})
    assert "zimoy" not in _b_home_city_card(CITY)


def _summary(monkeypatch, *, enabled: bool, total: int):
    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "true" if enabled else "false")

    async def fake_city_summary(session, city_id, *, now, include_catalog_schedule=False):
        return {"total": total, "flooded": 0}

    monkeypatch.setattr(winter_public, "city_summary", fake_city_summary)
    return asyncio.run(city_hub_page._winter_summary(None, 1, now=NOW))


def test_flag_off_means_no_entry(monkeypatch) -> None:
    assert _summary(monkeypatch, enabled=False, total=4) is None


def test_flag_on_without_points_means_no_entry(monkeypatch) -> None:
    assert _summary(monkeypatch, enabled=True, total=0) is None


def test_flag_on_with_points_gives_entry(monkeypatch) -> None:
    assert _summary(monkeypatch, enabled=True, total=4) == {"total": 4, "flooded": 0}


async def _home_html(db_session, monkeypatch, *, enabled: bool) -> tuple[str, str]:
    import uuid

    from httpx import ASGITransport, AsyncClient

    from src.api.app import app
    from src.application.ice_city_day import city_slug, invalidate_public_city_cache
    from tests.api.test_public_arenas import _insert_arena, _insert_city

    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "true" if enabled else "false")

    async def fake_city_summary(session, city_id, *, now, include_catalog_schedule=False):
        return {"total": 2, "flooded": 1}

    monkeypatch.setattr(winter_public, "city_summary", fake_city_summary)
    name = f"Зимний {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name="Каток")
    await _insert_arena(db_session, city_id, name="Второй")
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/", cookies={"glide_city": slug})
    assert resp.status_code == 200
    return resp.text, slug


async def test_home_page_links_winter_when_flag_on(app_use_test_db, db_session, monkeypatch) -> None:
    html, slug = await _home_html(db_session, monkeypatch, enabled=True)
    assert f'href="/c/{slug}/zimoy"' in html
    assert "2\u00a0места · залиты 1" in html


async def test_home_page_has_no_winter_when_flag_off(app_use_test_db, db_session, monkeypatch) -> None:
    html, slug = await _home_html(db_session, monkeypatch, enabled=False)
    assert "/zimoy" not in html
