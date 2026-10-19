"""Подборка «Для вас»: счёт, фото, вид, закрепы, флаг."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.city_picks import clear_for_you_cache, for_you, pin_place

_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _reset_for_you_cache():
    clear_for_you_cache()
    yield
    clear_for_you_cache()


async def _city(db_session) -> tuple[int, str]:
    name = f"FY{uuid.uuid4().hex[:8]}"
    city_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO cities (name, country, price_group, is_active)
                    VALUES (:name, 'BY', 'BY_BASE', true)
                    RETURNING id
                    """
                ),
                {"name": name},
            )
        ).scalar_one()
    )
    await db_session.flush()
    return city_id, name


async def _place(
    db_session,
    city_id: int,
    *,
    name: str,
    venue_type: str = "shop",
    amenities: dict | None = None,
    photo: bool = False,
) -> int:
    arena_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO arenas (city_id, name, address, venue_type, is_active, is_confirmed)
                    VALUES (:city_id, :name, 'ул. Тестовая, 1', :venue_type, true, true)
                    RETURNING id
                    """
                ),
                {"city_id": city_id, "name": name, "venue_type": venue_type},
            )
        ).scalar_one()
    )
    slug = f"p{arena_id}"
    await db_session.execute(
        text(
            """
            INSERT INTO arena_profiles (arena_id, city_id, slug, status, amenities)
            VALUES (:arena_id, :city_id, :slug, 'published', CAST(:amenities AS jsonb))
            """
        ),
        {
            "arena_id": arena_id,
            "city_id": city_id,
            "slug": slug,
            "amenities": json.dumps(amenities or {}),
        },
    )
    if photo:
        await db_session.execute(
            text(
                """
                INSERT INTO media (owner_type, owner_id, storage_key, variants, license, status)
                VALUES (
                    'arena', :arena_id, :key,
                    CAST(:variants AS jsonb), 'own', 'published'
                )
                """
            ),
            {
                "arena_id": arena_id,
                "key": f"arenas/{arena_id}/card.jpg",
                "variants": json.dumps({"card": f"arenas/{arena_id}/card.jpg"}),
            },
        )
    await db_session.flush()
    return arena_id


async def _event(db_session, *, city_id: int, arena_id: int, kind: str, at: datetime) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO catalog_consumer_events (kind, surface, city_id, arena_id, occurred_at)
            VALUES (:kind, 'place', :city_id, :arena_id, :at)
            """
        ),
        {"kind": kind, "city_id": city_id, "arena_id": arena_id, "at": at},
    )


def _enable(monkeypatch, city_id: int) -> None:
    monkeypatch.setenv("FOR_YOU_CITY_IDS", str(city_id))
    clear_for_you_cache()


@pytest.mark.asyncio
async def test_for_you_ranks_photo_score_and_breaks_a_third_of_the_same_kind(db_session, monkeypatch) -> None:
    city_id, name = await _city(db_session)
    _enable(monkeypatch, city_id)
    beta = await _place(db_session, city_id, name="Бета", photo=True)
    alpha = await _place(db_session, city_id, name="Альфа", photo=True)
    no_photo = await _place(db_session, city_id, name="Яхта", photo=False)
    gym = await _place(db_session, city_id, name="Гамма", venue_type="gym", photo=False)
    ice = await _place(db_session, city_id, name="Каток", venue_type="ice", photo=True)
    outdoor = await _place(db_session, city_id, name="Уличный каток", venue_type="outdoor", photo=True)
    recent = _NOW - timedelta(days=1)
    await _event(db_session, city_id=city_id, arena_id=beta, kind="public_contact_click", at=recent)
    await _event(db_session, city_id=city_id, arena_id=beta, kind="public_contact_click", at=recent)
    await _event(db_session, city_id=city_id, arena_id=alpha, kind="public_page_view", at=recent)
    for _ in range(10):
        await _event(db_session, city_id=city_id, arena_id=no_photo, kind="public_page_view", at=recent)
    for _ in range(20):
        await _event(db_session, city_id=city_id, arena_id=ice, kind="public_page_view", at=recent)
        await _event(db_session, city_id=city_id, arena_id=outdoor, kind="public_page_view", at=recent)
    await _event(
        db_session,
        city_id=city_id,
        arena_id=beta,
        kind="public_page_view",
        at=_NOW - timedelta(days=31),
    )
    await db_session.flush()

    items = await for_you(db_session, city_id, now=_NOW)
    ids = [item["arena_id"] for item in items]
    assert ice not in ids
    assert outdoor not in ids
    assert ids[0] == beta
    assert ids[1] == alpha
    assert ids[2] == gym
    assert no_photo not in ids
    assert items[0]["kind_label"] == "Магазин"
    assert items[0]["photo_url"]
    assert items[2]["photo_url"] is None
    assert items[0]["pinned"] is False
    assert items[0]["path"] == f"/p/{name.lower()}/{items[0]['slug']}"
    assert set(items[0]) == {"arena_id", "slug", "name", "kind_label", "photo_url", "path", "pinned"}


