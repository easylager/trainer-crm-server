"""TASK-051: public read-only Ice API (list, card, sessions, trainers, search)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from src.api.app import app
from src.application.arena_profile import backfill_arena_profiles, ensure_arena_profile
from src.application.ice_session_use_cases import create_ice_session
from src.infrastructure.db.models import SUBSCRIPTION_TIER_ONLINE
from tests.api.test_public_catalog_integration import _create_active_trainer_via_api
from tests.api.test_webapp_client_miniapp_integration import _ensure_trainer_subscription_tier
from tests.db_catalog_helpers import require_seed_service_id


REPO_ROOT = Path(__file__).resolve().parents[2]


async def _insert_city(db_session, *, name: str, country: str = "BY") -> int:
    ins = await db_session.execute(
        text(
            """
            INSERT INTO cities (name, country, price_group, is_active, sort_order)
            VALUES (:name, :c, :pg, true, 9000)
            RETURNING id
            """
        ),
        {
            "name": name,
            "c": country,
            "pg": "BY_BASE" if country == "BY" else "RU_BASE",
        },
    )
    return int(ins.scalar_one())


async def _insert_arena(
    db_session,
    city_id: int,
    *,
    name: str,
    address: str = "ул. Ледовая, 1",
    latitude: float | None = 53.9,
    longitude: float | None = 27.56,
    district: str | None = "Центр",
    phone: str | None = None,
    website_url: str | None = None,
    opening_hours: dict | None = None,
) -> int:
    ins = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, latitude, longitude, is_active, is_confirmed)
            VALUES (:cid, :name, :addr, :lat, :lon, true, true)
            RETURNING id
            """
        ),
        {
            "cid": city_id,
            "name": name,
            "addr": address,
            "lat": latitude,
            "lon": longitude,
        },
    )
    arena_id = int(ins.scalar_one())
    slug = await ensure_arena_profile(
        db_session, arena_id, city_id=city_id, name=name, district=district
    )
    await db_session.execute(
        text(
            """
            UPDATE arena_profiles
            SET district = :district,
                phone = :phone,
                website_url = :website,
                opening_hours = CAST(:hours AS jsonb)
            WHERE arena_id = :id
            """
        ),
        {
            "id": arena_id,
            "district": district,
            "phone": phone,
            "website": website_url,
            "hours": None if opening_hours is None else __import__("json").dumps(opening_hours),
        },
    )
    del slug
    await db_session.flush()
    return arena_id


async def _add_future_session(
    db_session,
    arena_id: int,
    *,
    days_ahead: int = 2,
    starts_at_local: str = "13:00",
    price_adult_minor: int = 850,
    valid_until: datetime | None = None,
    observed_at: datetime | None = None,
) -> int:
    local_date = date.today() + timedelta(days=days_ahead)
    created = await create_ice_session(
        db_session,
        arena_id,
        local_date=local_date,
        starts_at_local=starts_at_local,
        duration_minutes=45,
        kind="public_skate",
        price_adult_minor=price_adult_minor,
        price_child_minor=600,
        price_rental_minor=1200,
    )
    session_id = int(created["id"])
    if valid_until is not None or observed_at is not None:
        await db_session.execute(
            text(
                """
                UPDATE ice_sessions
                SET valid_until = COALESCE(:vu, valid_until),
                    observed_at = COALESCE(:obs, observed_at)
                WHERE id = :id
                """
            ),
            {"id": session_id, "vu": valid_until, "obs": observed_at},
        )
    await db_session.flush()
    return session_id


