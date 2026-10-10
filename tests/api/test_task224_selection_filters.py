"""TASK-224: окна ОХМ и фильтр услуг на /c/{город}."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import city_slug
from src.application.ice_session_use_cases import create_ice_session
from src.application.selection_page import (
    clean_svc,
    compose_selection_share,
    load_selection_view,
    render_selection_page,
)
from tests.api.test_public_arenas import _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _ohm(db_session, arena_id: int, *, day: date, hhmm: str) -> None:
    await create_ice_session(
        db_session,
        arena_id,
        local_date=day,
        starts_at_local=hhmm,
        duration_minutes=60,
        kind="hockey_practice",
        price_adult_minor=1700,
        price_child_minor=None,
        price_rental_minor=None,
        session_label="большая арена",
    )
    await db_session.flush()


async def _profile(
    db_session,
    arena_id: int,
    *,
    amenities: dict | None = None,
    opening_hours: dict | None = None,
    venue_type: str | None = None,
    phone: str | None = None,
) -> None:
    if venue_type:
        await db_session.execute(
            text("UPDATE arenas SET venue_type = :vt WHERE id = :id"),
            {"vt": venue_type, "id": arena_id},
        )
    sets: list[str] = []
    params: dict = {"id": arena_id}
    if amenities is not None:
        sets.append("amenities = CAST(:amenities AS jsonb)")
        params["amenities"] = json.dumps(amenities)
    if opening_hours is not None:
        sets.append("opening_hours = CAST(:hours AS jsonb)")
        params["hours"] = json.dumps(opening_hours)
    if phone is not None:
        sets.append("phone = :phone")
        params["phone"] = phone
    if sets:
        await db_session.execute(
            text(f"UPDATE arena_profiles SET {', '.join(sets)} WHERE arena_id = :id"),
            params,
        )


def _weekend_saturday(from_day: date) -> date:
    """Суббота окна «Сб–Вс» — как в ice_time_windows.resolve_window('weekend')."""
    if from_day.weekday() in (5, 6):
        return from_day - timedelta(days=from_day.weekday() - 5)
    return from_day + timedelta(days=5 - from_day.weekday())


@pytest.mark.asyncio
async def test_ohm_weekend_window_and_seg_counts(app_use_test_db, db_session) -> None:
    name = f"Окнинск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    rink = await _insert_arena(db_session, city_id, name=f"ОХМ-уик {uuid.uuid4().hex[:4]}")
    today = date.today()
    saturday = _weekend_saturday(today)
    sunday = saturday + timedelta(days=1)
    monday = saturday + timedelta(days=2)
    # Воскресенье внутри окна «Сб–Вс»; понедельник 18:00 — уже за пределами.
    await _ohm(db_session, rink, day=sunday, hhmm="10:30")
    await _ohm(db_session, rink, day=monday, hhmm="18:00")
    await db_session.commit()
    slug = city_slug(name)

    async with _client() as client:
        page = await client.get(f"/c/{slug}", params={"kind": "ohm", "w": "weekend"})

    assert page.status_code == 200
    html = page.text
    assert "10:30" in html
    assert "18:00" not in html
    assert re.search(r'Сб–Вс[^<]*<small>\d+</small>', html)
    assert re.search(r'<span class="on">\s*Сб–Вс', html) or 'class="on">Сб–Вс' in html


@pytest.mark.asyncio
async def test_svc_sharpening_lists_and_sorts_open_first(app_use_test_db, db_session) -> None:
    name = f"Заточинск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    city_row = {"id": city_id, "name": name, "country": "BY"}
    open_shop = await _insert_arena(db_session, city_id, name=f"Мастерская {uuid.uuid4().hex[:4]}")
    open_rink = await _insert_arena(db_session, city_id, name=f"Каток+заточка {uuid.uuid4().hex[:4]}")
    plain_rink = await _insert_arena(db_session, city_id, name=f"Без услуг {uuid.uuid4().hex[:4]}")
    closed_shop = await _insert_arena(db_session, city_id, name=f"Закрытая {uuid.uuid4().hex[:4]}")
    daily = {"daily": {"open": "00:00", "close": "23:59"}}
    closed_week = {
        "weekly": {
            "mon": None,
            "tue": None,
            "wed": None,
            "thu": None,
            "fri": None,
            "sat": None,
            "sun": None,
        }
    }
    await _profile(
        db_session,
        open_shop,
        venue_type="shop",
        amenities={"skate_sharpening": True},
        opening_hours=daily,
        phone="+375 29 111-22-33",
    )
    await _profile(
        db_session,
        open_rink,
        venue_type="ice",
        amenities={"skate_sharpening": True},
        opening_hours=daily,
    )
    await _profile(db_session, plain_rink, venue_type="ice", amenities={"skate_rental": True})
    await _profile(
        db_session,
        closed_shop,
        venue_type="shop",
        amenities={"skate_sharpening": True},
        opening_hours=closed_week,
    )
    await db_session.commit()

    view = await load_selection_view(
        db_session, city=city_row, venue=None, when=None, svc="sharpening"
    )
    names = [str(i.get("name")) for i in view["items"]]
    assert "Без услуг" not in names
    assert len(names) >= 2
    # «open» днём, «soon» в последний час перед закрытием — оба значат «открыто сейчас».
    assert view["items"][0].get("open_state", {}).get("state") in ("open", "soon")
    assert int(view.get("open_now_count") or 0) >= 1
    share = compose_selection_share(view, page_url="http://test/c/x")
    html = render_selection_page(
        view,
        canonical_url="http://test/c/x",
        og_image_url="http://test/og.png",
        cta_url=None,
        share=share,
        city_page_url=None,
        base_url="http://test",
    )
    assert "Позвонить" in html
    assert names[0] in html


def test_clean_svc_unit() -> None:
    assert clean_svc("sharpening") == "sharpening"
    assert clean_svc(" rental ") == "rental"
    assert clean_svc("service") == "service"
    assert clean_svc("ice") is None
    assert clean_svc(None) is None


@pytest.mark.asyncio
async def test_city_selection_still_hides_shops_without_svc(app_use_test_db, db_session) -> None:
    name = f"Регресс {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    shop_name = f"Секретный магазин {uuid.uuid4().hex[:4]}"
    rink_name = f"Каток {uuid.uuid4().hex[:4]}"
    shop = await _insert_arena(db_session, city_id, name=shop_name)
    rink = await _insert_arena(db_session, city_id, name=rink_name)
    await _profile(db_session, shop, venue_type="shop", amenities={"skate_sharpening": True})
    day = date.today() + timedelta(days=1)
    await create_ice_session(
        db_session,
        rink,
        local_date=day,
        starts_at_local="12:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=1000,
    )
    await db_session.commit()
    slug = city_slug(name)

    async with _client() as client:
        # /c/{город} без параметров — хаб (TASK-224); список «все места» — с любым параметром.
        page = await client.get(f"/c/{slug}", params={"page": "1"})

    assert page.status_code == 200
    assert shop_name not in page.text
    assert rink_name in page.text
