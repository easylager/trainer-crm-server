"""Collective Wave P1.6: brand kit fields (cover, about, gallery, accent)."""
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.collective
from sqlalchemy import text

from src.application.brand_presentation import ACCENT_PRESETS, normalize_default_city_id, resolve_accent_preset
from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    build_collective_catalog_webapp_url,
    collective_location_payload,
    collective_storage_key_allowed,
    update_collective_brand,
)


@pytest.mark.asyncio
async def test_update_collective_brand_kit_about_and_accent(db_session) -> None:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO collectives (slug, display_name, status, seat_limit, created_at, updated_at)
            VALUES ('kit-studio', 'Kit Studio', :st, 5, :now, :now)
            RETURNING id
            """
        ),
        {"st": COLLECTIVE_STATUS_ACTIVE, "now": now},
    )
    cid = int(r.scalar_one())
    r_tr = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    tid = int(r_tr.scalar_one())
    await db_session.execute(
        text("UPDATE collectives SET owner_trainer_id = :tid WHERE id = :cid"),
        {"tid": tid, "cid": cid},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
            VALUES (:cid, :tid, :role, :active, :now)
            """
        ),
        {"cid": cid, "tid": tid, "role": MEMBER_ROLE_OWNER, "active": MEMBER_STATUS_ACTIVE, "now": now},
    )
    await db_session.commit()

    logo_key = f"collectives/{cid}/logo_abc.jpg"
    assert collective_storage_key_allowed(cid, logo_key)
    assert not collective_storage_key_allowed(cid, "trainers/1/x.jpg")

    updated = await update_collective_brand(
        db_session,
        collective_id=cid,
        trainer_id=tid,
        about="Студия для тех, кто любит движение.",
        accent_preset="forest",
        contacts={"address": "Минск, центр", "instagram": "@kit"},
    )
    assert updated is not None
    assert updated.get("about") == "Студия для тех, кто любит движение."
    assert updated.get("accent_preset") == "forest"
    assert updated.get("contacts", {}).get("address") == "Минск, центр"

    updated2 = await update_collective_brand(
        db_session,
        collective_id=cid,
        trainer_id=tid,
        logo_key=logo_key,
    )
    assert updated2 is not None
    assert updated2.get("logo_key") == logo_key


def test_resolve_accent_preset_fallback() -> None:
    accent = resolve_accent_preset("unknown-preset")
    assert accent["id"] in ACCENT_PRESETS


def test_normalize_default_city_id() -> None:
    assert normalize_default_city_id(3) == 3
    assert normalize_default_city_id("5") == 5
    assert normalize_default_city_id(0) is None
    assert normalize_default_city_id("bad") is None


def test_build_collective_catalog_webapp_url_with_city(monkeypatch) -> None:
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://example.test")
    url = build_collective_catalog_webapp_url("ice-yoga", default_city_id=2)
    assert url == "https://example.test/webapp/catalog?collective=ice-yoga&tab=catalog&city_id=2"


@pytest.mark.asyncio
async def test_update_collective_location_fields(db_session) -> None:
    city_row = await db_session.execute(text("SELECT id FROM cities WHERE is_active LIMIT 1"))
    city_id = city_row.scalar()
    if city_id is None:
        pytest.skip("seed must contain an active city")
    arena_row = await db_session.execute(
        text("SELECT id FROM arenas WHERE city_id = :cid AND is_active LIMIT 1"),
        {"cid": city_id},
    )
    arena_id = arena_row.scalar()
    if arena_id is None:
        pytest.skip("seed must contain an active arena")

    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO collectives (slug, display_name, status, seat_limit, created_at, updated_at)
            VALUES ('loc-studio', 'Loc Studio', :st, 5, :now, :now)
            RETURNING id
            """
        ),
        {"st": COLLECTIVE_STATUS_ACTIVE, "now": now},
    )
    cid = int(r.scalar_one())
    r_tr = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    tid = int(r_tr.scalar_one())
    await db_session.execute(
        text("UPDATE collectives SET owner_trainer_id = :tid WHERE id = :cid"),
        {"tid": tid, "cid": cid},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
            VALUES (:cid, :tid, :role, :active, :now)
            """
        ),
        {"cid": cid, "tid": tid, "role": MEMBER_ROLE_OWNER, "active": MEMBER_STATUS_ACTIVE, "now": now},
    )
    await db_session.commit()

    updated = await update_collective_brand(
        db_session,
        collective_id=cid,
        trainer_id=tid,
        default_city_id=int(city_id),
        primary_arena_id=int(arena_id),
    )
    assert updated is not None
    assert updated.get("default_city_id") == int(city_id)
    assert updated.get("primary_arena_id") == int(arena_id)
    assert updated.get("primary_arena_name")
    assert "city_id=" in (updated.get("catalog_webapp_url") or "")

    row = await db_session.execute(
        text("SELECT slug, brand_tokens, primary_arena_id FROM collectives WHERE id = :cid"),
        {"cid": cid},
    )
    db_row = row.fetchone()
    assert db_row is not None
    location = await collective_location_payload(
        db_session,
        {
            "slug": db_row[0],
            "brand_tokens": db_row[1],
            "primary_arena_id": db_row[2],
        },
    )
    assert location["default_city_id"] == int(city_id)
    assert location["primary_arena_id"] == int(arena_id)
