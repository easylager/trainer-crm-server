"""
Интеграционные тесты клиентского Mini App: GET/POST /api/webapp/client/*.

Цель — зафиксировать контракт и граничные случаи (initData, слоты, бронь, сессия, заявки),
а не «подгонять» ожидания под текущую реализацию: при расхождении с доменной логикой тест падает.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.subscription_use_cases import create_trial_subscription
from src.application.trainer_schedule_use_cases import replace_slots_for_day
from src.infrastructure.db.models import (
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_TRIAL,
    SUBSCRIPTION_TIER_ANALYTICS,
    SUBSCRIPTION_TIER_CRM,
    SUBSCRIPTION_TIER_ONLINE,
)
from src.api.miniapp_auth.deps import MINIAPP_AUTH_ERROR_HEADER, MINIAPP_CREDENTIAL_USER_DETAIL_RU
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.shared.telegram_webapp import InitDataAuthError
from tests.conftest import belarus_test_phone


def _fresh_client_telegram_id() -> int:
    return 7_000_000_000 + (uuid.uuid4().int % 2_000_000_000)


_CLIENT_MINIAPP_VERIFY_PATCH = "src.api.miniapp_auth.deps.verify_telegram_init_data_principal"


@contextmanager
def patch_client_init_auth(telegram_id: int) -> Iterator[None]:
    """Клиентский webapp валидирует initData токеном client-бота."""
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch(_CLIENT_MINIAPP_VERIFY_PATCH, return_value=fake):
        yield


async def _require_seed_ids(db_session) -> tuple[int, int, int | None]:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    r2 = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r2.scalar()
    if sid is None or cid is None:
        pytest.skip("need seed services and cities")
    r3 = await db_session.execute(
        text("SELECT id FROM arenas WHERE city_id = :cid ORDER BY id LIMIT 1"),
        {"cid": cid},
    )
    aid = r3.scalar()
    return int(sid), int(cid), int(aid) if aid is not None else None


def _modules_json_for_subscription_tier(tier: str) -> str:
    """Canonical CRM row + module flags (matches migration mapping)."""
    m = {"online": False, "analytics": False, "groups": False}
    if tier == SUBSCRIPTION_TIER_ONLINE:
        m["online"] = True
    elif tier == SUBSCRIPTION_TIER_ANALYTICS:
        m["online"] = True
        m["analytics"] = True
    return json.dumps(m, ensure_ascii=False)


async def _ensure_trainer_subscription_tier(db_session, trainer_id: int, tier: str) -> None:
    """
    Активная подписка с нужным tier. Сначала trial (как в проде), иначе — любой plan из БД
    (в тестовой базе может не быть is_trial-плана).

    Всегда выставляет tier на **все** строки подписок тренера — иначе после PATCH active
    остаётся trial с analytics, а INSERT добавлял бы вторую строку crm и эффективный tier
    оставался бы analytics.
    """
    sub = await create_trial_subscription(db_session, trainer_id)
    if sub is None:
        r = await db_session.execute(
            text(
                """
                SELECT 1 FROM trainer_subscriptions
                WHERE trainer_id = :tid AND expires_at > NOW()
                  AND status IN (:s1, :s2)
                LIMIT 1
                """
            ),
                {"tid": trainer_id, "s1": SUBSCRIPTION_STATUS_ACTIVE, "s2": SUBSCRIPTION_STATUS_TRIAL},
        )
        if r.fetchone() is None:
            r = await db_session.execute(text("SELECT id FROM subscription_plans ORDER BY id LIMIT 1"))
            plan_id = r.scalar()
            if plan_id is None:
                pytest.skip("need subscription_plans seed")
            await db_session.execute(
                text(
                    """
                    INSERT INTO trainer_subscriptions
                        (trainer_id, plan_id, started_at, expires_at, status, tier, modules)
                    VALUES (
                        :tid,
                        :pid,
                        NOW(),
                        NOW() + INTERVAL '400 days',
                        :st,
                        :crm,
                        CAST(:mods AS jsonb)
                    )
                    """
                ),
                {
                    "tid": trainer_id,
                    "pid": plan_id,
                    "st": SUBSCRIPTION_STATUS_ACTIVE,
                    "crm": SUBSCRIPTION_TIER_CRM,
                    "mods": _modules_json_for_subscription_tier(tier),
                },
            )
    await db_session.execute(
        text(
            """
            UPDATE trainer_subscriptions
            SET tier = :crm, modules = CAST(:mods AS jsonb)
            WHERE trainer_id = :tid
            """
        ),
        {
            "tid": trainer_id,
            "crm": SUBSCRIPTION_TIER_CRM,
            "mods": _modules_json_for_subscription_tier(tier),
        },
    )
    await db_session.commit()


async def _create_trainer_online_with_slot(
    db_session,
    *,
    slot_date: date,
    start_hours: set[int],
    tier: str = SUBSCRIPTION_TIER_ONLINE,
) -> tuple[int, int, int]:
    """
    Тренер с активной подпиской и слотом на день. Возвращает
    (trainer_id, service_id, slot_id первого слота по дате/часу).
    """
    sid, cid, aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body: dict = {
            "profile": {
                "first_name": "Клиент",
                "last_name": "API",
                "age": 30,
                "city_id": cid,
                "min_hours_before_booking": 0,
            },
            "service_ids": [sid],
        }
        if aid is not None:
            body["arena_ids"] = [aid]
        create_resp = await client.post("/api/trainers", json=body)
        assert create_resp.status_code == 200, create_resp.text
        trainer_id = create_resp.json()["id"]
        await client.patch(f"/api/trainers/{trainer_id}/status", json={"status": "active"})

    await _ensure_trainer_subscription_tier(db_session, trainer_id, tier)

    await replace_slots_for_day(db_session, trainer_id, slot_date, {h * 60 for h in start_hours}, 60)
    r = await db_session.execute(
        text(
            """
            SELECT id FROM slots
            WHERE trainer_id = :tid AND slot_date = :d
            ORDER BY start_time
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "d": slot_date},
    )
    slot_row = r.fetchone()
    assert slot_row is not None
    return trainer_id, sid, int(slot_row[0])


