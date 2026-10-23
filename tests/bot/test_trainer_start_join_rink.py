"""
TASK-323: тренер пришёл с лендинга катка — ``/join?arena=`` → ``/start link_<token>_arena_<id>``.

Бот снимает хвост катка до разбора токена, привязывает тренера по токену и отмечает ему каток:
онбординг (quick-setup) открывается с ним, а не с пустым списком.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from src.application.trainer_link_token_use_cases import issue_landing_trainer_link_token
from src.bot.handlers import trainer_handlers
from src.infrastructure.db import async_session_factory


async def _active_rink() -> int:
    async with async_session_factory() as s:
        r = await s.execute(
            text("INSERT INTO cities (name, is_active) VALUES (:n, true) RETURNING id"),
            {"n": f"Катковск {uuid.uuid4().hex[:6]}"},
        )
        city_id = int(r.scalar())
        r = await s.execute(
            text("INSERT INTO arenas (city_id, name, is_active) VALUES (:c, 'Каток с лендинга', true) RETURNING id"),
            {"c": city_id},
        )
        arena_id = int(r.scalar())
        await s.commit()
    return arena_id


@pytest.mark.asyncio
async def test_start_from_rink_landing_links_trainer_and_picks_the_rink(monkeypatch) -> None:
    arena_id = await _active_rink()
    async with async_session_factory() as s:
        token = str((await issue_landing_trainer_link_token(s))["token"])

    monkeypatch.setattr(trainer_handlers, "_trainer_typing", AsyncMock())
    monkeypatch.setattr(trainer_handlers, "_seed_trainer_avatar_bg", AsyncMock())
    monkeypatch.setattr(trainer_handlers, "sync_trainer_linked_chat_menu", AsyncMock())
    monkeypatch.setattr(
        "src.application.trainer_events_notify.notify_admins_trainer_first_login", AsyncMock()
    )
    tg_id = 5_900_000_000 + (uuid.uuid4().int % 90_000_000)
    message = SimpleNamespace(
        text=f"/start link_{token}_arena_{arena_id}",
        from_user=SimpleNamespace(id=tg_id, username=None, first_name="Анна", last_name="Лёд"),
        chat=SimpleNamespace(id=tg_id),
        bot=SimpleNamespace(),
        answer=AsyncMock(),
        answer_photo=AsyncMock(),
    )

    await trainer_handlers.cmd_start(message)

    async with async_session_factory() as s:
        r = await s.execute(
            text("SELECT id, primary_arena_id FROM trainers WHERE telegram_id = :tg"),
            {"tg": tg_id},
        )
        row = r.fetchone()
        assert row is not None, "start-параметр с хвостом катка не привязал тренера"
        trainer_id, primary = int(row[0]), row[1]
        linked = (
            await s.execute(
                text("SELECT arena_id FROM trainer_arenas WHERE trainer_id = :t"), {"t": trainer_id}
            )
        ).scalars().all()
    assert [int(a) for a in linked] == [arena_id]
    assert primary == arena_id
    # Первый запуск: одно предложение с кнопкой онбординга, как и без катка.
    assert message.answer_photo.await_count + message.answer.await_count >= 1
