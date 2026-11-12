"""TASK-397: события карточки без персональных данных и срез по via."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.app import app
from src.application.booking_source import BookingSource, get_empty_via_share
from src.application.public_web_cta import public_page_view_beacon_script
from src.application.trainer_card_measure import (
    WEEKLY_SITE_VIEWS_SQL,
    measure_payload,
    record_booking_confirmed,
    record_site_trainer_card_view,
    record_trainer_card_event,
    via_from_booking_source,
    via_from_start_param,
)
from tests.api.test_webapp_client_miniapp_integration import (
    _client_auth_headers,
    patch_client_init_auth,
)


def test_via_from_start_param_and_booking_source() -> None:
    assert via_from_start_param("trainer_7_v_k12") == "k12"
    assert via_from_start_param("trainer_7_a_3") == "p3"
    assert via_from_start_param("trainer_7") is None
    assert via_from_booking_source(BookingSource("link")) == "link"
    assert via_from_booking_source(BookingSource("site_catalog", city_id=4)) == "k4"
    assert via_from_booking_source(BookingSource("unknown")) is None
    assert via_from_booking_source(BookingSource("site_trainer")) is None


def test_measure_payload_drops_personal_fields() -> None:
    body = measure_payload(surface="miniapp", via="link", action="call", start_param="trainer_7_v_link")
    # start_param с «link» не проходит разбор метки места — via задан отдельно.
    assert body["via"] == "link"
    assert body["action"] == "call"
    assert "phone" not in body
    assert set(body) <= {"surface", "via", "action", "target", "booking_id", "ua_class", "start_param", "source"}
    assert measure_payload(via="app_button") == {}
    assert measure_payload(surface="site", ua_class="not-a-class") == {"surface": "site"}


def test_trainer_page_beacon_is_not_on_other_pages() -> None:
    page = public_page_view_beacon_script(surface="trainer_page")
    assert "/api/webapp/public/trainer-card-view" in page
    assert "trainer_id" in page
    assert "public-page-view-beacon.js" in page
    place = public_page_view_beacon_script(surface="place_page", city_id=1, arena_id=2)
    assert "trainer-card-view" not in place


async def _trainer(session: AsyncSession) -> int:
    row = await session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = row.fetchone()
    await session.commit()
    return int(trainer_id)


@pytest.mark.asyncio
async def test_site_view_keeps_via_and_drops_bots_from_the_weekly_cut(db_session: AsyncSession) -> None:
    trainer_id = await _trainer(db_session)
    human = await record_site_trainer_card_view(
        db_session,
        trainer_id=trainer_id,
        via="k7",
        user_agent="Mozilla/5.0",
        client_ip="203.0.113.5",
    )
    again = await record_site_trainer_card_view(
        db_session,
        trainer_id=trainer_id,
        via="p3",
        user_agent="Mozilla/5.0",
        client_ip="203.0.113.5",
    )
    bot = await record_site_trainer_card_view(
        db_session,
        trainer_id=trainer_id,
        via="link",
        user_agent="Mozilla/5.0 (compatible; Googlebot/2.1)",
        client_ip="203.0.113.9",
    )
    assert human is True
    assert again is False  # тот же человек в те же сутки — одна строка, первая метка
    assert bot is True
    rows = (
        await db_session.execute(
            text(
                "SELECT payload FROM trainer_demand_events "
                "WHERE trainer_id = :tid AND kind = 'trainer_card_view' ORDER BY id"
            ),
            {"tid": trainer_id},
        )
    ).all()
    assert len(rows) == 2
    assert rows[0][0]["via"] == "k7"
    assert rows[0][0]["ua_class"] == "human"
    assert "name" not in rows[0][0]
    now = datetime.now(timezone.utc)
    counted = (
        await db_session.execute(
            text(WEEKLY_SITE_VIEWS_SQL),
            {"since": now - timedelta(days=7), "until": now + timedelta(minutes=1)},
        )
    ).all()
    assert [(r.via, r.views) for r in counted] == [("k7", 1)]


@pytest.mark.asyncio
async def test_event_row_has_no_phone_or_init_data(db_session: AsyncSession) -> None:
    trainer_id = await _trainer(db_session)
    ok = await record_trainer_card_event(
        db_session,
        trainer_id=trainer_id,
        kind="card_cta_tap",
        payload={
            "surface": "miniapp",
            "action": "write",
            "via": "link",
            "phone": "+375291112233",
            "first_name": "Анна",
            "init_data": "query_id=secret",
            "name": "Анна",
        },
    )
    assert ok is True
    payload = (
        await db_session.execute(
            text("SELECT payload FROM trainer_demand_events WHERE trainer_id = :tid AND kind = 'card_cta_tap'"),
            {"tid": trainer_id},
        )
    ).scalar_one()
    assert payload == {"surface": "miniapp", "action": "write", "via": "link"}


@pytest.mark.asyncio
async def test_confirm_latency_uses_booking_id_only(db_session: AsyncSession) -> None:
    trainer_id = await _trainer(db_session)
    service = (await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))).scalar()
    if service is None:
        service = (
            await db_session.execute(text("INSERT INTO services (name) VALUES ('Лёд') RETURNING id"))
        ).scalar_one()
    client_id = (
        await db_session.execute(
            text("INSERT INTO clients (telegram_id) VALUES (:tg) RETURNING id"),
            {"tg": 910_000_000 + trainer_id},
        )
    ).scalar_one()
    created = datetime.now(timezone.utc) - timedelta(hours=5)
    slot_id = (
        await db_session.execute(
            text(
                "INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status) "
                "VALUES (:tid, :d, '10:00', '11:00', 'booked') RETURNING id"
            ),
            {"tid": trainer_id, "d": created.date()},
        )
    ).scalar_one()
    booking_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status, source, created_at)
                VALUES (:slot, :tid, :cid, :sid, 'confirmed', 'link', :created)
                RETURNING id
                """
            ),
            {
                "slot": slot_id,
                "tid": trainer_id,
                "cid": client_id,
                "sid": service,
                "created": created,
            },
        )
    ).scalar_one()
    await db_session.commit()
    assert await record_booking_confirmed(db_session, trainer_id=trainer_id, booking_id=int(booking_id)) is True
    payload = (
        await db_session.execute(
            text(
                "SELECT payload FROM trainer_demand_events "
                "WHERE trainer_id = :tid AND kind = 'booking_confirmed'"
            ),
            {"tid": trainer_id},
        )
    ).scalar_one()
    assert payload == {"booking_id": int(booking_id)}
    share = await get_empty_via_share(db_session, days=1)
    assert share["self_bookings"] >= 1
    assert share["empty_via"] == 0