def _minsk_monday_reference() -> tuple[date, datetime]:
    """Фиксированный «сегодня» — понедельник 10:00 Europe/Minsk для фильтра слотов."""
    d = date(2026, 3, 9)
    dt = datetime(2026, 3, 9, 10, 0, 0)
    return d, dt


@pytest.mark.asyncio
async def test_client_session_get_and_post_roundtrip(app_use_test_db, db_session) -> None:
    sid, cid, aid = await _require_seed_ids(db_session)
    ctg = _fresh_client_telegram_id()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={
                "profile": {"first_name": "Сесс", "last_name": "Ия", "age": 28, "city_id": cid},
                "service_ids": [sid],
            },
        )
        trainer_id = create_resp.json()["id"]

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            empty = await client.get("/api/webapp/client/session", headers={"X-Telegram-Init-Data": "mock"})
            assert empty.status_code == 200
            assert empty.json().get("trainer_id") is None

            post = await client.post(
                "/api/webapp/client/session",
                json={
                    "city_id": cid,
                    "service_id": sid,
                    "arena_id": aid,
                    "trainer_id": trainer_id,
                },
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert post.status_code == 200
            assert post.json().get("success") is True

            loaded = await client.get("/api/webapp/client/session", headers={"X-Telegram-Init-Data": "mock"})
            assert loaded.status_code == 200
            body = loaded.json()
            assert body.get("city_id") == cid
            assert body.get("service_id") == sid
            assert body.get("trainer_id") == trainer_id
            assert body.get("arena_id") == aid
            assert isinstance(body.get("city_name"), (str, type(None)))
            assert isinstance(body.get("trainer_name"), (str, type(None)))


@pytest.mark.asyncio
async def test_init_data_query_param_same_as_header_for_session(app_use_test_db, db_session) -> None:
    await _require_seed_ids(db_session)
    ctg = _fresh_client_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            via_h = await client.get("/api/webapp/client/session", headers={"X-Telegram-Init-Data": "mock"})
            q = quote("mock", safe="")
            via_q = await client.get(f"/api/webapp/client/session?init_data={q}")
    assert via_h.status_code == 200
    assert via_q.status_code == 200
    assert via_h.json() == via_q.json()


@pytest.mark.asyncio
async def test_init_data_query_wins_over_header_when_both_present(app_use_test_db, db_session) -> None:
    """
    raw = init_data or x_telegram_init_data — приоритет у query (как в schedule/trainer).
    Должно согласовываться с тем, какой user_id реально валидируется.
    """
    await _require_seed_ids(db_session)
    user_a = _fresh_client_telegram_id()
    user_b = _fresh_client_telegram_id()

    def _side_effect(raw: str, _token: object) -> MiniAppPrincipal:
        if "token_a" in raw:
            return MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_a)
        if "token_b" in raw:
            return MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_b)
        return MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_a)

    with patch(_CLIENT_MINIAPP_VERIFY_PATCH, side_effect=_side_effect):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            q = quote("token_b", safe="")
            resp = await client.get(
                f"/api/webapp/client/session?init_data={q}",
                headers={"X-Telegram-Init-Data": "token_a"},
            )
    assert resp.status_code == 200
    # session для user_b — пустой выбор; главное: не user_a (у которого могла бы быть другая сессия)
    # при отсутствии строки client_session для нового tg trainer_id будет None
    assert resp.json().get("trainer_id") is None


