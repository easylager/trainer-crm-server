"""Список /c/: окно как в Mini App — сортировка, подписи, границы суток."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from src.application.ice_session_use_cases import create_ice_session
from src.application.selection_page import selection_description
from src.shared.copy_ru import t
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.api.test_selection_page import _og


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("Europe/Minsk")).astimezone(timezone.utc)


def _freeze_modules(monkeypatch, fixed: datetime, *modules: str) -> None:
    import datetime as dt

    class _Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return fixed.astimezone(tz)
            return fixed.replace(tzinfo=None)

    for mod in modules:
        monkeypatch.setattr(f"{mod}.datetime", _Clock)


@pytest.mark.asyncio
async def test_today_window_zero_shows_nearest_caption(app_use_test_db, db_session, monkeypatch) -> None:
    fixed = _utc(2026, 10, 7, 22, 55)
    _freeze_modules(monkeypatch, fixed, "src.application.selection_page", "src.application.arena_public_use_cases")
    name = f"Ноль {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток")
    today = fixed.astimezone(ZoneInfo("Europe/Minsk")).date()
    await create_ice_session(
        db_session,
        arena_id,
        local_date=today,
        starts_at_local="08:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    tomorrow = today + timedelta(days=1)
    await create_ice_session(
        db_session,
        arena_id,
        local_date=tomorrow,
        starts_at_local="12:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    caption = t("selection.window.empty_caption", label="Сегодня")

    async with _client() as client:
        resp = await client.get(f"/c/{slug}", params={"t": "ice", "w": "today"})

    assert resp.status_code == 200
    assert caption in resp.text
    assert "12:00" in resp.text
    assert "b-card2--off" in resp.text
    assert t("selection.window.off_nearest").strip() in resp.text
    assert _og(resp.text, "og:description") == caption


@pytest.mark.asyncio
async def test_today_window_afternoon_session_counts_as_in_window(
    app_use_test_db, db_session, monkeypatch
) -> None:
    """14:00 Минск, сеанс в 16:00 — в окне «сегодня», без подписи «сеансов нет»."""
    fixed = _utc(2026, 10, 7, 14, 0)
    _freeze_modules(monkeypatch, fixed, "src.application.selection_page", "src.application.arena_public_use_cases")
    name = f"День {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток днём")
    today = fixed.astimezone(ZoneInfo("Europe/Minsk")).date()
    await create_ice_session(
        db_session,
        arena_id,
        local_date=today,
        starts_at_local="16:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    empty_caption = t("selection.window.empty_caption", label="Сегодня")

    async with _client() as client:
        resp = await client.get(f"/c/{slug}", params={"t": "ice", "w": "today"})

    assert resp.status_code == 200
    assert empty_caption not in resp.text
    assert "16:00" in resp.text
    assert "b-card2--off" not in resp.text


@pytest.mark.asyncio
async def test_today_window_partial_shows_break(app_use_test_db, db_session, monkeypatch) -> None:
    fixed = _utc(2026, 10, 7, 14, 0)
    _freeze_modules(monkeypatch, fixed, "src.application.selection_page", "src.application.arena_public_use_cases")
    name = f"Часть {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    early_id = await _insert_arena(db_session, city_id, name="Каток Альфа")
    late_id = await _insert_arena(db_session, city_id, name="Каток Бета")
    today = fixed.astimezone(ZoneInfo("Europe/Minsk")).date()
    await create_ice_session(
        db_session,
        early_id,
        local_date=today,
        starts_at_local="16:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await create_ice_session(
        db_session,
        late_id,
        local_date=today + timedelta(days=1),
        starts_at_local="10:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        resp = await client.get(f"/c/{slug}", params={"t": "ice", "w": "today"})

    body = resp.text
    assert resp.status_code == 200
    cards = body.split('b-cards"', 1)[1].split("</section>", 1)[0]
    assert "b-window-break" in cards
    assert cards.index("16:00") < cards.index("b-window-break") < cards.index("10:00")
    # «Ближайший: завтра» и время в слоте — время не повторяется в подписи.
    assert "Ближайший: завтра</span>" in cards
    assert "Ближайший: завтра 10:00" not in cards


@pytest.mark.asyncio
async def test_today_window_rink_without_sessions_stays_a_card(app_use_test_db, db_session, monkeypatch) -> None:
    """Каток без сеансов — карточка, как в Mini App; «нет массового катания» — только для пустого списка."""
    fixed = _utc(2026, 10, 7, 12, 0)
    _freeze_modules(monkeypatch, fixed, "src.application.selection_page", "src.application.arena_public_use_cases")
    name = f"Пусто {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await _insert_arena(db_session, city_id, name="Без льда")
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)

    async with _client() as client:
        resp = await client.get(f"/c/{slug}", params={"t": "ice", "w": "today"})

    assert resp.status_code == 200
    assert "Без льда" in resp.text.split('b-cards"', 1)[1]
    assert t("selection.empty.skate.title") not in resp.text


@pytest.mark.asyncio
async def test_home_keeps_today_tab_without_shift_note(app_use_test_db, db_session, monkeypatch) -> None:
    fixed = _utc(2026, 10, 7, 22, 55)
    monkeypatch.setattr("src.application.catalog_home_page._utc_now", lambda: fixed)
    name = f"Главная {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток")
    today = fixed.astimezone(ZoneInfo("Europe/Minsk")).date()
    await create_ice_session(
        db_session,
        arena_id,
        local_date=today,
        starts_at_local="08:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await create_ice_session(
        db_session,
        arena_id,
        local_date=today + timedelta(days=1),
        starts_at_local="11:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        home = await client.get("/")

    assert home.status_code == 200
    assert "На сегодня всё — вот завтра" not in home.text
    assert 'href="/?when=tomorrow" aria-current="true"' not in home.text


@pytest.mark.asyncio
async def test_midnight_minsk_still_today_window(app_use_test_db, db_session, monkeypatch) -> None:
    fixed = _utc(2026, 10, 14, 0, 0)
    _freeze_modules(monkeypatch, fixed, "src.application.selection_page", "src.application.arena_public_use_cases")
    name = f"0000 {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    arena_id = await _insert_arena(db_session, city_id, name="Каток")
    await create_ice_session(
        db_session,
        arena_id,
        local_date=date(2026, 10, 15),
        starts_at_local="10:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    caption = t("selection.window.empty_caption", label="Сегодня")

    async with _client() as client:
        resp = await client.get(f"/c/{slug}", params={"t": "ice", "w": "today"})

    assert resp.status_code == 200
    assert caption in resp.text
    assert "10:00" in resp.text


@pytest.mark.asyncio
async def test_today_window_phone_rink_goes_below_the_break(app_use_test_db, db_session, monkeypatch) -> None:
    """inWindow в Mini App: «время по телефону» — не ответ на окно, его место под разделителем."""
    from sqlalchemy import text

    fixed = _utc(2026, 10, 7, 12, 0)
    _freeze_modules(monkeypatch, fixed, "src.application.selection_page", "src.application.arena_public_use_cases")
    name = f"Звонок {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    live_id = await _insert_arena(db_session, city_id, name="Каток с сеансом")
    phone_id = await _insert_arena(db_session, city_id, name="Каток по звонку")
    await db_session.execute(
        text("UPDATE arena_profiles SET schedule_mode = 'phone' WHERE arena_id = :id"), {"id": phone_id}
    )
    today = fixed.astimezone(ZoneInfo("Europe/Minsk")).date()
    await create_ice_session(
        db_session,
        live_id,
        local_date=today,
        starts_at_local="16:00",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=500,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        resp = await client.get(f"/c/{city_slug(name)}", params={"t": "ice", "w": "today"})

    assert resp.status_code == 200
    cards = resp.text.split('b-cards"', 1)[1].split("</section>", 1)[0]
    assert cards.index("Каток с сеансом") < cards.index("b-window-break") < cards.index("Каток по звонку")
    phone_card = cards[cards.index("Каток по звонку") :]
    assert "Сегодня нет" in phone_card
    assert "ближайший" not in phone_card.lower()
