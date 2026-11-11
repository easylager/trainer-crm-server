"""TASK-368: GET /client/me и запись имени и «моего катка»."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.app import app
from src.api.miniapp_auth import MiniAppPrincipal, get_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform
from src.api.routes.webapp_client_me import router as me_router
from src.application.catalog_consumer_events import telegram_actor_hash
from src.application.client_me import initial_of, label_ink
from src.application.client_profile_use_cases import create_guardian_profile
from src.application.hockey_cache import invalidate_aggregates
from src.application.hockey_game import make_pick, score_finished_matches
from src.application.hockey_matches import set_manual_result
from src.application.hockey_notices import set_fav_club
from src.application.ice_session_use_cases import create_ice_session
from src.ingestion.hockey_sources import MINSK_TZ

ME = "/api/webapp/client/me"
_SECRET = "x" * 32


def test_label_ink_wcag() -> None:
    for color in ("#003DA5", "#C8102E", "#5D7285"):
        assert label_ink(color) == "#FFFFFF"
    assert label_ink("#F2C94C") == "#0D1B26"


def test_initial_keeps_emoji_out_of_the_letter() -> None:
    assert initial_of("Максим 🌱") == "М"
    assert initial_of("🌱") == "?"
    assert initial_of("123") == "?"


def test_no_club_route() -> None:
    paths = {route.path for route in me_router.routes}
    assert paths == {"/client/me", "/client/me/name", "/client/me/home-arena"}


def _raw(user_id: int, first: str, last: str = "") -> str:
    user = json.dumps({"id": user_id, "first_name": first, "last_name": last}, ensure_ascii=False)
    return urlencode({"user": user, "auth_date": "1"})


def _auth(user_id: int) -> None:
    principal = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)
    app.dependency_overrides[get_client_miniapp_principal] = lambda: principal


def _clear_auth() -> None:
    app.dependency_overrides.pop(get_client_miniapp_principal, None)


@pytest.fixture
def client_me_auth():
    yield
    _clear_auth()


async def _get(headers: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(ME, headers=headers or {})


async def _put(path: str, body: dict, headers: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.put(ME + path, json=body, headers=headers or {})


async def _city(db: AsyncSession) -> int:
    return (
        await db.execute(
            text("""
                INSERT INTO cities (name, country, is_active)
                VALUES (:name, 'BY', true)
                RETURNING id
                """),
            {"name": f"Я-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()


async def _arena(db: AsyncSession, city_id: int, *, name: str, active: bool = True) -> int:
    return (
        await db.execute(
            text("""
                INSERT INTO arenas (city_id, name, is_active, is_confirmed)
                VALUES (:city_id, :name, :active, true)
                RETURNING id
                """),
            {"city_id": city_id, "name": name, "active": active},
        )
    ).scalar_one()


async def _client_row(db: AsyncSession, telegram_id: int, first: str, last: str | None = None) -> int:
    return (
        await db.execute(
            text("""
                INSERT INTO clients (telegram_id, first_name, last_name)
                VALUES (:tg, :first, :last)
                RETURNING id
                """),
            {"tg": telegram_id, "first": first, "last": last},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_ac7_no_init_data_is_401(app_use_test_db) -> None:
    response = await _get()
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_ac1_ac2_catalog_person(app_use_test_db, db_session, client_me_auth, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", _SECRET)
    user_id = 368_100_001
    _auth(user_id)
    headers = {"X-Telegram-Init-Data": _raw(user_id, "Максим", "Василенко")}
    response = await _get(headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "name",
        "initial",
        "city",
        "club",
        "home_arena",
        "stats",
        "rows",
        "profile_name",
    }
    assert body["name"] == "Максим В."
    assert body["initial"] == "М"
    assert body["city"] is None
    assert body["club"] is None
    assert body["home_arena"] is None
    assert body["stats"] == {
        "trainings": None,
        "streak_weeks": None,
        "kk_points": None,
        "kk_place": None,
    }
    assert body["rows"]["bookings"] is None
    assert body["rows"]["passes"] is None
    assert body["rows"]["saved"] is None
    assert body["rows"]["requests"] is None
    assert body["rows"]["family"] == {
        "people": [
            {"profile_id": None, "name": "Максим В.", "is_you": True, "active": True},
        ]
    }
    assert body["profile_name"] is None

    again = await _get(headers)
    assert again.status_code == 200
    actor = telegram_actor_hash(user_id)
    opened = (
        await db_session.execute(
            text("""
                SELECT COUNT(*) FROM catalog_consumer_events
                WHERE kind = 'me_open' AND actor_hash = :actor
                """),
            {"actor": actor},
        )
    ).scalar_one()
    assert int(opened) == 1


@pytest.mark.asyncio
async def test_ac3_name_sticks_through_a_pick(app_use_test_db, db_session, client_me_auth, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", _SECRET)
    user_id = 368_100_002
    _auth(user_id)
    saved = await _put("/name", {"name": "  Максим 🌱  "})
    assert saved.status_code == 200
    assert saved.json() == {"name": "Максим 🌱"}
    renamed = await _put("/name", {"name": "Макс"})
    assert renamed.status_code == 200
    assert renamed.json() == {"name": "Макс"}
    blank = await _put("/name", {"name": "   "})
    assert blank.status_code == 422
    assert blank.json() == {"detail": "Имя — от 1 до 40 знаков"}
    long = await _put("/name", {"name": "а" * 41})
    assert long.status_code == 422
    assert long.json()["detail"] == "Имя — от 1 до 40 знаков"

    now = datetime.now(MINSK_TZ)
    match_id = (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
                VALUES ('hcdinamo', :mid, 'Динамо-Минск', 'СКА', :starts_at)
                RETURNING id
                """),
            {"mid": f"t368-name-{user_id}", "starts_at": now + timedelta(hours=2)},
        )
    ).scalar_one()
    await make_pick(
        db_session,
        player_key=user_id,
        display_name="Другое имя",
        match_id=int(match_id),
        side="home",
        now=now,
    )
    me = await _get({"X-Telegram-Init-Data": _raw(user_id, "Максим", "Василенко")})
    assert me.json()["name"] == "Макс"
    assert me.json()["initial"] == "М"
    named = (
        await db_session.execute(text("SELECT COUNT(*) FROM catalog_consumer_events WHERE kind = 'me_name_set'"))
    ).scalar_one()
    assert int(named) == 2