@pytest.mark.asyncio
async def test_client_routes_401_without_init(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.get("/api/webapp/client/session")
        r2 = await client.get("/api/webapp/client/slots?trainer_id=1")
        r3 = await client.post("/api/webapp/client/booking", json={"slot_id": 1, "phone": "+375291112233"})
        r4 = await client.get("/api/webapp/client/activity-stats")
    assert r1.status_code == 401
    assert r2.status_code == 401
    assert r3.status_code == 401
    assert r4.status_code == 401


@pytest.mark.asyncio
async def test_client_routes_401_invalid_init_data(app_use_test_db) -> None:
    def _bad(*_a, **_kw) -> int:
        raise InitDataAuthError("bad")

    with patch(_CLIENT_MINIAPP_VERIFY_PATCH, side_effect=_bad):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/webapp/client/session", headers={"X-Telegram-Init-Data": "x"})
    assert resp.status_code == 401
    assert resp.json().get("detail") == MINIAPP_CREDENTIAL_USER_DETAIL_RU
    assert resp.headers.get(MINIAPP_AUTH_ERROR_HEADER) == "1"


@pytest.mark.asyncio
async def test_client_activity_stats_zeros_when_no_client_row(app_use_test_db, db_session) -> None:
    """TG user без строки clients: снимок нулевой (не ошибка)."""
    await _require_seed_ids(db_session)
    ctg = _fresh_client_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/webapp/client/activity-stats", headers={"X-Telegram-Init-Data": "mock"}
            )
    assert r.status_code == 200
    body = r.json()
    assert body.get("completed_total") == 0
    assert body.get("completed_minutes_total") == 0
    assert body.get("upcoming_bookings_count") == 0
    assert body.get("last_completed_at") is None
    assert body.get("first_completed_at") is None
    assert body.get("streak_weeks") == 0
    assert body.get("top_trainer") is None


