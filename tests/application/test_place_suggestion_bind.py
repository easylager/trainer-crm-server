"""PDEC-028 Task 8: автор заявки с сайта привязывается к Telegram по ``/start sg_<token>``."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from src.application import place_suggestion_use_cases as uc
from src.application.place_suggestion_use_cases import (
    bind_suggestion_author,
    create_place_suggestion,
    parse_suggest_start,
)
from src.bot import messages as msg
from src.bot.handlers import client_handlers


async def _noop(*_a, **_kw):
    return None


@pytest.fixture(autouse=True)
def _no_telegram(monkeypatch):
    """Никаких реальных сообщений в Telegram: .env держит боевые токены ботов."""
    monkeypatch.setattr(uc, "notify_admins_new_place_suggestion", _noop)


def _tid() -> int:
    return 7_500_000_000 + (uuid.uuid4().int % 100_000_000)


async def _suggest(db_session, *, author=None, name="Каток-привязка") -> dict:
    return await create_place_suggestion(
        db_session, source="site" if author is None else "miniapp", kind="ice", city_id=None,
        new_city={"name": f"Пса-Привязка-{uuid.uuid4().hex[:6]}", "country": "BY"}, name=name,
        address=None, details={}, contact=None, author_telegram_id=author, client_ip=None,
    )


def test_parse_suggest_start():
    assert parse_suggest_start("sg_AbC-12_xyz0") == "AbC-12_xyz0"
    assert parse_suggest_start("sg_") is None
    assert parse_suggest_start("sg_bad token") is None
    assert parse_suggest_start("watch_12") is None
    assert parse_suggest_start(None) is None


@pytest.mark.asyncio
async def test_bind_once_then_token_is_burned(db_session):
    res = await _suggest(db_session)
    tid = _tid()
    bound = await bind_suggestion_author(db_session, res["bind_token"], tid)
    assert bound == {"id": res["id"], "name": "Каток-привязка", "status": "new"}
    row = (await db_session.execute(
        text("SELECT author_telegram_id, bind_token FROM place_suggestions WHERE id=:id"), {"id": res["id"]}
    )).one()
    assert int(row[0]) == tid and row[1] is None
    assert await bind_suggestion_author(db_session, res["bind_token"], _tid()) is None


@pytest.mark.asyncio
async def test_miniapp_author_is_not_rebound(db_session):
    author = _tid()
    res = await _suggest(db_session, author=author)
    assert res["bind_token"] is None
    # Даже если токен каким-то образом оказался в строке — автор из Mini App не перезаписывается.
    await db_session.execute(text("UPDATE place_suggestions SET bind_token='forged_token_1' WHERE id=:id"),
                             {"id": res["id"]})
    await db_session.commit()
    assert await bind_suggestion_author(db_session, "forged_token_1", _tid()) is None
    got = (await db_session.execute(
        text("SELECT author_telegram_id FROM place_suggestions WHERE id=:id"), {"id": res["id"]}
    )).scalar()
    assert int(got) == author


def _message(payload: str, tid: int) -> MagicMock:
    message = MagicMock()
    message.text = f"/start {payload}"
    message.from_user = MagicMock(id=tid, username="suggest_user")
    message.answer = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_bot_start_sg_thanks_then_link_used(app_use_test_db, db_session, _test_db_core, monkeypatch):
    monkeypatch.setattr(client_handlers, "async_session_factory", _test_db_core["factory"])
    res = await _suggest(db_session, name="Каток <Север>")
    tid = _tid()

    first = _message(f"sg_{res['bind_token']}", tid)
    await client_handlers.cmd_start(first)
    first.answer.assert_awaited_once()
    assert first.answer.await_args.args[0] == msg.CLIENT_SUGGEST_BOUND.format(
        id=res["id"], name="Каток &lt;Север&gt;"
    )

    second = _message(f"sg_{res['bind_token']}", tid)
    await client_handlers.cmd_start(second)
    second.answer.assert_awaited_once()
    assert second.answer.await_args.args[0] == msg.CLIENT_SUGGEST_LINK_USED