@pytest.mark.asyncio
async def test_ac4_ac6_club_and_home_arena(app_use_test_db, db_session, client_me_auth, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", _SECRET)
    user_id = 368_100_003
    _auth(user_id)
    await set_fav_club(db_session, user_id, "Динамо-Минск", display_name="Максим")
    now = datetime.now(MINSK_TZ)
    await db_session.execute(
        text("""
            INSERT INTO hockey_matches (
                source, source_match_id, home_team, away_team, starts_at, status,
                home_score, away_score, decided_in, result_source
            )
            VALUES
              ('hcdinamo', :near, 'Динамо-Минск', 'СКА', :near_at, 'scheduled', NULL, NULL, NULL, NULL),
              ('hcdinamo', :far, 'Динамо-Минск', 'ЦСКА', :far_at, 'scheduled', NULL, NULL, NULL, NULL),
              ('hcdinamo', :done, 'Динамо-Минск', 'Барыс', :done_at, 'final', 3, 1, 'regulation', 'manual')
            """),
        {
            "near": f"t368-near-{user_id}",
            "far": f"t368-far-{user_id}",
            "done": f"t368-done-{user_id}",
            "near_at": now + timedelta(days=2),
            "far_at": now + timedelta(days=20),
            "done_at": now + timedelta(days=1),
        },
    )
    city_id = await _city(db_session)
    rink = await _arena(db_session, city_id, name="«Чижовка-арена»")
    hidden = await _arena(db_session, city_id, name="Скрытый", active=False)
    tomorrow = (datetime.now(ZoneInfo("Europe/Minsk")) + timedelta(days=1)).date()
    await create_ice_session(
        db_session,
        rink,
        local_date=tomorrow,
        starts_at_local="09:00",
        duration_minutes=45,
        kind="public_skate",
        price_adult_minor=1000,
    )
    client_id = await _client_row(db_session, user_id, "Максим")
    await db_session.execute(
        text("""
            INSERT INTO client_sessions (telegram_id, state, city_id)
            VALUES (:tg, 'idle', :city)
            """),
        {"tg": user_id, "city": city_id},
    )
    await db_session.execute(
        text("""
            INSERT INTO client_ice_watches (client_id, telegram_id, arena_id, watch_kind, filter_json, active)
            VALUES (:cid, :tg, :aid, 'sessions', '{}'::jsonb, true)
            """),
        {"cid": client_id, "tg": user_id, "aid": rink},
    )

    missing = await _put("/home-arena", {"arena_id": hidden})
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Каток не найден"}
    foreign = await _put("/home-arena", {"arena_id": 2_147_483_647})
    assert foreign.status_code == 404

    put = await _put("/home-arena", {"arena_id": rink})
    assert put.status_code == 200
    home = put.json()["home_arena"]
    assert home["id"] == rink
    assert home["name"] == "«Чижовка-арена»"
    assert home["href"] == f"/webapp/arena?id={rink}"
    assert home["sessions_left_today"] == 0
    assert home["tomorrow_first"] == "9:00"
    assert home["subscribed"] is True

    me = await _get()
    body = me.json()
    assert (
        body["city"]
        == (await db_session.execute(text("SELECT name FROM cities WHERE id = :id"), {"id": city_id})).scalar_one()
    )
    assert body["club"]["name"] == "Динамо-Минск"
    assert body["club"]["short"] == "ДМ"
    assert body["club"]["color"] == "#003DA5"
    assert body["club"]["label_ink"] == "#FFFFFF"
    assert set(body["club"]) == {"name", "short", "color", "logo", "label_ink", "next_match"}
    assert body["club"]["next_match"]["opponent"] == "СКА"
    assert body["club"]["next_match"]["href"] == "/webapp/kto-kogo"
    assert body["club"]["next_match"]["starts_at"].endswith("+03:00")
    assert body["home_arena"]["tomorrow_first"] == "9:00"

    cleared = await _put("/home-arena", {"arena_id": None})
    assert cleared.status_code == 200
    assert cleared.json() == {"home_arena": None}
    events = (
        (
            await db_session.execute(
                text("""
                SELECT payload->>'arena_id'
                FROM catalog_consumer_events
                WHERE kind = 'me_home_arena_set'
                ORDER BY id
                """)
            )
        )
        .scalars()
        .all()
    )
    assert events == [str(rink), None]


@pytest.mark.asyncio
async def test_ac5_child_profile(app_use_test_db, db_session, client_me_auth) -> None:
    user_id = 368_100_004
    _auth(user_id)
    parent = await _client_row(db_session, user_id, "Максим", "В.")
    child = await create_guardian_profile(db_session, user_id, first_name="Миша", last_name="Ковалёв")
    await set_fav_club(db_session, user_id, "СКА", display_name="Максим")
    city_id = await _city(db_session)
    service_id = (
        await db_session.execute(text("INSERT INTO services (name) VALUES ('Хоккей') RETURNING id"))
    ).scalar_one()
    trainer_id = (
        await db_session.execute(
            text("""
                INSERT INTO trainers (status, is_catalog_visible, catalog_state)
                VALUES ('active', true, 'published')
                RETURNING id
                """)
        )
    ).scalar_one()
    now = datetime.now(MINSK_TZ)
    future = now + timedelta(days=1)
    past = now - timedelta(days=2)

    async def _slot(on: datetime) -> int:
        local = on.astimezone(MINSK_TZ)
        return (
            await db_session.execute(
                text("""
                    INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
                    VALUES (:tid, :d, TIME '18:00', TIME '18:45', 'booked')
                    RETURNING id
                    """),
                {"tid": trainer_id, "d": local.date()},
            )
        ).scalar_one()

    parent_slot = await _slot(future)
    child_slot = await _slot(past)
    await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:slot, :tid, :cid, :sid, 'confirmed')
            """),
        {"slot": parent_slot, "tid": trainer_id, "cid": parent, "sid": service_id},
    )
    await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:slot, :tid, :cid, :sid, 'completed')
            """),
        {"slot": child_slot, "tid": trainer_id, "cid": child, "sid": service_id},
    )
    product = (
        await db_session.execute(
            text("""
                INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents)
                VALUES (:tid, '4 занятия', 4, 10000)
                RETURNING id
                """),
            {"tid": trainer_id},
        )
    ).scalar_one()
    await db_session.execute(
        text("""
            INSERT INTO pass_instances (
                client_id, pass_product_id, sessions_remaining, sessions_total, price_cents, status
            )
            VALUES (:cid, :pid, 4, 4, 10000, 'active')
            """),
        {"cid": parent, "pid": product},
    )
    await db_session.execute(
        text("""
            INSERT INTO client_requests (client_id, city_id, service_id, status)
            VALUES (:cid, :city, :sid, 'new')
            """),
        {"cid": child, "city": city_id, "sid": service_id},
    )
    await db_session.execute(
        text("""
            INSERT INTO client_sessions (telegram_id, state, city_id)
            VALUES (:tg, 'idle', :city)
            """),
        {"tg": user_id, "city": city_id},
    )
    await db_session.execute(
        text("""
            INSERT INTO client_trainer_edges (client_id, telegram_id, trainer_id, is_saved)
            VALUES (:cid, :tg, :tid, true)
            """),
        {"cid": parent, "tg": user_id, "tid": trainer_id},
    )
    played = now - timedelta(days=3)
    match_id = (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
                VALUES ('hcdinamo', :mid, 'Динамо-Минск', 'СКА', :starts_at)
                RETURNING id
                """),
            {"mid": f"t368-child-{user_id}", "starts_at": played + timedelta(hours=2)},
        )
    ).scalar_one()
    await make_pick(
        db_session,
        player_key=user_id,
        display_name="Максим",
        match_id=int(match_id),
        side="away",
        now=played,
    )
    await set_manual_result(
        db_session,
        int(match_id),
        home_score=1,
        away_score=2,
        decided_in="regulation",
        now=played + timedelta(hours=5),
    )
    await score_finished_matches(db_session, now=played + timedelta(hours=5))

    own = (await _get()).json()
    child_body = (await _get({"X-Profile-Id": str(child)})).json()

    assert own["profile_name"] is None
    assert child_body["profile_name"] == "Миша Ковалёв"
    assert own["name"] == child_body["name"] == "Максим"
    assert own["club"]["short"] == child_body["club"]["short"] == "СК"
    assert own["home_arena"] is None and child_body["home_arena"] is None
    assert own["stats"]["kk_points"] == child_body["stats"]["kk_points"]
    assert own["stats"]["kk_points"] not in (None, 0)
    assert own["stats"]["kk_place"] == child_body["stats"]["kk_place"]
    assert own["stats"]["trainings"] is None
    assert child_body["stats"]["trainings"] == 1
    assert own["rows"]["bookings"]["next_starts_at"] is not None
    assert child_body["rows"]["bookings"]["next_starts_at"] is None
    assert own["rows"]["passes"] == {"lessons_left": 4}
    assert child_body["rows"]["passes"] is None
    assert own["rows"]["saved"] == {"count": 1}
    assert child_body["rows"]["saved"] is None
    assert own["rows"]["requests"] is None
    assert child_body["rows"]["requests"] == {"count": 1}
    assert own["rows"]["family"]["people"] == [
        {"profile_id": parent, "name": "Максим", "is_you": True, "active": True},
        {"profile_id": child, "name": "Миша", "is_you": False, "active": False},
    ]
    assert child_body["rows"]["family"]["people"] == [
        {"profile_id": parent, "name": "Максим", "is_you": True, "active": False},
        {"profile_id": child, "name": "Миша", "is_you": False, "active": True},
    ]


@pytest.mark.asyncio
async def test_foreign_profile_does_not_add_people(app_use_test_db, db_session, client_me_auth) -> None:
    user_id = 368_200_001
    _auth(user_id)
    parent = await _client_row(db_session, user_id, "Максим")
    child = await create_guardian_profile(db_session, user_id, first_name="Миша")
    other_id = 368_200_002
    await _client_row(db_session, other_id, "Чужой")
    foreign = await create_guardian_profile(db_session, other_id, first_name="Чужая")

    body = (await _get({"X-Profile-Id": str(foreign)})).json()
    assert body["rows"]["family"]["people"] == [
        {"profile_id": parent, "name": "", "is_you": True, "active": True},
        {"profile_id": child, "name": "Миша", "is_you": False, "active": False},
    ]
    assert body["profile_name"] is None


@pytest.mark.asyncio
async def test_child_emoji_name_is_kept(app_use_test_db, db_session, client_me_auth) -> None:
    user_id = 368_200_003
    _auth(user_id)
    parent = await _client_row(db_session, user_id, "Максим")
    child = await create_guardian_profile(db_session, user_id, first_name="Аня 🌱")

    people = (await _get()).json()["rows"]["family"]["people"]
    assert people == [
        {"profile_id": parent, "name": "", "is_you": True, "active": True},
        {"profile_id": child, "name": "Аня 🌱", "is_you": False, "active": False},
    ]


@pytest.mark.asyncio
async def test_family_access_child_is_a_person(app_use_test_db, db_session, client_me_auth) -> None:
    owner_id = 368_200_004
    child = await _client_row(db_session, owner_id, "Аня")
    second_id = 368_200_005
    second = await _client_row(db_session, second_id, "Катя")
    await db_session.execute(
        text("""
            INSERT INTO client_family_access_members (primary_client_id, member_telegram_id)
            VALUES (:pid, :mtid)
            """),
        {"pid": child, "mtid": second_id},
    )
    _auth(second_id)

    body = (await _get({"X-Telegram-Init-Data": _raw(second_id, "Екатерина")})).json()
    assert body["name"] == "Екатерина"
    assert body["rows"]["family"]["people"] == [
        {"profile_id": second, "name": "Екатерина", "is_you": True, "active": True},
        {"profile_id": child, "name": "Аня", "is_you": False, "active": False},
    ]


def _listen(db: AsyncSession) -> tuple[list[str], object]:
    statements: list[str] = []

    def _before(_conn, _cursor, statement, _params, _context, _executemany) -> None:
        statements.append(statement)

    bind = db.sync_session.get_bind()
    event.listen(bind, "before_cursor_execute", _before)
    return statements, _before


@pytest.mark.asyncio
async def test_one_query_per_source(app_use_test_db, db_session, client_me_auth) -> None:
    """Число запросов не растёт от числа записей: на источник один запрос, не N+1."""
    user_id = 368_100_005
    _auth(user_id)
    parent = await _client_row(db_session, user_id, "Максим")
    city_id = await _city(db_session)
    service_id = (
        await db_session.execute(text("INSERT INTO services (name) VALUES ('Лёд') RETURNING id"))
    ).scalar_one()
    trainer_id = (
        await db_session.execute(
            text("""
                INSERT INTO trainers (status, is_catalog_visible, catalog_state)
                VALUES ('active', true, 'published')
                RETURNING id
                """)
        )
    ).scalar_one()
    now = datetime.now(MINSK_TZ)

    async def _booking(day: int) -> None:
        local = (now + timedelta(days=day)).astimezone(MINSK_TZ)
        slot = (
            await db_session.execute(
                text("""
                    INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
                    VALUES (:tid, :d, TIME '18:00', TIME '18:45', 'booked')
                    RETURNING id
                    """),
                {"tid": trainer_id, "d": local.date()},
            )
        ).scalar_one()
        await db_session.execute(
            text("""
                INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
                VALUES (:slot, :tid, :cid, :sid, 'confirmed')
                """),
            {"slot": slot, "tid": trainer_id, "cid": parent, "sid": service_id},
        )
        await db_session.execute(
            text("""
                INSERT INTO client_requests (client_id, city_id, service_id, status)
                VALUES (:cid, :city, :sid, 'new')
                """),
            {"cid": parent, "city": city_id, "sid": service_id},
        )

    await _get()
    await _booking(1)

    async def _once() -> tuple[int, object]:
        invalidate_aggregates()
        statements, hook = _listen(db_session)
        try:
            response = await _get()
        finally:
            bind = db_session.sync_session.get_bind()
            if event.contains(bind, "before_cursor_execute", hook):
                event.remove(bind, "before_cursor_execute", hook)
        assert response.status_code == 200
        return len(statements), response

    n_one, one = await _once()
    for day in range(2, 6):
        await _booking(day)
    n_many, many = await _once()
    assert n_one == n_many == 26, f"SQL statements: 1 booking {n_one}, 5 bookings {n_many}"
    assert one.json()["rows"]["requests"] == {"count": 1}
    assert many.json()["rows"]["requests"] == {"count": 5}
    print(f"GET /client/me SQL statements: {n_one}")


@pytest.mark.asyncio
async def test_p95_fifty_calls(app_use_test_db, client_me_auth, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", _SECRET)
    user_id = 368_100_006
    _auth(user_id)
    samples: list[float] = []
    for _ in range(50):
        started = time.perf_counter()
        response = await _get({"X-Telegram-Init-Data": _raw(user_id, "Максим", "К")})
        samples.append(time.perf_counter() - started)
        assert response.status_code == 200
    samples.sort()
    p95 = samples[int(len(samples) * 0.95) - 1]
    print(f"GET /client/me p95 over 50 calls: {p95 * 1000:.1f} ms")
    assert p95 < 0.25
