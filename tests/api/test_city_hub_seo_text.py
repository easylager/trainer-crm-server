"""TASK-425: хаб /c/minsk — лента «Лёд» по каткам; другие города не меняются."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from src.api.app import app
from src.application.city_hub_seo import SEO_RICH_HUB_CITIES
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_arenas import _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _today() -> date:
    return datetime.now(ZoneInfo("Europe/Minsk")).date()


async def _session(db, arena_id, *, day, hhmm, kind="public_skate", minutes=60, adult=None, child=None, rental=None):
    await create_ice_session(
        db,
        arena_id,
        local_date=day,
        starts_at_local=hhmm,
        duration_minutes=minutes,
        kind=kind,
        price_adult_minor=adult,
        price_child_minor=child,
        price_rental_minor=rental,
    )
    await db.flush()


async def _minsk(db) -> int:
    return await _insert_city(db, name="Минск")


def _tomorrow() -> date:
    return _today() + timedelta(days=1)


async def _get(path: str) -> str:
    invalidate_public_city_cache()
    async with _client() as client:
        return (await client.get(path)).text


def test_only_minsk_is_listed() -> None:
    assert SEO_RICH_HUB_CITIES == {"minsk"}


def _ribbon(html: str) -> str:
    return html.split('<div class="b-scroll">')[1].split("</section>")[0]


@pytest.mark.asyncio
async def test_minsk_ribbon_is_one_tile_per_rink(app_use_test_db, db_session) -> None:
    cid = await _minsk(db_session)
    cheap = await _insert_arena(db_session, cid, name="Дешёвый каток", address="ул. Тестовая, 5")
    dear = await _insert_arena(db_session, cid, name="Дорогой каток")
    solo = await _insert_arena(db_session, cid, name="Одиночный каток")
    quiet = await _insert_arena(db_session, cid, name="Каток без сеансов")
    shop = await _insert_arena(db_session, cid, name="Магазин коньков")
    await db_session.execute(text("UPDATE arenas SET venue_type = 'shop' WHERE id = :id"), {"id": shop})
    await db_session.execute(
        text("""UPDATE arena_profiles SET amenities = '{"skate_rental": true}' WHERE arena_id = :id"""),
        {"id": cheap},
    )
    profiles = await db_session.execute(text("SELECT arena_id, slug FROM arena_profiles WHERE city_id = :id"), {"id": cid})
    slugs = {arena_id: slug for arena_id, slug in profiles}
    day = _tomorrow()
    for hh in ("10:00", "12:00", "08:30"):
        await _session(db_session, cheap, day=day, hhmm=hh, minutes=45, adult=700, child=500, rental=300)
    await _session(db_session, dear, day=day, hhmm="18:00", minutes=90, adult=1500, child=900)
    await _session(db_session, dear, day=day, hhmm="20:00", minutes=90, adult=1500, child=900)
    await _session(db_session, solo, day=day, hhmm="22:00", minutes=45)
    await db_session.commit()

    html = await _get("/c/minsk")
    ribbon = _ribbon(html)
    assert ribbon.count('class="b-tile"') == 3  # три катка, а не восемь сеансов
    assert ribbon.index("Дешёвый каток") < ribbon.index("Дорогой каток") < ribbon.index("Одиночный каток")
    assert "ещё 2 сеанса" in ribbon and "ещё 1 сеанс<" in ribbon
    assert ribbon.count("b-tile__more") == 2  # у одиночного сеанса строки нет
    assert "8:30" in ribbon  # бейдж — ближайший сеанс катка
    assert "Частые вопросы" not in html and "FAQPage" not in html  # карточку вопросов убрали: спроса нет

    assert re.search(r'<link rel="canonical" href="https?://[^/"]+/c/minsk"', html)
    assert '<h1 class="b-hero__title">Катки Минска</h1>' in html
    assert 'href="#rinks">Список катков</a>' in html
    listing = html.split('id="rinks"', 1)[1].split("</section>", 1)[0]
    assert "ул. Тестовая, 5 · Прокат коньков" in listing
    assert "Взрослый билет на ближайший сеанс: 7 BYN</span>" in listing
    assert listing.count("Взрослый билет на ближайший сеанс:") == 2
    for rink in (cheap, dear, solo, quiet):
        assert f'href="/p/minsk/{slugs[rink]}"' in listing
    assert "?s=" not in listing
    assert "Магазин коньков" not in listing

    async with _client() as client:
        home, place = await client.get("/"), await client.get(f"/p/minsk/{slugs[quiet]}")
    assert 'href="/c/minsk">Катки Минска</a>' in home.text
    assert 'href="/c/minsk">Все катки Минска</a>' in place.text


@pytest.mark.asyncio
async def test_other_city_page_is_unchanged(app_use_test_db, db_session) -> None:
    cid = await _insert_city(db_session, name="Молодечно")
    a = await _insert_arena(db_session, cid, name="Арена один")
    b = await _insert_arena(db_session, cid, name="Арена два")
    for arena in (a, b):
        await _session(db_session, arena, day=_tomorrow(), hhmm="10:00", adult=900, rental=300)
    await db_session.commit()
    html = await _get(f"/c/{city_slug('Молодечно')}")
    assert "b-seo" not in html and "b-tile__more" not in html
    assert "Частые вопросы" not in html
    assert 'id="rinks"' not in html


@pytest.mark.asyncio
async def test_minsk_hub_sql_budget_does_not_grow_with_rinks(app_use_test_db, db_session) -> None:
    cid = await _minsk(db_session)
    ids = [await _insert_arena(db_session, cid, name=f"Каток {i}") for i in range(2)]
    for aid in ids:
        await _session(db_session, aid, day=_tomorrow(), hhmm="10:00", adult=900, rental=300)
    await db_session.commit()
    bind = db_session.sync_session.get_bind()
    counts = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany):
        if (statement or "").lstrip().upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            counts["n"] += 1

    event.listen(bind, "before_cursor_execute", _before)
    try:
        await _get("/c/minsk")
        small = counts["n"]
        for i in range(10):
            aid = await _insert_arena(db_session, cid, name=f"Новый {i}")
            await _session(db_session, aid, day=_tomorrow(), hhmm="11:00", adult=900, rental=300)
        await db_session.commit()
        counts["n"] = 0
        await _get("/c/minsk")
        big = counts["n"]
    finally:
        event.remove(bind, "before_cursor_execute", _before)
    assert abs(big - small) <= 1, (small, big)