@pytest.mark.asyncio
async def test_ice_list_city_bbox_near_keeps_arena_without_coords(
    app_use_test_db, db_session
) -> None:
    """AC-001: city_id / bbox / near; arena without coords stays in the city list."""
    cid = await _insert_city(db_session, name=f"IceList-{uuid.uuid4().hex[:6]}")
    with_coords = await _insert_arena(
        db_session, cid, name="Каток с координатами", latitude=53.90, longitude=27.56
    )
    no_coords = await _insert_arena(
        db_session,
        cid,
        name="Каток без координат",
        latitude=None,
        longitude=None,
        phone="+375 17 000 00 00",
    )
    await _add_future_session(db_session, with_coords)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        by_city = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": cid, "intent": "coach", "limit": 50},
        )
        bbox = await client.get(
            "/api/public/ice/arenas",
            params={"bbox": "53.8,27.4,54.0,27.7", "intent": "coach", "limit": 50},
        )
        near = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": cid, "near": "53.90,27.56", "intent": "coach", "limit": 50},
        )
    assert by_city.status_code == 200, by_city.text
    city_ids = {it["id"] for it in by_city.json()["items"]}
    assert with_coords in city_ids
    assert no_coords in city_ids
    no_coords_row = next(it for it in by_city.json()["items"] if it["id"] == no_coords)
    assert no_coords_row["latitude"] is None
    assert no_coords_row["on_map"] is False

    assert bbox.status_code == 200, bbox.text
    bbox_ids = {it["id"] for it in bbox.json()["items"]}
    assert with_coords in bbox_ids
    assert no_coords not in bbox_ids

    assert near.status_code == 200, near.text
    near_ids = {it["id"] for it in near.json()["items"]}
    assert with_coords in near_ids
    assert no_coords in near_ids
    with_row = next(it for it in near.json()["items"] if it["id"] == with_coords)
    assert with_row["distance_km"] is not None
    missing_row = next(it for it in near.json()["items"] if it["id"] == no_coords)
    assert missing_row["distance_km"] is None


@pytest.mark.asyncio
async def test_tier_is_computed_on_read_without_data_tier_column(
    app_use_test_db, db_session
) -> None:
    """AC-002: sessions → A; cancel them → B; no stored data_tier column."""
    models = (REPO_ROOT / "src/infrastructure/db/models.py").read_text(encoding="utf-8")
    assert "data_tier" not in models

    cid = await _insert_city(db_session, name=f"IceTier-{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(
        db_session,
        cid,
        name="Арена с расписанием",
        phone="+375 17 111 11 11",
        website_url="https://rink.example",
    )
    sid = await _add_future_session(db_session, arena_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": cid, "intent": "skate", "limit": 20},
        )
        assert listed.status_code == 200, listed.text
        items = listed.json()["items"]
        assert [it["id"] for it in items] == [arena_id]
        assert items[0]["tier"] == "A"

        await db_session.execute(
            text("UPDATE ice_sessions SET status = 'cancelled' WHERE id = :id"),
            {"id": sid},
        )
        await db_session.flush()

        after = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": cid, "intent": "coach", "limit": 20},
        )
        skate_after = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": cid, "intent": "skate", "limit": 20},
        )
    assert after.status_code == 200, after.text
    row = next(it for it in after.json()["items"] if it["id"] == arena_id)
    assert row["tier"] == "B"
    assert skate_after.status_code == 200, skate_after.text
    assert all(it["id"] != arena_id for it in skate_after.json()["items"])