@pytest.mark.asyncio
async def test_slots_active_trainer_crm_only_returns_empty_and_flag_false(
    app_use_test_db, db_session
) -> None:
    """Без tier online клиент не видит онлайн-слотов; активный тренер — не 404."""
    ref_day, ref_now = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=3)
    trainer_id, _sid, _slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={14}, tier=SUBSCRIPTION_TIER_CRM
    )
    ctg = _fresh_client_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with (
                patch("src.api.routes.webapp.get_slots_cached", return_value=None),
                patch("src.api.routes.webapp.datetime") as mock_dt,
                patch("src.api.routes.webapp.date") as mock_date,
            ):
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                mock_dt.strftime = datetime.strftime
                resp = await client.get(
                    f"/api/webapp/client/slots?trainer_id={trainer_id}",
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("online_booking_available") is False
    assert data.get("slots") == []


@pytest.mark.asyncio
async def test_slots_unknown_trainer_404(app_use_test_db, db_session) -> None:
    await _require_seed_ids(db_session)
    ctg = _fresh_client_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/client/slots?trainer_id=999999999",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_slots_respects_min_working_hours_window(app_use_test_db, db_session) -> None:
    """
    Слот слишком близко по «рабочим часам» до начала — не должен попадать в выдачу при min_hours=3.
    """
    ref_day, _ = _minsk_monday_reference()
    # Пятница той же недели, слот 12:00
    slot_day = ref_day + timedelta(days=4)
    trainer_id, _sid, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={12}
    )
    ctg = _fresh_client_telegram_id()
    friday_morning = datetime.combine(slot_day, time(10, 0))
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with (
                patch("src.api.routes.webapp.get_slots_cached", return_value=None),
                patch("src.api.routes.webapp.datetime") as mock_dt,
                patch("src.api.routes.webapp.date") as mock_date,
            ):
                mock_date.today.return_value = ref_day
                # Пятница 10:00 — до слота 12:00 меньше 3 «рабочих» часов в окне 8–22
                mock_dt.now.return_value = friday_morning
                mock_dt.combine = datetime.combine
                resp = await client.get(
                    f"/api/webapp/client/slots?trainer_id={trainer_id}&min_hours=3",
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json().get("slots") or []]
    assert slot_id not in ids


