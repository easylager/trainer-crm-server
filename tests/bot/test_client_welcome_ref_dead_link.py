"""
`/start welcome_ref_<id>` с мёртвым trainer_id не должен роняться необработанным
исключением: клиент получает внятный ответ, сигнал спроса по несуществующему
тренеру не пишется (FK на `trainers` его всё равно отвергнет).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from src.bot import messages as msg
from src.bot.handlers import client_handlers


class _DummySessionFactory:
    """Подменяет async_session_factory(): отдаёт болванку сессии, в БД не ходит."""

    def __call__(self) -> "_DummySessionFactory":
        return self

    async def __aenter__(self) -> MagicMock:
        return MagicMock()

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _message(payload: str) -> MagicMock:
    message = MagicMock()
    message.text = f"/start {payload}"
    message.from_user = MagicMock(id=1304982166, username="owner")
    message.answer = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_welcome_ref_missing_trainer_answers_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client_handlers, "async_session_factory", _DummySessionFactory())
    monkeypatch.setattr(
        client_handlers,
        "client_invite_needs_registration_form",
        AsyncMock(return_value=False),
    )
    # Тренера с таким id нет — ровно то, что приходит по устаревшей ссылке.
    monkeypatch.setattr(client_handlers, "get_trainer", AsyncMock(return_value=None))
    # Если обработчик всё-таки попытается записать сигнал, он получит ту же
    # IntegrityError, что и в проде, — тест должен покраснеть, а не пройти.
    record = AsyncMock(
        side_effect=IntegrityError("INSERT", {}, Exception("FK trainer_id"))
    )
    monkeypatch.setattr(client_handlers, "record_profile_view_commit", record)
    bind = AsyncMock(return_value=(None, None))
    monkeypatch.setattr(client_handlers, "_bind_client_invite_trainer_context", bind)

    message = _message("welcome_ref_3222")

    await client_handlers.cmd_start(message)

    record.assert_not_awaited()
    bind.assert_not_awaited()
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == msg.CLIENT_ERROR_TRAINER_NOT_FOUND