@pytest.mark.asyncio
async def test_skate_intent_lists_only_arenas_with_future_public_ice(
    app_use_test_db, db_session
) -> None:
    """Owner rule (overrides AC-003): intent=skate requires a future public_skate|open_ice slot."""
    cid = await _insert_city(db_session, name=f"IceIntent-{uuid.uuid4().hex[:6]}")
    skate = await _insert_arena(db_session, cid, name="Лёд с сеансом", phone="+375 17 1")
    profile_only = await _insert_arena(
        db_session, cid, name="Лёд без сеанса", phone="+375 17 2", website_url="https://x.example"
    )
    await _add_future_session(db_session, skate)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        skate_list = await client.get(
            "/api/public/ice/arenas", params={"city_id": cid, "intent": "skate"}
        )
        coach_list = await client.get(
            "/api/public/ice/arenas", params={"city_id": cid, "intent": "coach"}
        )
        group_list = await client.get(
            "/api/public/ice/arenas", params={"city_id": cid, "intent": "group"}
        )
    skate_ids = {it["id"] for it in skate_list.json()["items"]}
    coach_ids = {it["id"] for it in coach_list.json()["items"]}
    group_ids = {it["id"] for it in group_list.json()["items"]}
    assert skate_ids == {skate}
    assert profile_only in coach_ids
    assert profile_only in group_ids
    skate_row = skate_list.json()["items"][0]
    assert skate_row["live"]["kind"] == "session"
    assert skate_row["live"]["currency_code"]
    coach_row = next(it for it in coach_list.json()["items"] if it["id"] == skate)
    assert coach_row["live"]["kind"] == "trainers"
    group_row = next(it for it in group_list.json()["items"] if it["id"] == skate)
    assert group_row["live"]["kind"] == "groups"


