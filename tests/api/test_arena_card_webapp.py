"""TASK-052: arena card Mini App — page serve, model AC, booking preselects this arena."""
from __future__ import annotations

import subprocess
import uuid
from datetime import date, time, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.arena_profile import ensure_arena_profile
from src.infrastructure.db.models import SUBSCRIPTION_TIER_ONLINE
from tests.api.test_public_catalog_integration import _create_active_trainer_via_api
from tests.api.test_webapp_client_miniapp_integration import (
    _ensure_trainer_subscription_tier,
    patch_client_init_auth,
)
from tests.conftest import belarus_test_phone
from tests.db_catalog_helpers import require_seed_service_id

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_arena_card_model_node_unit() -> None:
    """AC-002/006 + edges: empty week day, live session, no photo, three prices."""
    proc = subprocess.run(
        ["node", "--test", "tests/js/arena-card-model.test.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.asyncio
async def test_arena_card_page_and_assets_served(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        html = await client.get("/webapp/arena")
        js = await client.get("/webapp/arena-card.js")
        css = await client.get("/webapp/arena-card.css")
        model = await client.get("/webapp/arena-card-model.js")
        alias = await client.get("/webapp/arena.html")
    assert html.status_code == 200, html.text
    body = html.text
    assert "arena-card.js" in body
    page_js = js.text + model.text + body
    assert "Лента льда" in page_js
    assert "Билет на месте" in page_js
    assert "Сегодня" in page_js
    assert "Завтра" in page_js
    assert "Неделя" in page_js
    assert "Расписание уточняется" in page_js
    assert "Это ваш каток?" in page_js
    assert "Сообщить об ошибке" in page_js
    assert js.status_code == 200
    assert css.status_code == 200
    assert "arena-row--lesson" in css.text
    assert "#c2761a" not in css.text.lower()
    assert "--app-cta-fill" in css.text
    assert model.status_code == 200
    assert alias.status_code == 200
    shell = (REPO_ROOT / "static/webapp/mini-app-client-shell.js").read_text(encoding="utf-8")
    assert "maybeOpenArenaDeepLink" in shell
    assert "arena?ref=" in shell
    assert "iceRowCta" in model.text
    assert "bookable: false" in model.text or "bookable:false" in model.text
    assert 'data-action="book"' not in js.text


@pytest.mark.asyncio
async def test_arena_card_booking_preselects_this_arena(app_use_test_db, db_session) -> None:
    """AC-003: card Записаться href carries this arena_id; booking lands on it, not primary."""
    r = await db_session.execute(
        text(
            """
            SELECT id FROM cities WHERE COALESCE(is_active, true)
            ORDER BY id LIMIT 1
            """
        )
    )
    city_id = r.scalar()
    if city_id is None:
        pytest.skip("need seed city")
    ins_a = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
            VALUES (:cid, :n, 'ул. Карточки, 1', true, true)
            RETURNING id
            """
        ),
        {"cid": int(city_id), "n": f"Карточка-{uuid.uuid4().hex[:6]}"},
    )
    this_arena = int(ins_a.scalar_one())
    ins_b = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
            VALUES (:cid, :n, 'ул. Другая, 2', true, true)
            RETURNING id
            """
        ),
        {"cid": int(city_id), "n": f"Чужая-{uuid.uuid4().hex[:6]}"},
    )
    other_arena = int(ins_b.scalar_one())
    await ensure_arena_profile(db_session, this_arena, city_id=int(city_id), name="This")
    await ensure_arena_profile(db_session, other_arena, city_id=int(city_id), name="Other")
    await db_session.flush()
    sid = await require_seed_service_id(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        trainer_id = await _create_active_trainer_via_api(
            client,
            db_session,
            city_id=int(city_id),
            service_ids=[sid],
            arena_ids=[this_arena, other_arena],
            first_name="Мария",
            last_name="Карточка",
        )
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :p WHERE id = :tid"),
        {"p": other_arena, "tid": trainer_id},
    )
    await _ensure_trainer_subscription_tier(db_session, trainer_id, SUBSCRIPTION_TIER_ONLINE)
    slot_day = date.today() + timedelta(days=3)
    slot_ins = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, arena_id)
            VALUES (:tid, :d, :st, :et, 'available', :aid)
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "d": slot_day,
            "st": time(18, 0),
            "et": time(19, 0),
            "aid": this_arena,
        },
    )
    slot_id = int(slot_ins.scalar_one())
    await db_session.commit()

    href_proc = subprocess.run(
        [
            "node",
            "-e",
            "const m=require('./static/webapp/arena-card-model.js');"
            f"process.stdout.write(m.buildBookingHref({{trainerId:{trainer_id},arenaId:{this_arena},action:'book'}}));",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert href_proc.returncode == 0, href_proc.stderr
    href = href_proc.stdout
    assert f"trainer_id={trainer_id}" in href
    assert f"arena_id={this_arena}" in href
    assert "from=arena" in href

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        trainers = await client.get(f"/api/public/arenas/{this_arena}/trainers")
        card = await client.get(f"/api/public/arenas/{this_arena}")
    assert trainers.status_code == 200, trainers.text
    items = trainers.json()["items"]
    ours = next(it for it in items if it["id"] == trainer_id)
    assert ours["can_book"] is True
    assert card.status_code == 200
    assert card.json()["id"] == this_arena

    ctg = 7_200_000_000 + (uuid.uuid4().int % 1_000_000)
    phone, _ = belarus_test_phone(ctg)
    await db_session.execute(
        text(
            """
            INSERT INTO client_sessions (
                telegram_id, state, city_id, selected_service_id, selected_arena_id, selected_trainer_id
            )
            VALUES (:tg, 'idle', :cid, :sid, :aid, :tid)
            """
        ),
        {
            "tg": ctg,
            "cid": int(city_id),
            "sid": sid,
            "aid": this_arena,
            "tid": trainer_id,
        },
    )
    await db_session.commit()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("src.api.routes.webapp.get_slots_cached", return_value=None):
                book = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "service_id": sid,
                        "first_name": "Клиент",
                    },
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert book.status_code == 200, book.text
    data = book.json()
    assert data.get("success") is True
    bid = int(data["booking_id"])
    row = await db_session.execute(
        text("SELECT arena_id FROM bookings WHERE id = :bid"), {"bid": bid}
    )
    booked_arena = int(row.scalar_one())
    assert booked_arena == this_arena
    assert booked_arena != other_arena


@pytest.mark.asyncio
async def test_arena_card_level_b_payload_has_contacts_not_sessions(
    app_use_test_db, db_session
) -> None:
    """AC-005: level B card still has phone/site for the pending-schedule block."""
    r = await db_session.execute(
        text("SELECT id FROM cities WHERE COALESCE(is_active, true) ORDER BY id LIMIT 1")
    )
    city_id = r.scalar()
    if city_id is None:
        pytest.skip("need seed city")
    ins = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
            VALUES (:cid, :n, 'ул. Без слотов, 1', true, true)
            RETURNING id
            """
        ),
        {"cid": int(city_id), "n": f"B-level-{uuid.uuid4().hex[:6]}"},
    )
    arena_id = int(ins.scalar_one())
    await ensure_arena_profile(db_session, arena_id, city_id=int(city_id), name="B")
    await db_session.execute(
        text(
            """
            UPDATE arena_profiles
            SET phone = :phone, website_url = :web, district = 'Фрунзенский'
            WHERE arena_id = :id
            """
        ),
        {
            "id": arena_id,
            "phone": "+375 17 000-00-00",
            "web": "https://zamok.example",
        },
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        card = await client.get(f"/api/public/arenas/{arena_id}")
        feed = await client.get(f"/api/public/arenas/{arena_id}/sessions")
    assert card.status_code == 200
    body = card.json()
    assert body["tier"] in ("B", "C")
    assert body["phone"]
    assert body["website_url"]
    assert feed.status_code == 200
    assert feed.json()["days"] == []
    js = (REPO_ROOT / "static/webapp/arena-card.js").read_text(encoding="utf-8")
    assert "Расписание уточняется" in js
    assert "Позвонить" in js
    assert "Сайт катка" in js
