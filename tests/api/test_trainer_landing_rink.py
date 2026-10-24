"""Лендинг под каток /trainers/{город}/{каток} (TASK-321): ссылка для холодного сообщения тренеру."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.application.trainer_landing_page import clear_rink_picker_cache_for_tests, trainer_rink_path
from tests.api.test_public_arenas import _add_future_session
from tests.api.test_public_place_page import _place


@pytest.fixture(autouse=True)
def _no_rink_cache():
    clear_rink_picker_cache_for_tests()
    yield
    clear_rink_picker_cache_for_tests()


def _client(**kw) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", **kw)


def test_trainer_rink_path_mirrors_place_path():
    assert trainer_rink_path(city_name="Минск", slug="zamok") == "/trainers/minsk/zamok"


@pytest.mark.asyncio
async def test_rink_landing_shows_that_rink(db_session):
    place = await _place(db_session, name="Каток Проверочный")
    await _add_future_session(db_session, place["arena_id"], days_ahead=1, starts_at_local="19:30")
    await db_session.commit()
    path = "/trainers" + place["path"][len("/p"):]
    async with _client() as client:
        resp = await client.get(path)
        head = await client.head(path)
    assert resp.status_code == 200
    body = resp.text
    assert "Тренерам катка «Каток Проверочный»" in body
    assert "<title>Тренерам катка «Каток Проверочный» — Glide</title>" in body
    assert '<meta name="robots" content="noindex, follow">' in body
    assert 'rel="canonical"' not in body  # noindex без canonical на /trainers
    # Превью ссылки — картинка этого катка: в мессенджере тренер видит свой лёд.
    assert f'{place["path"]}/og.png"' in body
    assert "Научат здесь же" in body and "Так ваш каток выглядит в Glide" in body
    assert "Станьте первым тренером здесь" in body  # на катке пока нет опубликованных тренеров
    # Сеанс — с концом, а окно в пустой карточке — пример после него, без выдуманного тренера.
    assert "19:30–" in body and "Ваше окно после катания — например, в" in body
    assert f'href="/join?arena={place["arena_id"]}"' in body
    assert head.status_code == 200


@pytest.mark.asyncio
async def test_unknown_rink_redirects_to_trainers(db_session):
    async with _client(follow_redirects=False) as client:
        resp = await client.get("/trainers/nowhere/no-such-rink")
    assert resp.status_code == 302 and resp.headers["location"] == "/trainers"


@pytest.mark.asyncio
async def test_russian_rink_gets_no_trainer_landing(db_session, monkeypatch):
    """Предложение тренерам — белорусское (BYN): каток Питера открыт в каталоге, но лендинга нет."""
    monkeypatch.setenv("ICE_DISCOVERY_COUNTRIES", "BY,RU")
    place = await _place(db_session, name="Каток Питерский")
    await db_session.execute(text("UPDATE cities SET country = 'RU' WHERE id = :id"), {"id": place["city_id"]})
    await db_session.commit()
    path = "/trainers" + place["path"][len("/p"):]
    async with _client(follow_redirects=False) as client:
        place_resp = await client.get(place["path"])
        resp = await client.get(path)
        home = await client.get("/trainers")
    assert place_resp.status_code == 200  # сам каток публичен — отсекает именно лендинг
    assert resp.status_code == 302 and resp.headers["location"] == "/trainers"
    assert "Каток Питерский" not in home.text


def test_window_label_prefers_the_window_after_the_session():
    from src.application.trainer_landing_page import _example_window, _window_label

    slot = {"local_date": "2026-10-24", "ends_hhmm": "11:45"}
    wins = [
        {"starts_at": "2026-10-24T09:00:00+03:00", "time": "9:00", "day": "сегодня"},
        {"starts_at": "2026-10-24T12:00:00+03:00", "time": "12:00", "day": "сегодня"},
    ]
    assert _window_label(wins, slot) == "свободно в 12:00 — после катания"
    assert _window_label(wins[:1], slot) == "свободно: сегодня, 9:00"
    assert _window_label([], slot) == ""
    assert _example_window(slot) == "12:00"
    assert _example_window({"ends_hhmm": "12:00"}) == "12:00"
    assert _example_window(None) == ""
