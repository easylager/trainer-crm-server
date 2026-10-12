"""TASK-240: одно правило «Заточки» — Python и SQL, одно число, бюджет SQL."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from src.api.app import app
from src.application.catalog_home_page import load_catalog_home_view
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from src.shared.catalog_sharpening import SHARPENING_MONTH_PARAM, SHARPENING_SECTION_SQL, row_in_sharpening_section
from src.shared.ice_discovery_scope import public_scope_params
from src.shared.notification_hours import NOTIFICATION_TZ
from tests.api.test_public_arenas import _insert_arena, _insert_bare_trainer, _insert_city

_MONTH = 10


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _count_sql(db_session):
    bind = db_session.sync_session.get_bind()
    counts = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany):
        head = (statement or "").lstrip().upper()
        if head.startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            counts["n"] += 1

    event.listen(bind, "before_cursor_execute", _before)
    return bind, counts, _before


async def _place(
    db_session,
    city_id: int,
    *,
    name: str,
    venue_type: str = "ice",
    amenities: dict | None = None,
    season: tuple[int, int] | None = None,
    is_active: bool = True,
    status: str = "published",
    created_by_trainer_id: int | None = None,
    has_photo: bool = True,
    country: str = "BY",
) -> int:
    arena_id = await _insert_arena(
        db_session,
        city_id,
        name=name,
        has_photo=has_photo,
        created_by_trainer_id=created_by_trainer_id,
    )
    await db_session.execute(
        text(
            """
            UPDATE arenas
            SET venue_type = :vt, is_active = :active
            WHERE id = :id
            """
        ),
        {"id": arena_id, "vt": venue_type, "active": is_active},
    )
    await db_session.execute(
        text(
            """
            UPDATE arena_profiles
            SET amenities = CAST(:amenities AS jsonb),
                status = :status,
                season_start_month = :start_m,
                season_end_month = :end_m
            WHERE arena_id = :id
            """
        ),
        {
            "id": arena_id,
            "amenities": json.dumps(amenities or {}),
            "status": status,
            "start_m": None if season is None else season[0],
            "end_m": None if season is None else season[1],
        },
    )
    if country != "BY":
        await db_session.execute(
            text("UPDATE cities SET country = :country WHERE id = :id"),
            {"id": city_id, "country": country},
        )
    return arena_id


_CASES = [
    {"id": "ice-sharpening", "venue": "ice", "amenities": {"skate_sharpening": True}, "expect": True},
    {"id": "shop-profiling", "venue": "shop", "amenities": {"blade_profiling": True}, "expect": True},
    {
        "id": "center-sharpening",
        "venue": "other",
        "amenities": {"hockey_center": True, "skate_sharpening": True},
        "expect": True,
    },
    {"id": "gym-sharpening", "venue": "gym", "amenities": {"skate_sharpening": True}, "expect": True},
    {"id": "ice-rental", "venue": "ice", "amenities": {"skate_rental": True}, "expect": False},
    {"id": "shop-molding", "venue": "shop", "amenities": {"skate_molding": True}, "expect": False},
    {"id": "shop-repair", "venue": "shop", "amenities": {"repair": True}, "expect": False},
    {"id": "roller-rental", "venue": "other", "amenities": {"skate_rental": True}, "expect": False},
    {
        "id": "closed-summer",
        "venue": "ice",
        "amenities": {"skate_sharpening": True},
        "season": (6, 8),
        "expect": False,
    },
    {
        "id": "wrap-open-in-october",
        "venue": "outdoor",
        "amenities": {"skate_sharpening": True},
        "season": (9, 4),
        "expect": True,
    },
    {
        "id": "wrap-closed-in-october",
        "venue": "ice",
        "amenities": {"blade_profiling": True},
        "season": (11, 3),
        "expect": False,
    },
    {
        "id": "string-true",
        "venue": "shop",
        "amenities": {"skate_sharpening": "true"},
        "expect": True,
    },
    {"id": "inactive", "venue": "ice", "amenities": {"skate_sharpening": True}, "is_active": False, "expect": False},
    {
        "id": "draft",
        "venue": "ice",
        "amenities": {"skate_sharpening": True},
        "status": "draft",
        "expect": False,
    },
    {"id": "no-photo-trainer", "venue": "ice", "amenities": {"skate_sharpening": True}, "trainer": True, "expect": False},
    {"id": "empty", "venue": "ice", "amenities": {}, "expect": False},
    {
        "id": "ru-city",
        "venue": "ice",
        "amenities": {"skate_sharpening": True},
        "country": "RU",
        "expect": False,
    },
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _CASES, ids=[case["id"] for case in _CASES])
async def test_python_predicate_matches_sql(case: dict, app_use_test_db, db_session) -> None:
    """Один месяц, одна строка: Python и SQL отвечают одинаково."""
    name = f"Правило {case['id']} {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name, country="BY")
    trainer_id = await _insert_bare_trainer(db_session) if case.get("trainer") else None
    arena_id = await _place(
        db_session,
        city_id,
        name=name,
        venue_type=case["venue"],
        amenities=case["amenities"],
        season=case.get("season"),
        is_active=case.get("is_active", True),
        status=case.get("status", "published"),
        created_by_trainer_id=trainer_id,
        has_photo=not case.get("trainer"),
        country=case.get("country", "BY"),
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            text(
                f"""
                SELECT a.is_active, a.is_confirmed, a.created_by_trainer_id, a.venue_type,
                       p.amenities, p.season_start_month, p.season_end_month,
                       p.status AS profile_status,
                       c.country, c.is_active AS city_is_active,
                       EXISTS (
                           SELECT 1 FROM media m
                           WHERE m.owner_type = 'arena' AND m.owner_id = a.id
                             AND m.status = 'published'
                       ) AS has_photo,
                       ({SHARPENING_SECTION_SQL}) AS in_section
                FROM arenas a
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                JOIN cities c ON c.id = a.city_id
                WHERE a.id = :id
                """
            ),
            {"id": arena_id, SHARPENING_MONTH_PARAM: _MONTH, **public_scope_params()},
        )
    ).mappings().one()
    python_in = row_in_sharpening_section(row, month=_MONTH)
    assert python_in is bool(row["in_section"])
    assert python_in is case["expect"]


def _minsk_month() -> int:
    return datetime.now(ZoneInfo(NOTIFICATION_TZ)).month


@pytest.mark.asyncio
async def test_one_number_across_hub_list_api_and_home(app_use_test_db, db_session) -> None:
    """Трасса, формовка, прокат и закрытый сезон не входят. В разделе ровно два места."""
    name = f"Одночисло {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    month = _minsk_month()
    closed_month = 1 if month != 1 else 2
    track = "Лыжероллерная трасса"
    shop_sharp = "Магазин с заточкой"
    shop_mold = "Магазин только формовка"
    rink_rent = "Каток только прокат"
    rink_sharp = "Каток с заточкой"
    rink_closed = "Закрытый каток с заточкой"
    await _place(db_session, city_id, name=track, venue_type="other", amenities={"skate_rental": True})
    await _place(db_session, city_id, name=shop_sharp, venue_type="shop", amenities={"skate_sharpening": True})
    await _place(db_session, city_id, name=shop_mold, venue_type="shop", amenities={"skate_molding": True})
    await _place(db_session, city_id, name=rink_rent, venue_type="ice", amenities={"skate_rental": True})
    await _place(db_session, city_id, name=rink_sharp, venue_type="ice", amenities={"skate_sharpening": True})
    await _place(
        db_session,
        city_id,
        name=rink_closed,
        venue_type="ice",
        amenities={"skate_sharpening": True},
        season=(closed_month, closed_month),
    )
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        hub = await client.get(f"/c/{slug}")
        service = await client.get(f"/c/{slug}", params={"svc": "service"})
        sharpening = await client.get(f"/c/{slug}", params={"svc": "sharpening"})
        rental = await client.get(f"/c/{slug}", params={"svc": "rental"})
        api = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": city_id, "intent": "skate", "svc": "service", "limit": 50},
        )
        api_plain = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": city_id, "intent": "skate", "limit": 50},
        )
    assert hub.status_code == service.status_code == sharpening.status_code == 200
    assert "2 места" in hub.text
    for page in (service.text, sharpening.text):
        assert shop_sharp in page and rink_sharp in page
        assert track not in page
        assert shop_mold not in page
        assert rink_rent not in page
        assert rink_closed not in page
    assert rink_rent in rental.text
    assert track not in rental.text
    body = api.json()
    names = {item["name"] for item in body["items"]}
    assert names == {shop_sharp, rink_sharp}
    assert body["service_count"] == body["total"] == 2
    assert api_plain.json()["service_count"] == 2

    home = await load_catalog_home_view(db_session)
    city = next(item for item in home["cities"] if int(item["id"]) == city_id)
    assert city["has_sharpening"] is True


@pytest.mark.asyncio
async def test_selection_service_sql_does_not_grow_with_places(app_use_test_db, db_session) -> None:
    """SSR /c/{город}?svc=service: число SQL не растёт с числом мест."""

    async def _city_with(n: int) -> str:
        name = f"Бюджет {n} {uuid.uuid4().hex[:6]}"
        city_id = await _insert_city(db_session, name=name)
        for i in range(n):
            await _place(
                db_session,
                city_id,
                name=f"Заточка {i}",
                venue_type="shop" if i % 2 else "ice",
                amenities={"skate_sharpening": True},
            )
        await db_session.commit()
        invalidate_public_city_cache()
        return city_slug(name)

    slug_few = await _city_with(2)
    bind, counts, before = _count_sql(db_session)
    try:
        async with _client() as client:
            few = await client.get(f"/c/{slug_few}", params={"svc": "service"})
        few_n = counts["n"]
    finally:
        event.remove(bind, "before_cursor_execute", before)
    assert few.status_code == 200, few.text

    slug_many = await _city_with(8)
    bind, counts, before = _count_sql(db_session)
    try:
        async with _client() as client:
            many = await client.get(f"/c/{slug_many}", params={"svc": "service"})
        many_n = counts["n"]
    finally:
        event.remove(bind, "before_cursor_execute", before)
    assert many.status_code == 200, many.text
    assert few_n == many_n
    assert "8 мест" in many.text or "8 место" in many.text