@pytest.mark.asyncio
async def test_public_beacon_and_client_event_ignore_personal_fields(
    app_use_test_db, db_session: AsyncSession
) -> None:
    trainer_id = await _trainer(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        prefetch = await client.post(
            f"/api/webapp/public/trainer-card-view?trainer_id={trainer_id}&via=link",
            headers={"user-agent": "Mozilla/5.0", "Purpose": "prefetch"},
        )
        assert prefetch.status_code == 204
        viewed = await client.post(
            f"/api/webapp/public/trainer-card-view?trainer_id={trainer_id}&via=share",
            headers={"user-agent": "Mozilla/5.0 (iPhone)"},
        )
        assert viewed.status_code == 204
        with patch_client_init_auth(880_001):
            denied = await client.post(
                "/api/webapp/client/trainer-card-event",
                headers={**_client_auth_headers(), "Content-Type": "application/json"},
                json={
                    "event": "card_cta_tap",
                    "trainer_id": trainer_id,
                    "action": "call",
                    "phone": "+375290000000",
                    "init_data": "must-not-land",
                    "first_name": "Имя",
                },
            )
        assert denied.status_code == 200
        assert denied.json()["recorded"] is True
    rows = (
        await db_session.execute(
            text(
                "SELECT kind, payload::text FROM trainer_demand_events "
                "WHERE trainer_id = :tid ORDER BY id"
            ),
            {"tid": trainer_id},
        )
    ).all()
    blob = " ".join(payload for _, payload in rows)
    assert "phone" not in blob
    assert "init_data" not in blob
    assert "Имя" not in blob
    assert "+375" not in blob
    assert any(kind == "trainer_card_view" for kind, _ in rows)
    assert any(kind == "card_cta_tap" for kind, _ in rows)
