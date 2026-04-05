"""
Интеграционные тесты публичного каталога: GET /api/public/cities|services|arenas|trainers|...

Цель — зафиксировать контракт (поля, фильтры, пагинация) и отсутствие утечек внутренних
данных; при расхождении с ожидаемой безопасностью/UX тест падает и правится продукт.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.trainer_use_cases import add_trainer_rating
from src.application.trainer_schedule_use_cases import replace_slots_for_day
from src.infrastructure.db.models import SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE
from src.shared.public_trainer_payload import PUBLIC_CATALOG_TRAINER_DROP_KEYS
from tests.api.test_webapp_client_miniapp_integration import (
    _ensure_trainer_subscription_tier,
    _require_seed_ids,
)
from tests.conftest import unique_test_telegram_id


def _pg_dow(d: date) -> int:
    """PostgreSQL EXTRACT(DOW FROM date): 0=Sunday .. 6=Saturday."""
    return (d.weekday() + 1) % 7


def _assert_no_public_trainer_leaks(obj: dict) -> None:
    """Топ-уровень ответа каталога не должен содержать внутренних полей тренера."""
    leaked = PUBLIC_CATALOG_TRAINER_DROP_KEYS & set(obj.keys())
    assert not leaked, f"unexpected internal keys in public payload: {leaked}"


def _assert_catalog_item_contract(item: dict) -> None:
    _assert_no_public_trainer_leaks(item)
    assert "id" in item and isinstance(item["id"], int)
    assert "can_book" in item and isinstance(item["can_book"], bool)
    assert "profile" in item
    assert "photos" in item and isinstance(item["photos"], list)
    assert "service_ids" in item and isinstance(item["service_ids"], list)
    assert "services" in item and isinstance(item["services"], list)
    assert "arena_ids" in item and isinstance(item["arena_ids"], list)
    assert "arena_names" in item and isinstance(item["arena_names"], list)
    assert "free_slots_14d" in item and isinstance(item["free_slots_14d"], int)
    assert "has_pass_products" in item and isinstance(item["has_pass_products"], bool)
    assert "has_certificate_products" in item and isinstance(
        item["has_certificate_products"], bool
    )
    assert "education_entries" in item and isinstance(item["education_entries"], list)
    for e in item["education_entries"]:
        _assert_public_education_entry(e)


def _assert_public_education_entry(entry: dict) -> None:
    """Публичная карточка / education: только безопасные поля, без модерации."""
    allowed = {
        "id",
        "education_type",
        "institution_name",
        "program_or_title",
        "degree_level",
        "country",
        "city",
        "start_year",
        "end_year",
        "is_in_progress",
        "document_url",
        "approved_at",
        "updated_at",
    }
    assert set(entry.keys()) <= allowed, f"unexpected keys in public education: {set(entry) - allowed}"


async def _create_active_trainer_via_api(
    client: AsyncClient,
    *,
    city_id: int,
    service_ids: list[int],
    arena_ids: list[int] | None = None,
    first_name: str = "Публичный",
    last_name: str = "Каталог",
) -> int:
    body: dict = {
        "profile": {"first_name": first_name, "last_name": last_name, "age": 28, "city_id": city_id},
        "service_ids": service_ids,
    }
    if arena_ids:
        body["arena_ids"] = arena_ids
    r = await client.post("/api/trainers", json=body)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    st = await client.patch(f"/api/trainers/{tid}/status", json={"status": "active"})
    assert st.status_code == 200, st.text
    return tid


@pytest.mark.asyncio
async def test_public_catalog_list_shape_photo_source_and_no_leaks(
    app_use_test_db, db_session
) -> None:
    sid, cid, aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(
            client, city_id=cid, service_ids=[sid], arena_ids=[aid] if aid else None
        )
        await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
        resp = await client.get(
            "/api/public/trainers",
            params={"city_id": cid, "limit": 200},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) >= {"items", "total", "_photo_source"}
    assert data["_photo_source"] in ("cdn", "direct", "proxy")
    assert isinstance(data["total"], int)
    ids = {it["id"] for it in data["items"]}
    assert tid in ids
    ours = next(it for it in data["items"] if it["id"] == tid)
    _assert_catalog_item_contract(ours)


@pytest.mark.asyncio
async def test_public_trainer_detail_shape_booking_flags_education_and_no_leaks(
    app_use_test_db, db_session
) -> None:
    sid, cid, aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(client, city_id=cid, service_ids=[sid])
        await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
        d1 = await client.get(f"/api/public/trainers/{tid}")
    assert d1.status_code == 200
    body = d1.json()
    _assert_no_public_trainer_leaks(body)
    assert body["id"] == tid
    assert body["can_book"] is True
    assert body.get("booking_reason") is None
    assert body["_photo_source"] in ("cdn", "direct", "proxy")
    assert isinstance(body.get("education_entries"), list)
    for e in body["education_entries"]:
        _assert_public_education_entry(e)

    await db_session.execute(
        text("UPDATE trainer_subscriptions SET tier = :tier WHERE trainer_id = :tid"),
        {"tid": tid, "tier": SUBSCRIPTION_TIER_CRM},
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        d2 = await client.get(f"/api/public/trainers/{tid}")
    assert d2.status_code == 200
    b2 = d2.json()
    assert b2["can_book"] is False
    assert b2.get("booking_reason") in ("crm_only", "no_subscription", "tier_insufficient")


@pytest.mark.asyncio
async def test_public_trainer_detail_404_when_inactive(app_use_test_db, db_session) -> None:
    sid, cid, _ = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(client, city_id=cid, service_ids=[sid])
        await client.patch(f"/api/trainers/{tid}/status", json={"status": "pending_profile"})
        r = await client.get(f"/api/public/trainers/{tid}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_public_reviews_list_has_no_client_identifiers(app_use_test_db, db_session) -> None:
    sid, cid, _ = await _require_seed_ids(db_session)
    ctid = unique_test_telegram_id()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(client, city_id=cid, service_ids=[sid])
        await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
    await add_trainer_rating(db_session, tid, ctid, 5, review_text="Норм")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rev = await client.get(f"/api/public/trainers/{tid}/reviews")
    assert rev.status_code == 200
    payload = rev.json()
    assert "items" in payload and "total" in payload
    raw = rev.text.lower()
    assert "client_telegram" not in raw
    assert str(ctid) not in raw
    for it in payload["items"]:
        assert set(it.keys()) <= {"rating", "review_text", "created_at"}


@pytest.mark.asyncio
async def test_public_education_route_matches_detail_safe_fields(
    app_use_test_db, db_session
) -> None:
    """GET /trainers/{id}/education и блок education_entries в карточке — один контракт."""
    sid, cid, _ = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(client, city_id=cid, service_ids=[sid])
        await client.patch(f"/api/trainers/{tid}/status", json={"status": "active"})
        post = await client.post(
            f"/api/trainers/{tid}/education",
            json={
                "education_type": "formal_education",
                "institution_name": "Интеграционный вуз",
                "program_or_title": "Спорт",
            },
        )
        assert post.status_code == 201
        edu_id = post.json()["id"]
    await db_session.execute(
        text(
            """
            UPDATE trainer_education
            SET moderation_status = 'approved', approved_snapshot = true
            WHERE id = :eid
            """
        ),
        {"eid": edu_id},
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        card = await client.get(f"/api/public/trainers/{tid}")
        edu_only = await client.get(f"/api/public/trainers/{tid}/education")
    assert card.status_code == 200
    assert edu_only.status_code == 200
    c_edu = card.json()["education_entries"]
    e_items = edu_only.json()["items"]
    assert len(c_edu) == len(e_items) >= 1
    for e in c_edu:
        _assert_public_education_entry(e)
    for e in e_items:
        _assert_public_education_entry(e)


@pytest.mark.asyncio
async def test_public_education_includes_pending_moderation_for_active_trainer(
    app_use_test_db, db_session
) -> None:
    """Подробные записи об образовании видны в каталоге до отдельного апрува модератором (pending)."""
    sid, cid, _ = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(client, city_id=cid, service_ids=[sid])
        await client.patch(f"/api/trainers/{tid}/status", json={"status": "active"})
        post = await client.post(
            f"/api/trainers/{tid}/education",
            json={
                "education_type": "formal_education",
                "institution_name": "Пока на модерации",
                "program_or_title": "Тренерский курс",
            },
        )
        assert post.status_code == 201
        card = await client.get(f"/api/public/trainers/{tid}")
    assert card.status_code == 200
    entries = card.json().get("education_entries") or []
    assert len(entries) >= 1
    assert any(
        (e.get("institution_name") or "").strip() == "Пока на модерации" for e in entries
    )
    for e in entries:
        _assert_public_education_entry(e)


@pytest.mark.asyncio
async def test_public_filter_city_service_arena_narrow_results(
    app_use_test_db, db_session
) -> None:
    sid, cid, aid = await _require_seed_ids(db_session)
    r_other = await db_session.execute(
        text(
            """
            SELECT c.id FROM cities c
            WHERE c.id != :cid
            ORDER BY c.id LIMIT 1
            """
        ),
        {"cid": cid},
    )
    other_city = r_other.scalar()
    if other_city is None:
        pytest.skip("need at least two cities in DB")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        t_match = await _create_active_trainer_via_api(
            client,
            city_id=cid,
            service_ids=[sid],
            arena_ids=[aid] if aid else None,
            first_name="Город",
            last_name="Матч",
        )
        t_other = await _create_active_trainer_via_api(
            client,
            city_id=int(other_city),
            service_ids=[sid],
            first_name="Другой",
            last_name="Город",
        )
        for x in (t_match, t_other):
            await _ensure_trainer_subscription_tier(db_session, x, SUBSCRIPTION_TIER_ONLINE)

        by_city = await client.get("/api/public/trainers", params={"city_id": cid, "limit": 100})
        assert by_city.status_code == 200
        city_ids = {it["id"] for it in by_city.json()["items"]}
        assert t_match in city_ids
        assert t_other not in city_ids

        by_srv = await client.get("/api/public/trainers", params={"service_id": sid, "limit": 100})
        assert by_srv.status_code == 200
        assert t_match in {it["id"] for it in by_srv.json()["items"]}

        if aid is not None:
            by_ar = await client.get("/api/public/trainers", params={"arena_id": aid, "limit": 100})
            assert by_ar.status_code == 200
            assert t_match in {it["id"] for it in by_ar.json()["items"]}
            assert t_other not in {it["id"] for it in by_ar.json()["items"]}


@pytest.mark.asyncio
async def test_public_time_filters_require_matching_slot(
    app_use_test_db, db_session
) -> None:
    """filter_days + filter_time_slots сужают выдачу по реальным available-слотам (14 дней)."""
    sid, cid, aid = await _require_seed_ids(db_session)
    slot_date = date.today() + timedelta(days=3)
    if slot_date > date.today() + timedelta(days=13):
        slot_date = date.today() + timedelta(days=1)
    dow = _pg_dow(slot_date)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        t_with = await _create_active_trainer_via_api(
            client, city_id=cid, service_ids=[sid], arena_ids=[aid] if aid else None
        )
        t_without = await _create_active_trainer_via_api(
            client,
            city_id=cid,
            service_ids=[sid],
            first_name="Без",
            last_name="Слота",
        )
        for x in (t_with, t_without):
            await _ensure_trainer_subscription_tier(db_session, x, SUBSCRIPTION_TIER_ONLINE)

    await replace_slots_for_day(db_session, t_with, slot_date, {10}, 60)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/public/trainers",
            params={
                "city_id": cid,
                "filter_days": str(dow),
                "filter_time_slots": "09:00-12:00",
                "limit": 100,
            },
        )
    assert resp.status_code == 200
    ids = {it["id"] for it in resp.json()["items"]}
    assert t_with in ids
    assert t_without not in ids


@pytest.mark.asyncio
async def test_public_list_requires_active_subscription_detail_is_active_only(
    app_use_test_db, db_session
) -> None:
    """
    Список каталога требует неистёкшую подписку; карточка по id доступна при status=active
    (как в docstring public.py — видимость вне зависимости от tier/подписки).
    """
    sid, cid, _ = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(client, city_id=cid, service_ids=[sid])
        await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)

    await db_session.execute(
        text("UPDATE trainer_subscriptions SET expires_at = NOW() - INTERVAL '2 days' WHERE trainer_id = :tid"),
        {"tid": tid},
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        lst = await client.get("/api/public/trainers", params={"limit": 200})
        one = await client.get(f"/api/public/trainers/{tid}")
    assert lst.status_code == 200
    assert tid not in {it["id"] for it in lst.json()["items"]}
    assert one.status_code == 200
    assert one.json()["id"] == tid


@pytest.mark.asyncio
async def test_public_pagination_total_stable(app_use_test_db, db_session) -> None:
    sid, cid, _ = await _require_seed_ids(db_session)
    created: list[int] = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for i in range(2):
            tid = await _create_active_trainer_via_api(
                client,
                city_id=cid,
                service_ids=[sid],
                first_name="Стр",
                last_name=f"аница{i}",
            )
            await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
            created.append(tid)
        p1 = await client.get("/api/public/trainers", params={"city_id": cid, "limit": 1, "offset": 0})
        p2 = await client.get("/api/public/trainers", params={"city_id": cid, "limit": 1, "offset": 1})
    assert p1.status_code == p2.status_code == 200
    t1, t2 = p1.json(), p2.json()
    assert t1["total"] == t2["total"]
    assert len(t1["items"]) <= 1
    if t1["total"] >= 2:
        assert t1["items"][0]["id"] != t2["items"][0]["id"]


@pytest.mark.asyncio
async def test_public_cities_services_arenas_trainers_smoke(app_use_test_db, db_session) -> None:
    sid, cid, aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        c = await client.get("/api/public/cities")
        s = await client.get("/api/public/services")
        a = await client.get("/api/public/arenas", params={"city_id": cid})
    assert c.status_code == s.status_code == 200
    assert "items" in c.json() and isinstance(c.json()["items"], list)
    assert "items" in s.json()
    if aid is not None:
        assert a.status_code == 200
        assert "items" in a.json()


@pytest.mark.asyncio
async def test_public_invalid_filter_params_do_not_500(app_use_test_db, db_session) -> None:
    """Битые filter_* не должны ронять каталог."""
    await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/public/trainers",
            params={"filter_time_slots": "not-a-range", "filter_days": "abc", "limit": 5},
        )
    assert r.status_code == 200
    assert "items" in r.json()
