"""TASK-275: ошибки стиля B с ревью 13.10 — даты, оговорки, вечерний счётчик, городские номера."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.arena_public_use_cases import _date_label
from src.application.catalog_home_page import _today_done_text
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from src.application.ice_session_use_cases import create_ice_session
from src.application.selection_page import selection_description
from src.shared.public_display import format_phone_display
from tests.api.test_public_arenas import _insert_arena, _insert_city

_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def test_feed_date_label_never_shows_iso() -> None:
    today = date(2026, 10, 13)  # вторник
    assert _date_label(today, today) == "Сегодня"
    assert _date_label(today + timedelta(days=1), today) == "Завтра"
    assert _date_label(date(2026, 10, 16), today) == "Пт"


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("+375291234567", "+375 29 123-45-67"),
        ("+375173001122", "+375 17 300-11-22"),
        ("+375162123456", "+375 162 12-34-56"),
        ("+375164236545", "+375 1642 3-65-45"),
        ("+375233412345", "+375 2334 1-23-45"),
        # Неизвестный код не делим: неверная группировка хуже слитной.
        ("+375233345259", "+375 233345259"),
    ],
)
def test_landline_numbers_group_by_known_city_code(raw: str, shown: str) -> None:
    assert format_phone_display(raw) == shown


def test_service_header_drops_zero_open_now() -> None:
    view = {"svc": "sharpening", "total": 11, "open_now_count": 0}
    line = selection_description(view)
    assert "0 открыт" not in line
    assert line.startswith("11 ")
    assert "3 открыты сейчас" in selection_description({**view, "open_now_count": 3})


def test_home_counter_after_last_session_points_to_tomorrow() -> None:
    cities = [
        {"next_skate": {"day_label": "завтра"}},
        {"next_skate": {"day_label": "завтра"}},
        {"next_skate": {"day_label": "сб"}},
        {"next_skate": None},
    ]
    assert _today_done_text(cities) == "Сегодня сеансов нет, завтра лёд в 2 городах"
    assert _today_done_text([{"next_skate": {"day_label": "сб"}}]) == "Сегодня сеансов нет"


@pytest.mark.asyncio
async def test_list_with_empty_window_shows_nearest_as_tickets(app_use_test_db, db_session) -> None:
    """Окно «сегодня» пусто: ближайшие сеансы — билетами, без ISO-дат и «уточняется»."""
    name = f"Окно {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    later = await _insert_arena(db_session, city_id, name="Каток через три дня")
    await _insert_arena(db_session, city_id, name="Каток без расписания")
    day = datetime.now(ZoneInfo("Europe/Minsk")).date() + timedelta(days=3)
    await create_ice_session(
        db_session,
        later,
        local_date=day,
        starts_at_local="09:30",
        duration_minutes=60,
        kind="public_skate",
        price_adult_minor=1100,
        price_child_minor=None,
        price_rental_minor=None,
    )
    await db_session.execute(text("SELECT 1"))
    await db_session.commit()
    invalidate_public_city_cache()

    async with _client() as client:
        resp = await client.get(f"/c/{city_slug(name)}?t=ice&w=today")
    assert resp.status_code == 200
    body = resp.text
    assert "b-slot__time" in body and "9:30" in body
    assert not _ISO_DATE.search(re.sub(r'(href|content|datetime)="[^"]*"', "", body))
    assert "уточняется" not in body
    assert "На сегодня всё" in body
    assert "сеансов нет — показываем ближайшие" not in body
    assert "Каток через три дня" in body
