"""TASK-330: пустая карточка катка зовёт на колокольчик — сайт и редирект в бота."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from src.application.place_links import parse_watch_start_param, watch_start_param
from tests.api.test_public_place_page import _client, _place

NB = " "
MINSK = ZoneInfo("Europe/Minsk")


async def _track(db_session, arena_id: int) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
            VALUES (:a, 'task330_test_v1', true, 'daily', now() + interval '1 day', CAST('{}' AS jsonb))
            """
        ),
        {"a": arena_id},
    )


async def _friday_waves(db_session, arena_id: int) -> None:
    today = datetime.now(MINSK).date()
    last_friday = today - timedelta(days=(today.weekday() - 4) % 7)
    for weeks in (0, 1, 2):
        day: date = last_friday - timedelta(weeks=weeks)
        moment = datetime.combine(day, time(15, 0), tzinfo=MINSK).astimezone(timezone.utc)
        if moment > datetime.now(timezone.utc):
            moment -= timedelta(weeks=3)
        await db_session.execute(
            text("INSERT INTO ice_schedule_waves (arena_id, detected_at, source) VALUES (:a, :t, 'parser')"),
            {"a": arena_id, "t": moment},
        )


@pytest.mark.asyncio
async def test_empty_tracked_rink_shows_habit_and_bell(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    await _track(db_session, place["arena_id"])
    await _friday_waves(db_session, place["arena_id"])
    await db_session.commit()

    async with _client() as client:
        html = (await client.get(place["path"])).text
    assert 'class="b-wait"' in html
    assert f"Обычно по{NB}пятницам" in html
    # Кнопка в блоке и колокольчик на обложке — одна и та же подписка.
    assert html.count(f"startapp={watch_start_param(place['arena_id'])}") == 2
    assert f"Сообщить в{NB}Telegram" in html
    assert "Одно сообщение, потом колокольчик сам выключится." in html
    # Телефон остаётся под колокольчиком.
    assert "b-call" in html


@pytest.mark.asyncio
async def test_empty_tracked_rink_without_habit_waits_without_a_day(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    await _track(db_session, place["arena_id"])
    await db_session.commit()

    async with _client() as client:
        html = (await client.get(place["path"])).text
    assert "Ждём новое расписание" in html
    assert "Обычно" not in html
    assert "b-wait__kicker" not in html


@pytest.mark.asyncio
async def test_untracked_or_phone_only_rink_keeps_old_empty_block(app_use_test_db, db_session) -> None:
    untracked = await _place(db_session)
    phone_only = await _place(db_session, schedule_mode="phone")
    await _track(db_session, phone_only["arena_id"])
    await db_session.commit()

    async with _client() as client:
        for place in (untracked, phone_only):
            html = (await client.get(place["path"])).text
            assert 'class="b-wait"' not in html, place["path"]
            # Колокольчик на обложке ставит ту же подписку через бота — на любой карточке.
            assert html.count(f"startapp={watch_start_param(place['arena_id'])}") == 1


@pytest.mark.asyncio
async def test_watch_link_opens_bot_chat_even_with_main_mini_app(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "true")
    place = await _place(db_session)
    param = watch_start_param(place["arena_id"])

    async with _client() as client:
        r = await client.get(
            "/api/public/catalog/open-telegram",
            params={"startapp": param, "surface": "place_page"},
            follow_redirects=False,
        )
        place_r = await client.get(
            "/api/public/catalog/open-telegram",
            params={"startapp": f"arena_{place['arena_id']}", "surface": "place_page"},
            follow_redirects=False,
        )
    assert r.status_code == 302
    assert r.headers["location"] == f"https://t.me/glide_test_bot?start={param}"
    # Остальные ссылки по-прежнему открывают мини-апп.
    assert place_r.headers["location"] == f"https://t.me/glide_test_bot?startapp=arena_{place['arena_id']}"
    row = (
        await db_session.execute(
            text(
                "SELECT arena_id, city_id FROM catalog_consumer_events "
                "WHERE kind = 'public_telegram_cta' AND start_param = :p ORDER BY id DESC LIMIT 1"
            ),
            {"p": param},
        )
    ).one()
    assert row == (place["arena_id"], place["city_id"])


@pytest.mark.parametrize(
    ("value", "expected"),
    [("watch_8", 8), (" watch_42 ", 42), ("watch_0", None), ("watch_", None), ("arena_8", None), (None, None),
     ("watch_1234567890", None), ("watch_8_s_1", None)],
)
def test_parse_watch_start_param(value, expected) -> None:
    assert parse_watch_start_param(value) == expected