@pytest.mark.asyncio
async def test_expired_sessions_are_not_current_in_list_or_feed(
    app_use_test_db, db_session
) -> None:
    """AC-004: valid_until in the past or ends_at < now must not appear as current."""
    cid = await _insert_city(db_session, name=f"IceExp-{uuid.uuid4().hex[:6]}")
    expired_valid = await _insert_arena(db_session, cid, name="Просрочен valid_until")
    past_end = await _insert_arena(db_session, cid, name="Просрочен ends_at")
    live = await _insert_arena(db_session, cid, name="Актуальный сеанс")
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    future = datetime.now(timezone.utc) + timedelta(days=3)
    await _add_future_session(db_session, expired_valid, valid_until=past)
    await _add_future_session(db_session, live, valid_until=future)

    await create_ice_session(
        db_session,
        past_end,
        local_date=date.today() - timedelta(days=2),
        starts_at_local="11:00",
        duration_minutes=45,
        kind="public_skate",
        price_adult_minor=800,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get(
            "/api/public/ice/arenas", params={"city_id": cid, "intent": "skate"}
        )
        feed_expired = await client.get(f"/api/public/arenas/{expired_valid}/sessions")
        feed_past = await client.get(f"/api/public/arenas/{past_end}/sessions")
        feed_live = await client.get(f"/api/public/arenas/{live}/sessions")
    assert {it["id"] for it in listed.json()["items"]} == {live}

    def _session_ids(payload: dict) -> set[int]:
        ids: set[int] = set()
        for day in payload.get("days") or []:
            for slot in day.get("sessions") or []:
                ids.add(int(slot["id"]))
                assert "parser_key" not in slot
                assert "raw_html" not in slot
        return ids

    assert _session_ids(feed_expired.json()) == set()
    assert _session_ids(feed_past.json()) == set()
    live_ids = _session_ids(feed_live.json())
    assert len(live_ids) == 1
    slot = feed_live.json()["days"][0]["sessions"][0]
    assert slot["kind"] == "public_skate"
    assert slot["price_adult_minor"] == 850
    assert slot["price_child_minor"] == 600
    assert slot["price_rental_minor"] == 1200
    assert slot["currency_code"]
    assert slot["local_date"]


@pytest.mark.asyncio
async def test_catalog_arena_ids_filter_accepts_forty_or_flags_truncation(
    app_use_test_db, db_session
) -> None:
    """AC-005: 40 arena ids are applied, or the response marks truncation explicitly."""
    ids_40 = ",".join(str(i) for i in range(10_001, 10_041))
    ids_300 = ",".join(str(i) for i in range(1, 301))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        forty = await client.get(
            "/api/public/trainers", params={"arena_ids": ids_40, "limit": 1}
        )
        many = await client.get(
            "/api/public/trainers", params={"arena_ids": ids_300, "limit": 1}
        )
        groups = await client.get(
            "/api/public/training-groups", params={"arena_ids": ids_40, "limit": 1}
        )
    assert forty.status_code == 200, forty.text
    body = forty.json()
    assert "arena_ids_truncated" in body
    assert body["arena_ids_truncated"] is False
    assert int(body.get("arena_ids_received") or 0) == 40

    assert many.status_code == 200, many.text
    many_body = many.json()
    if many_body["arena_ids_truncated"]:
        assert int(many_body["arena_ids_received"]) > 32
    else:
        assert int(many_body["arena_ids_received"]) >= 40

    assert groups.status_code == 200, groups.text
    assert "arena_ids_truncated" in groups.json()


@pytest.mark.asyncio
async def test_arena_card_exposes_honest_freshness_and_source(
    app_use_test_db, db_session
) -> None:
    """AC-006: freshness/source present; missing source is null, not a fabricated date."""
    cid = await _insert_city(db_session, name=f"IceCard-{uuid.uuid4().hex[:6]}")
    with_source = await _insert_arena(
        db_session,
        cid,
        name="Каток с сайтом",
        website_url="https://zamok.example/ice",
        phone="+375 17 333",
    )
    bare = await _insert_arena(db_session, cid, name="Каток без источника")
    observed = datetime.now(timezone.utc) - timedelta(days=2)
    await _add_future_session(
        db_session,
        with_source,
        observed_at=observed,
        valid_until=datetime.now(timezone.utc) + timedelta(days=5),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        card = await client.get(f"/api/public/arenas/{with_source}")
        slug_card = await client.get("/api/public/arenas/katok-s-saytom")
        bare_card = await client.get(f"/api/public/arenas/{bare}")
    assert card.status_code == 200, card.text
    body = card.json()
    assert body["id"] == with_source
    assert body["tier"] in {"A", "B", "C"}
    assert "hero" in body and "gallery" in body
    freshness = body["freshness"]
    assert freshness["schedule_observed_at"] is not None
    assert freshness["source_url"] == "https://zamok.example/ice"
    assert freshness["source_label"]
    assert slug_card.status_code == 200, slug_card.text
    assert slug_card.json()["id"] == with_source

    assert bare_card.status_code == 200, bare_card.text
    bare_fresh = bare_card.json()["freshness"]
    assert bare_fresh["schedule_observed_at"] is None
    assert bare_fresh["source_label"] is None
    assert bare_fresh["source_url"] is None


@pytest.mark.asyncio
async def test_ice_list_of_sixty_arenas_is_not_n_plus_one(
    app_use_test_db, db_session
) -> None:
    """AC-007: 60 arenas in one city list must not query trainers/sessions per arena."""
    cid = await _insert_city(db_session, name=f"IceSixty-{uuid.uuid4().hex[:6]}")
    first_id = None
    for i in range(60):
        aid = await _insert_arena(
            db_session,
            cid,
            name=f"Каток {i:02d}",
            latitude=53.90 + i * 0.001,
            longitude=27.56,
            phone="+375 17 000" if i % 3 == 0 else None,
        )
        if first_id is None:
            first_id = aid
        if i < 5:
            await _add_future_session(db_session, aid, days_ahead=1 + i, starts_at_local="14:00")
    await backfill_arena_profiles(db_session)
    await db_session.flush()

    bind = db_session.sync_session.get_bind()
    counts = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany):
        sql = (statement or "").lstrip().upper()
        if sql.startswith(("SELECT", "INSERT", "UPDATE", "DELETE")):
            counts["n"] += 1

    event.listen(bind, "before_cursor_execute", _before)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/public/ice/arenas",
                params={"city_id": cid, "intent": "coach", "limit": 100},
            )
    finally:
        event.remove(bind, "before_cursor_execute", _before)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 60
    assert counts["n"] <= 12
    currencies = {it.get("currency_code") for it in items}
    assert None not in currencies


