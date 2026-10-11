"""TASK-201-B / TASK-224: /c/?kind=ohm и строка «Хоккей для любителей» на главной."""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_arenas import _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _mk(db_session, arena_id: int, *, day: date, hhmm: str) -> int:
    created = await create_ice_session(
        db_session,
        arena_id,
        local_date=day,
        starts_at_local=hhmm,
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=1000,
    )
    await db_session.flush()
    return int(created["id"])


async def _ohm(db_session, arena_id: int, *, day: date, hhmm: str) -> int:
    created = await create_ice_session(
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
    return int(created["id"])


@pytest.mark.asyncio
async def test_kind_ohm_lists_only_arenas_with_hockey_practice(app_use_test_db, db_session) -> None:
    name = f"Охминск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    ohm_rink = await _insert_arena(db_session, city_id, name=f"ОХМ-каток {uuid.uuid4().hex[:4]}")
    mk_only = await _insert_arena(db_session, city_id, name=f"Только-МК {uuid.uuid4().hex[:4]}")
    day = date.today() + timedelta(days=2)
    await _ohm(db_session, ohm_rink, day=day, hhmm="08:45")
    await _mk(db_session, mk_only, day=day, hhmm="15:00")
    await _mk(db_session, ohm_rink, day=day, hhmm="19:00")
    await db_session.commit()
    slug = city_slug(name)

    async with _client() as client:
        ohm_page = await client.get(f"/c/{slug}", params={"kind": "ohm"})
        all_page = await client.get(f"/c/{slug}")

    assert ohm_page.status_code == 200
    assert "Минск · хоккей" in ohm_page.text or f"{name} · хоккей" in ohm_page.text
    assert "открытая тренировка, ОХМ" in ohm_page.text
    assert "08:45" in ohm_page.text
    assert f"ОХМ-каток" in ohm_page.text or "ohm" in ohm_page.text.lower()
    assert "Только-МК" not in ohm_page.text
    assert "15:00" not in ohm_page.text
    # Массовое не смешивается: на обычной подборке ОХМ-время не в слотах МК-списка
    # (ОХМ-каток может быть в «все места», но 08:45 — только у kind=ohm).
    assert "08:45" not in all_page.text or "kind=ohm" in all_page.text


@pytest.mark.asyncio
async def test_ohm_centers_segment_lists_places_not_sessions(app_use_test_db, db_session) -> None:
    """kind=ohm — сеансы без центров; seg=centers — карточка места, без времени сеанса."""
    name = f"Центринск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    rink = await _insert_arena(db_session, city_id, name=f"ОХМ-сеанс {uuid.uuid4().hex[:4]}")
    center_name = f"Центр записи {uuid.uuid4().hex[:4]}"
    center = await _insert_arena(
        db_session,
        city_id,
        name=center_name,
        phone="+375 29 110-20-35",
        opening_hours={
            "center_badge": "Льда нет",
            "center_line": "Дорожка HST, бросковая зона.",
        },
    )
    await db_session.execute(
        text(
            """
            UPDATE arena_profiles
            SET amenities = COALESCE(amenities, '{}'::jsonb) || '{"hockey_center": true}'::jsonb
            WHERE arena_id = :id
            """
        ),
        {"id": center},
    )
    arena_slug = (
        await db_session.execute(
            text("SELECT slug FROM arena_profiles WHERE arena_id = :id"),
            {"id": center},
        )
    ).scalar_one()
    await _ohm(db_session, rink, day=date.today() + timedelta(days=2), hhmm="08:45")
    empty_name = f"Пустоцентр {uuid.uuid4().hex[:6]}"
    await _insert_city(db_session, name=empty_name)
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    place_href = f"/p/{slug}/{arena_slug}"

    async with _client() as client:
        ohm_page = await client.get(f"/c/{slug}", params={"kind": "ohm"})
        centers_page = await client.get(f"/c/{slug}", params={"kind": "ohm", "seg": "centers"})
        bad = await client.get(f"/c/{slug}", params={"kind": "ohm", "seg": "shops"})
        skate = await client.get(f"/c/{slug}", params={"t": "ice"})
        places = await client.get(f"/c/{slug}", params={"page": "1"})
        empty = await client.get(f"/c/{city_slug(empty_name)}", params={"kind": "ohm", "seg": "centers"})

    assert ohm_page.status_code == 200
    ohm_canon = re.search(r'<link rel="canonical" href="([^"]*)"', ohm_page.text)
    assert ohm_canon and ohm_canon.group(1).endswith(f"/c/{slug}?kind=ohm")
    assert "seg=" not in ohm_canon.group(1)
    assert "08:45" in ohm_page.text
    assert center_name not in ohm_page.text
    assert 'class="seg"' in ohm_page.text
    assert "Записи нет" in ohm_page.text
    assert f'class="chip chip--on" href="/c/{slug}?kind=ohm"' in ohm_page.text
    assert f'class="chip" href="/c/{slug}?kind=ohm&amp;seg=centers"' in ohm_page.text
    assert "Центры <small>1</small>" in ohm_page.text

    assert centers_page.status_code == 200
    html = centers_page.text
    canon = re.search(r'<link rel="canonical" href="([^"]*)"', html)
    assert canon and canon.group(1).endswith(f"/c/{slug}?kind=ohm&amp;seg=centers")
    assert f'<a class="sec pick" href="{place_href}">' in html
    assert center_name in html
    assert "Льда нет" in html
    assert "Дорожка HST" in html
    assert "08:45" not in html
    assert 'class="slot' not in html
    assert 'class="seg"' not in html
    assert "Записи нет" not in html
    assert "Позвать" not in html
    assert "Позвонить" not in html
    assert "По записи, не сеанс." in html
    assert "1 центр" in html
    assert f'class="chip chip--on" href="/c/{slug}?kind=ohm&amp;seg=centers"' in html

    assert bad.status_code == 200
    assert "08:45" in bad.text
    assert center_name not in bad.text

    assert skate.status_code == 200 and center_name not in skate.text
    assert places.status_code == 200 and center_name not in places.text

    assert empty.status_code == 200
    assert "Центров по записи нет" in empty.text
    assert 'class="seg"' not in empty.text
    assert "Записи нет" not in empty.text
    assert "Центры <small>0</small>" in empty.text


def _city_surface(html: str, city_name: str) -> str:
    """Карточка «ваш город» или плитка — то, где у города живёт пометка «ОХМ»."""
    hero = re.search(r'<a class="hero-city".*?</a>', html, re.S)
    if hero and city_name in hero.group(0):
        return hero.group(0)
    for match in re.finditer(r'<a class="city card[^"]*".*?</a>', html, re.S):
        if city_name in match.group(0):
            return match.group(0)
    raise AssertionError(city_name)


@pytest.mark.asyncio
async def test_home_ohm_line_and_tile_badge_only_with_future_ohm(app_use_test_db, db_session) -> None:
    """Строка «Хоккей для любителей» и «ОХМ» у города — только пока есть будущий ОХМ."""
    name = f"Чипинск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name, country="BY")
    rink = await _insert_arena(db_session, city_id, name=f"Чип-каток {uuid.uuid4().hex[:4]}")
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        before = await client.get("/", cookies={"glide_city": slug})
    assert before.status_code == 200
    assert "ОХМ" not in _city_surface(before.text, name)
    # В общей БД ОХМ уже может быть у других городов — тогда строка жива и до нашего сеанса.
    world_was_clean = "sub--ohm" not in before.text

    ohm_id = await _ohm(db_session, rink, day=date.today() + timedelta(days=1), hhmm="11:00")
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        after = await client.get("/", cookies={"glide_city": slug})
    assert after.status_code == 200
    assert '<p class="sub sub--ohm">Хоккей для любителей — ' in after.text
    assert "хоккей для любителей" in _city_surface(after.text, name)

    await db_session.execute(text("DELETE FROM ice_sessions WHERE id = :id"), {"id": ohm_id})
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        gone = await client.get("/", cookies={"glide_city": slug})
    assert gone.status_code == 200
    assert "ОХМ" not in _city_surface(gone.text, name)
    if world_was_clean:
        assert "sub--ohm" not in gone.text
