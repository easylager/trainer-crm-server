"""Admin «Путь тренеров»: path semantics and the DB query."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from src.application.admin_trainer_journey import (
    STEP_COUNT,
    build_journey_row,
    get_admin_trainer_journey,
    set_trainer_contacted,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _row(**kw):
    base = dict(
        id=1, telegram_id=10, telegram_username="nick", joined_at=NOW - timedelta(days=3),
        display_name="Анна", has_profile=True, has_services=True, has_schedule=True,
        slots_count=5, link_copied_at=None, clients_count=0, first_client_at=None,
        bookings_count=0, first_booking_at=None, schedule_at=None, last_activity_at=NOW,
        sub_raw=None, contacted_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_stops_at_first_gap_even_if_later_steps_done():
    # booking exists but profile missing: path stops at step 1, not 7.
    r = build_journey_row(_row(has_profile=False, bookings_count=2, clients_count=1), NOW)
    assert r["reached"] == 1
    assert r["stall"] == "Не начал профиль"
    assert r["working"] is False


def test_link_copied_but_no_client():
    r = build_journey_row(_row(link_copied_at=NOW), NOW)
    assert r["reached"] == 5
    assert r["stall"] == "Ссылка есть, клиентов нет"
    assert [s["done"] for s in r["steps"]] == [True] * 5 + [False] * 2


def test_working_trainer_and_plan():
    r = build_journey_row(
        _row(link_copied_at=NOW, clients_count=3, bookings_count=4,
             sub_raw="trial|" + (NOW + timedelta(days=5)).isoformat()), NOW)
    assert r["reached"] == STEP_COUNT and r["working"] is True
    assert r["plan"]["status"] == "trial"


def test_expired_plan():
    r = build_journey_row(_row(sub_raw="active|" + (NOW - timedelta(days=1)).isoformat()), NOW)
    assert r["plan"]["status"] == "expired"


@pytest.mark.asyncio
async def test_query_orders_newest_first_and_skips_excluded(db_session):
    for tid, tg, ago in ((9101, 9001, 5), (9102, 9002, 1), (9103, 9003, 3)):
        await db_session.execute(
            text(
                "INSERT INTO trainers (id, telegram_id, status, created_at) "
                "VALUES (:i, :tg, 'pending_profile', now() - make_interval(days => :d))"
            ),
            {"i": tid, "tg": tg, "d": ago},
        )
    await db_session.commit()
    data = await get_admin_trainer_journey(db_session, exclude_telegram_ids=[9003])
    ids = [i["trainer_id"] for i in data["items"] if i["trainer_id"] in (9101, 9102, 9103)]
    assert ids == [9102, 9101]
    first = next(i for i in data["items"] if i["trainer_id"] == 9102)
    assert first["reached"] == 1 and first["contacted_at"] is None

    assert await set_trainer_contacted(db_session, trainer_id=9102, contacted=True, admin_telegram_id=1)
    data = await get_admin_trainer_journey(db_session)
    assert next(i for i in data["items"] if i["trainer_id"] == 9102)["contacted_at"] is not None
    assert await set_trainer_contacted(db_session, trainer_id=9102, contacted=False, admin_telegram_id=1)
    assert not await set_trainer_contacted(db_session, trainer_id=999999, contacted=True, admin_telegram_id=1)


@pytest.mark.asyncio
async def test_admin_endpoints_roundtrip(db_session):
    from httpx import ASGITransport, AsyncClient

    from src.api.app import app
    from src.api.miniapp_auth.deps import get_admin_miniapp_principal
    from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal

    await db_session.execute(
        text("INSERT INTO trainers (id, telegram_id, telegram_username, status) VALUES (9201, 9301, 'zz_nick', 'pending_profile')")
    )
    await db_session.commit()
    app.dependency_overrides[get_admin_miniapp_principal] = lambda: MiniAppPrincipal(
        platform=MiniAppPlatform.TELEGRAM, user_id=4242
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/webapp/admin/trainer-journey")
            assert r.status_code == 200
            item = next(i for i in r.json()["items"] if i["trainer_id"] == 9201)
            assert item["username"] == "zz_nick" and item["reached"] == 1
            r = await c.post("/api/webapp/admin/trainer-journey/9201/contacted", json={"contacted": True})
            assert r.status_code == 200
            r = await c.post("/api/webapp/admin/trainer-journey/999999/contacted", json={"contacted": True})
            assert r.status_code == 404
            page = await c.get("/webapp/admin-journey")
            assert page.status_code == 200
    finally:
        app.dependency_overrides.pop(get_admin_miniapp_principal, None)


def test_catalog_listed_has_no_gaps():
    r = build_journey_row(_row(catalog_state="published"), NOW, ["photo"])
    assert r["catalog"] == {"state": "published", "listed": True, "label": "В каталоге", "missing": []}


def test_catalog_draft_lists_short_gaps_and_skips_unknown_keys():
    r = build_journey_row(_row(catalog_state="draft"), NOW, ["photo", "phone", "arenas", "weird_key"])
    assert r["catalog"]["listed"] is False
    assert r["catalog"]["missing"] == ["фото", "телефон", "арена"]
    assert r["catalog"]["label"] == "Не в каталоге"


def test_catalog_draft_complete_card_says_ready():
    r = build_journey_row(_row(catalog_state="draft"), NOW, [])
    assert r["catalog"]["label"] == "Не в каталоге, карточка готова"


def test_catalog_draft_that_asked_to_be_listed():
    r = build_journey_row(_row(catalog_state="draft", catalog_state_reason="trainer_requested"), NOW, ["photo"])
    assert r["catalog"]["label"] == "Хочет в каталог, не готов"


def test_catalog_pending_review_label():
    r = build_journey_row(_row(catalog_state="pending_review"), NOW, [])
    assert r["catalog"]["label"] == "На модерации"