@pytest.mark.asyncio
async def test_bbox_mixed_cities_keep_per_arena_currency(
    app_use_test_db, db_session
) -> None:
    """EDGE-001: bbox spanning cities must not collapse to one list-level currency."""
    by_city = await _insert_city(db_session, name=f"IceBY-{uuid.uuid4().hex[:6]}", country="BY")
    ru_city = await _insert_city(db_session, name=f"IceRU-{uuid.uuid4().hex[:6]}", country="RU")
    by_arena = await _insert_arena(
        db_session, by_city, name="Минский каток", latitude=53.90, longitude=27.56
    )
    ru_arena = await _insert_arena(
        db_session, ru_city, name="Смоленский каток", latitude=54.78, longitude=32.05
    )
    await _add_future_session(db_session, by_arena, price_adult_minor=850)
    await _add_future_session(db_session, ru_arena, price_adult_minor=40000)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/public/ice/arenas",
            params={"bbox": "53.0,27.0,55.0,33.0", "intent": "skate", "limit": 20},
        )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert "currency_code" not in payload or payload.get("currency_code") is None
    by_row = next(it for it in payload["items"] if it["id"] == by_arena)
    ru_row = next(it for it in payload["items"] if it["id"] == ru_arena)
    assert by_row["currency_code"] == "BYN"
    assert ru_row["currency_code"] == "RUB"
    assert by_row["live"]["currency_code"] == "BYN"
    assert ru_row["live"]["currency_code"] == "RUB"


@pytest.mark.asyncio
async def test_tier_outranks_distance_and_nearby_c_stays_visible(
    app_use_test_db, db_session
) -> None:
    """EDGE-003: A at 8 km ranks above C at 100 m; C remains in the coach list."""
    cid = await _insert_city(db_session, name=f"IceRank-{uuid.uuid4().hex[:6]}")
    near_c = await _insert_arena(
        db_session,
        cid,
        name="Ближний C",
        latitude=53.9001,
        longitude=27.5601,
        phone=None,
        website_url=None,
    )
    far_a = await _insert_arena(
        db_session,
        cid,
        name="Дальний A",
        latitude=53.97,
        longitude=27.56,
        phone="+375 17 9",
    )
    await _add_future_session(db_session, far_a)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": cid, "near": "53.90,27.56", "intent": "coach", "limit": 20},
        )
    assert resp.status_code == 200, resp.text
    ids = [it["id"] for it in resp.json()["items"]]
    assert ids.index(far_a) < ids.index(near_c)
    assert near_c in ids
    assert {it["id"]: it["tier"] for it in resp.json()["items"]}[far_a] == "A"
    assert {it["id"]: it["tier"] for it in resp.json()["items"]}[near_c] == "C"


@pytest.mark.asyncio
async def test_trainers_on_arena_reuse_can_book(app_use_test_db, db_session) -> None:
    sid = await require_seed_service_id(db_session)
    cid = await _insert_city(db_session, name=f"IceTr-{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, cid, name="Ледовый Замок")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(
            client,
            db_session,
            city_id=cid,
            service_ids=[sid],
            arena_ids=[arena_id],
            first_name="Иван",
            last_name="Замок",
        )
        await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
        resp = await client.get(f"/api/public/arenas/{arena_id}/trainers")
        search = await client.get("/api/public/search", params={"q": "Замок"})
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert any(it["id"] == tid for it in items)
    ours = next(it for it in items if it["id"] == tid)
    assert "can_book" in ours
    assert isinstance(ours["can_book"], bool)
    assert search.status_code == 200, search.text
    found = search.json()
    assert [g["type"] for g in found["groups"]] == ["arena", "trainer", "city"]
    trainer_hits = [h for h in found["groups"] if h["type"] == "trainer"][0]["items"]
    arena_hits = [h for h in found["groups"] if h["type"] == "arena"][0]["items"]
    assert any(h["id"] == tid for h in trainer_hits)
    assert any(h["id"] == arena_id for h in arena_hits)