@pytest.mark.asyncio
async def test_sharpening_label_and_name_tie(db_session, monkeypatch) -> None:
    city_id, _name = await _city(db_session)
    _enable(monkeypatch, city_id)
    beta = await _place(db_session, city_id, name="Бета", photo=True)
    alpha = await _place(
        db_session,
        city_id,
        name="Альфа",
        photo=True,
        amenities={"blade_profiling": True},
    )
    await db_session.flush()
    items = await for_you(db_session, city_id, now=_NOW)
    assert [item["arena_id"] for item in items] == [alpha, beta]
    assert items[0]["kind_label"] == "Заточка"
    assert items[1]["kind_label"] == "Магазин"


@pytest.mark.asyncio
async def test_two_candidates_stay_two_and_none_stay_empty(db_session, monkeypatch) -> None:
    city_id, _name = await _city(db_session)
    _enable(monkeypatch, city_id)
    await _place(db_session, city_id, name="Раз", photo=True)
    await _place(db_session, city_id, name="Два", photo=True)
    await db_session.flush()
    assert len(await for_you(db_session, city_id, now=_NOW)) == 2

    empty_id, _empty_name = await _city(db_session)
    _enable(monkeypatch, empty_id)
    await _place(db_session, empty_id, name="Только лёд", venue_type="ice", photo=True)
    await db_session.flush()
    assert await for_you(db_session, empty_id, now=_NOW) == []


@pytest.mark.asyncio
async def test_pin_holds_position_and_ice_is_allowed(db_session, monkeypatch) -> None:
    city_id, _name = await _city(db_session)
    _enable(monkeypatch, city_id)
    first = await _place(db_session, city_id, name="Альфа", photo=True)
    third = await _place(db_session, city_id, name="Гамма", venue_type="gym", photo=True)
    rink = await _place(db_session, city_id, name="Каток", venue_type="ice", photo=True)
    await pin_place(db_session, city_id, 2, rink)
    items = await for_you(db_session, city_id, now=_NOW)
    assert [item["arena_id"] for item in items] == [first, rink, third]
    assert items[1]["pinned"] is True
    assert items[0]["pinned"] is False
    assert items[2]["pinned"] is False
    assert rink not in (items[0]["arena_id"], items[2]["arena_id"])


@pytest.mark.asyncio
async def test_flag_off_hides_picks_but_keeps_pins(db_session, monkeypatch) -> None:
    city_id, _name = await _city(db_session)
    shop = await _place(db_session, city_id, name="Магазин", photo=True)
    await pin_place(db_session, city_id, 1, shop)
    monkeypatch.setenv("FOR_YOU_CITY_IDS", "")
    clear_for_you_cache()
    assert await for_you(db_session, city_id, now=_NOW) == []
    still = (
        await db_session.execute(
            text("SELECT arena_id FROM city_picks WHERE city_id = :city_id AND position = 1"),
            {"city_id": city_id},
        )
    ).scalar_one()
    assert int(still) == shop


def test_rink_with_sharpening_is_labelled_as_rink() -> None:
    from src.application.city_picks import section_kind

    kind, label = section_kind({"venue_type": "ice", "amenities": {"skate_sharpening": True}}, month=10)
    assert kind == "ice"
    assert label != "Заточка"