@pytest.mark.asyncio
async def test_slots_include_group_when_service_from_session_and_query_omits_service_id(
    app_use_test_db, db_session
) -> None:
    """
    Каталог передаёт service_id в query; кнопка «Записаться» из welcome/бота может открывать book
    только с trainer_id. Тогда /client/slots должен взять selected_service_id из client_sessions
    при совпадении selected_trainer_id — иначе групповые слоты пропадают.
    """
    ref_day, ref_now = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=3)
    trainer_id, sid, _ = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={11}, tier=SUBSCRIPTION_TIER_ONLINE
    )
    await replace_slots_for_day(
        db_session, trainer_id, slot_day, {9 * 60}, 60, capacity=4, group_service_id=sid
    )
    ctg = _fresh_client_telegram_id()
    seed_sid, cid, aid = await _require_seed_ids(db_session)
    assert int(sid) == int(seed_sid)
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            post = await client.post(
                "/api/webapp/client/session",
                json={
                    "city_id": cid,
                    "service_id": sid,
                    "arena_id": aid,
                    "trainer_id": trainer_id,
                },
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert post.status_code == 200
            with (
                patch("src.api.routes.webapp.get_slots_cached", return_value=None),
                patch("src.api.routes.webapp.datetime") as mock_dt,
                patch("src.api.routes.webapp.date") as mock_date,
            ):
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                resp = await client.get(
                    f"/api/webapp/client/slots?trainer_id={trainer_id}",
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert resp.status_code == 200
    slots = resp.json().get("slots") or []
    assert any(int(s.get("capacity") or 1) > 1 for s in slots), slots


@pytest.mark.asyncio
async def test_booking_happy_path_and_list_grouped_by_day(app_use_test_db, db_session) -> None:
    # list_bookings_for_client filters by real DB time — slot must be in the future vs CURRENT_TIMESTAMP.
    slot_day = date.today() + timedelta(days=14)
    ref_day = slot_day - timedelta(days=slot_day.weekday())
    ref_now = datetime.combine(ref_day, time(10, 0))
    trainer_id, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )
    ctg = _fresh_client_telegram_id()
    phone, _norm = belarus_test_phone(ctg)

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                "src.api.routes.webapp.date"
            ) as mock_date:
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                book = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "service_id": service_id,
                        "first_name": "Клиент",
                    },
                    headers={"X-Telegram-Init-Data": "mock"},
                )
            assert book.status_code == 200
            bid = book.json().get("booking_id")
            assert isinstance(bid, int)

            listed = await client.get(
                "/api/webapp/client/bookings",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert listed.status_code == 200
    days = listed.json().get("days") or []
    assert len(days) >= 1
    first_day = days[0]
    assert "date" in first_day and "bookings" in first_day
    booking_ids = [b["id"] for d in days for b in d.get("bookings") or []]
    assert bid in booking_ids
    found = next((b for d in days for b in d.get("bookings") or [] if b.get("id") == bid), None)
    assert found is not None
    assert found.get("service_name"), "client bookings list must include service_name"
    assert "service_id" in found


@pytest.mark.asyncio
async def test_booking_with_existing_offline_client_phone_links_telegram_silently(
    app_use_test_db, db_session
) -> None:
    ref_day, ref_now = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=4)
    _trainer_id, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )
    ctg = _fresh_client_telegram_id()
    phone, phone_norm = belarus_test_phone(ctg)
    r_offline = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (NULL, 'Офлайн', 'Клиент', :phone, :pn)
            RETURNING id
            """
        ),
        {"phone": phone, "pn": phone_norm},
    )
    offline_client_id = int(r_offline.fetchone()[0])
    await db_session.commit()

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                "src.api.routes.webapp.date"
            ) as mock_date:
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                book = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "service_id": service_id,
                        "first_name": "Алексей",
                    },
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert book.status_code == 200
    booking_id = int(book.json()["booking_id"])

    r_clients = await db_session.execute(
        text(
            """
            SELECT id, telegram_id
            FROM clients
            WHERE phone_normalized = :pn
            ORDER BY id
            """
        ),
        {"pn": phone_norm},
    )
    rows = r_clients.fetchall()
    assert len(rows) == 1
    assert int(rows[0][0]) == offline_client_id
    assert int(rows[0][1]) == ctg

    r_booking = await db_session.execute(
        text("SELECT client_id FROM bookings WHERE id = :bid"),
        {"bid": booking_id},
    )
    assert int(r_booking.scalar()) == offline_client_id


@pytest.mark.asyncio
async def test_booking_second_post_same_slot_is_not_idempotent(app_use_test_db, db_session) -> None:
    """Повторное бронирование того же слота должно отклоняться (конверсия / целостность)."""
    ref_day, ref_now = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=4)
    _tid, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )
    ctg = _fresh_client_telegram_id()
    phone, _norm = belarus_test_phone(ctg)

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                "src.api.routes.webapp.date"
            ) as mock_date:
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                first = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "service_id": service_id,
                        "first_name": "Клиент",
                    },
                    headers={"X-Telegram-Init-Data": "mock"},
                )
                second = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "service_id": service_id,
                        "first_name": "Клиент",
                    },
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert first.status_code == 200
    assert second.status_code == 400
    assert "not available" in (second.json().get("detail") or "").lower()


@pytest.mark.asyncio
async def test_parallel_post_booking_same_slot_one_400(app_use_test_db, db_session) -> None:
    """Два POST на один слот подряд: первый 200, второй 400 (слот уже занят после create_booking)."""
    ref_day, ref_now = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=4)
    _tid, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                "src.api.routes.webapp.date"
            ) as mock_date:
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                r1 = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "service_id": service_id,
                        "first_name": "Клиент",
                    },
                    headers={"X-Telegram-Init-Data": "mock"},
                )
                r2 = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "service_id": service_id,
                        "first_name": "Клиент",
                    },
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert r1.status_code == 200
    assert r2.status_code == 400
    assert "not available" in (r2.json().get("detail") or "").lower()


@pytest.mark.asyncio
async def test_booking_rejects_wrong_service_for_trainer(app_use_test_db, db_session) -> None:
    ref_day, ref_now = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=4)
    sid_a, cid, _aid = await _require_seed_ids(db_session)
    r_other = await db_session.execute(
        text("SELECT id FROM services WHERE id != :sid ORDER BY id LIMIT 1"),
        {"sid": sid_a},
    )
    other = r_other.scalar()
    if other is None:
        pytest.skip("need at least two services in seed")
    _tid, _s, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                "src.api.routes.webapp.date"
            ) as mock_date:
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                resp = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "service_id": int(other),
                        "first_name": "Клиент",
                    },
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_booking_requires_phone_digits(app_use_test_db, db_session) -> None:
    ref_day, ref_now = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=4)
    _tid, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )
    ctg = _fresh_client_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                "src.api.routes.webapp.date"
            ) as mock_date:
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                resp = await client.post(
                    "/api/webapp/client/booking",
                    json={"slot_id": slot_id, "phone": "123", "service_id": service_id},
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_booking_with_request_id_uses_service_from_request(app_use_test_db, db_session) -> None:
    """Заявка с откликом тренера: бронь без service_id в теле, service_id из заявки."""
    ref_day, ref_now = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=4)
    trainer_id, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )
    sid, cid, _aid = await _require_seed_ids(db_session)
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            cr = await client.post(
                "/api/webapp/client/request",
                json={
                    "city_id": cid,
                    "service_id": sid,
                    "comment": "запись из заявки",
                    "first_name": "Клиент",
                },
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert cr.status_code == 200
            request_id = cr.json()["request_id"]

    await db_session.execute(
        text(
            """
            INSERT INTO client_request_responses (client_request_id, trainer_id)
            VALUES (:rid, :tid)
            """
        ),
        {"rid": request_id, "tid": trainer_id},
    )
    await db_session.commit()

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                "src.api.routes.webapp.date"
            ) as mock_date:
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                book = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "request_id": request_id,
                    },
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert book.status_code == 200
    assert book.json().get("booking_id") is not None
    # service в заявке должен совпадать с услугой тренера для сценария
    assert sid == service_id


@pytest.mark.asyncio
async def test_booking_online_tier_required(app_use_test_db, db_session) -> None:
    ref_day, ref_now = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=4)
    trainer_id, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}, tier=SUBSCRIPTION_TIER_CRM
    )
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                "src.api.routes.webapp.date"
            ) as mock_date:
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                resp = await client.post(
                    "/api/webapp/client/booking",
                    json={"slot_id": slot_id, "phone": phone, "service_id": service_id},
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert resp.status_code == 403
    assert resp.headers.get("X-Error-Code") == "TRAINER_NO_ONLINE_TIER"


@pytest.mark.asyncio
async def test_cancel_booking_success_and_second_cancel_fails(
    app_use_test_db, db_session
) -> None:
    ref_day, ref_now = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=4)
    _tid, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_bot.session = MagicMock()
    mock_bot.session.close = AsyncMock()

    with patch_client_init_auth(ctg):
        with patch("src.api.routes.webapp.Bot", return_value=mock_bot):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                    "src.api.routes.webapp.date"
                ) as mock_date:
                    mock_date.today.return_value = ref_day
                    mock_dt.now.return_value = ref_now
                    mock_dt.combine = datetime.combine
                    book = await client.post(
                        "/api/webapp/client/booking",
                        json={
                            "slot_id": slot_id,
                            "phone": phone,
                            "service_id": service_id,
                            "first_name": "Клиент",
                        },
                        headers={"X-Telegram-Init-Data": "mock"},
                    )
                bid = book.json()["booking_id"]
                c1 = await client.post(
                    f"/api/webapp/client/bookings/{bid}/cancel",
                    json={"reason": "план"},
                    headers={"X-Telegram-Init-Data": "mock"},
                )
                c2 = await client.post(
                    f"/api/webapp/client/bookings/{bid}/cancel",
                    json={},
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert book.status_code == 200
    assert c1.status_code == 200
    assert c2.status_code == 400


@pytest.mark.asyncio
async def test_cancel_booking_other_client_400(app_use_test_db, db_session) -> None:
    ref_day, ref_now = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=4)
    _tid, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )
    owner = _fresh_client_telegram_id()
    stranger = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(owner)

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_bot.session = MagicMock()
    mock_bot.session.close = AsyncMock()

    with patch_client_init_auth(owner):
        with patch("src.api.routes.webapp.Bot", return_value=mock_bot):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                    "src.api.routes.webapp.date"
                ) as mock_date:
                    mock_date.today.return_value = ref_day
                    mock_dt.now.return_value = ref_now
                    mock_dt.combine = datetime.combine
                    book = await client.post(
                        "/api/webapp/client/booking",
                        json={
                            "slot_id": slot_id,
                            "phone": phone,
                            "service_id": service_id,
                            "first_name": "Клиент",
                        },
                        headers={"X-Telegram-Init-Data": "mock"},
                    )
                bid = book.json()["booking_id"]

    with patch_client_init_auth(stranger):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/webapp/client/bookings/{bid}/cancel",
                json={},
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_client_request_create_list_patch_delete(app_use_test_db, db_session) -> None:
    sid, cid, _aid = await _require_seed_ids(db_session)
    ctg = _fresh_client_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            cr = await client.post(
                "/api/webapp/client/request",
                json={
                    "city_id": cid,
                    "service_id": sid,
                    "comment": "тест",
                    "first_name": "Клиент",
                },
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert cr.status_code == 200
            rid = cr.json()["request_id"]
            listed = await client.get(
                "/api/webapp/client/requests",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert listed.status_code == 200
            items = listed.json().get("items") or []
            assert any(x.get("id") == rid for x in items)

            patched = await client.patch(
                f"/api/webapp/client/requests/{rid}",
                json={"comment": "обновлено"},
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert patched.status_code == 200
            req_after = patched.json().get("request")
            assert req_after is not None
            new_id = req_after["id"]
            assert new_id != rid

            deleted = await client.delete(
                f"/api/webapp/client/requests/{new_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_pass_products_404_when_trainer_not_online_tier(app_use_test_db, db_session) -> None:
    ref_day, _ = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=4)
    trainer_id, _s, _slot = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={10}, tier=SUBSCRIPTION_TIER_CRM
    )
    ctg = _fresh_client_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/client/pass-products?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_slots_online_trainer_includes_slot_when_min_hours_satisfied(
    app_use_test_db, db_session
) -> None:
    """Позитивный путь: онлайн-тренер, слот достаточно далеко — id есть в списке."""
    ref_day, ref_now = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=4)
    trainer_id, _sid, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )
    ctg = _fresh_client_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with (
                patch("src.api.routes.webapp.get_slots_cached", return_value=None),
                patch("src.api.routes.webapp.datetime") as mock_dt,
                patch("src.api.routes.webapp.date") as mock_date,
            ):
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                resp = await client.get(
                    f"/api/webapp/client/slots?trainer_id={trainer_id}&min_hours=3",
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("online_booking_available") is True
    ids = [s["id"] for s in data.get("slots") or []]
    assert slot_id in ids


@pytest.mark.asyncio
async def test_pass_products_ok_for_online_tier_trainer(app_use_test_db, db_session) -> None:
    ref_day, _ = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=3)
    trainer_id, _s, _slot = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={11}
    )
    ctg = _fresh_client_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/client/pass-products?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    assert "items" in resp.json()


@pytest.mark.asyncio
async def test_get_passes_empty_for_new_client(app_use_test_db) -> None:
    ctg = _fresh_client_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/client/passes",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    assert resp.json().get("items") == []


@pytest.mark.asyncio
async def test_certificate_activate_403_when_client_row_missing(app_use_test_db) -> None:
    """Активация привязана к клиенту в БД; только initData недостаточно."""
    ctg = _fresh_client_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/client/certificates/activate",
                json={"code": "ANY-CODE"},
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 403
    assert "client" in (resp.json().get("detail") or "").lower()


@pytest.mark.asyncio
async def test_certificate_products_requires_auth(app_use_test_db, db_session) -> None:
    sid, cid, _ = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={
                "profile": {"first_name": "Серт", "last_name": "Продукт", "age": 29, "city_id": cid},
                "service_ids": [sid],
            },
        )
        trainer_id = create_resp.json()["id"]
    ctg = _fresh_client_telegram_id()
    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/client/certificate-products?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    assert "items" in resp.json()


@pytest.mark.asyncio
async def test_webapp_client_home_page_served() -> None:
    """Static Mini App: client hub HTML is reachable (route + file present)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/webapp/client-home")
    assert resp.status_code == 200
    body = resp.text
    assert "data-client-hub" in body
    assert "client-home-main.js" in body
    assert "Главная" in body
