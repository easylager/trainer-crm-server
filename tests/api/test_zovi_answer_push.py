"""Ответ на открытку доходит до того, кто позвал: пуш бота и страница статуса."""

from __future__ import annotations

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendPhoto
from sqlalchemy import text

from src.application.ice_invites import answer_invite_result, create_invite
from src.application.zovi_answer_push import (
    MAX_ATTEMPTS,
    answer_push_text,
    deliver_invite_answer_push,
    process_invite_answer_pushes,
)
from tests.api.test_ice_invites import _at, _client, _headers, _insert_session, _place

_TG_ID = 777001


class _FakeBot:
    def __init__(self, *, forbid: bool = False, photo_fails: bool = False) -> None:
        self.photos: list[dict] = []
        self.texts: list[dict] = []
        self.forbid = forbid
        self.photo_fails = photo_fails

    async def send_photo(self, **kwargs):
        if self.forbid:
            raise TelegramForbiddenError(method=SendPhoto(chat_id=1, photo="x"), message="Forbidden: bot was blocked")
        if self.photo_fails:
            raise RuntimeError("upload failed")
        self.photos.append(kwargs)

    async def send_message(self, **kwargs):
        self.texts.append(kwargs)


async def _invite(
    db_session, *, telegram_id: int | None = _TG_ID, to_name: str | None = "Лера", actor: str | None = "creator-hash"
):
    place = await _place(db_session)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=2))
    created = await create_invite(
        db_session,
        session_id=session_id,
        to_name=to_name,
        from_name="Макс",
        show_price=False,
        parent_code=None,
        creator_actor_hash=actor,
        creator_telegram_id=telegram_id,
    )
    return created, place


async def _answer(
    db_session, code: str, *, device: str = "device-token-push1", actor: str | None = "friend-hash"
) -> int:
    _payload, inserted, answer_id = await answer_invite_result(
        db_session,
        code,
        device_token=device,
        tries=2,
        resist_ms=5400,
        falls=0,
        tricked=True,
        responder_actor_hash=actor,
    )
    assert inserted
    return answer_id


async def _notified(db_session, answer_id: int):
    return (
        await db_session.execute(
            text("SELECT notified_at, notify_attempts FROM ice_invite_answers WHERE id = :id"), {"id": answer_id}
        )
    ).one()


def test_push_text_names_the_answer_without_gender() -> None:
    text_ = answer_push_text(
        to_name="Лера",
        kind="public_skate",
        day="Вт, 13 окт",
        time="11:00",
        arena_name="ТЦ DiaMond city",
        tries=2,
        resist_ms=5400,
        falls=0,
        tricked=True,
        nth=1,
    )
    assert text_.startswith("<b>Лера: ДА!</b>")
    assert "Каток · Вт, 13 окт, 11:00" in text_
    assert "ТЦ DiaMond city" in text_
    assert "Держались 5 с · отказов 2 · падений 0" in text_
    assert "сказала" not in text_ and "сказал " not in text_


def test_push_text_for_company_and_hockey() -> None:
    first = answer_push_text(
        to_name=None,
        kind="hockey_practice",
        day="Сб, 17 окт",
        time="19:00",
        arena_name="Чижовка",
        tries=0,
        resist_ms=0,
        falls=0,
        tricked=False,
        nth=1,
    )
    assert first.startswith("<b>На твою открытку ответили «ДА»!</b>")
    assert "Хоккей · Сб, 17 окт, 19:00" in first
    third = answer_push_text(
        to_name=None,
        kind="public_skate",
        day="",
        time="19:00",
        arena_name="<Каток>",
        tries=0,
        resist_ms=0,
        falls=0,
        tricked=False,
        nth=3,
    )
    assert "уже 3-е" in third
    assert "&lt;Каток&gt;" in third


@pytest.mark.asyncio
async def test_answer_reaches_creator_once(app_use_test_db, db_session) -> None:
    created, _ = await _invite(db_session)
    answer_id = await _answer(db_session, created["code"])
    bot = _FakeBot()
    assert await deliver_invite_answer_push(db_session, bot, answer_id) is True
    assert len(bot.photos) == 1
    sent = bot.photos[0]
    assert sent["chat_id"] == _TG_ID
    assert sent["caption"].startswith("<b>Лера: ДА!</b>")
    notified_at, attempts = await _notified(db_session, answer_id)
    assert notified_at is not None and attempts == 1
    # Цикл бота и повторный вызов не шлют второй раз.
    assert await deliver_invite_answer_push(db_session, bot, answer_id) is False
    assert await process_invite_answer_pushes(db_session, bot) == 0
    assert len(bot.photos) == 1


@pytest.mark.asyncio
async def test_no_telegram_creator_no_push(app_use_test_db, db_session) -> None:
    created, _ = await _invite(db_session, telegram_id=None)
    answer_id = await _answer(db_session, created["code"])
    bot = _FakeBot()
    assert await deliver_invite_answer_push(db_session, bot, answer_id) is False
    assert bot.photos == [] and bot.texts == []


@pytest.mark.asyncio
async def test_creator_answering_own_card_is_not_news(app_use_test_db, db_session) -> None:
    created, _ = await _invite(db_session, actor="same-person")
    answer_id = await _answer(db_session, created["code"], actor="same-person")
    bot = _FakeBot()
    assert await deliver_invite_answer_push(db_session, bot, answer_id) is False
    assert bot.photos == []
    notified_at, _ = await _notified(db_session, answer_id)
    assert notified_at is not None


@pytest.mark.asyncio
async def test_blocked_bot_gives_up_and_broken_photo_falls_back_to_text(app_use_test_db, db_session) -> None:
    created, _ = await _invite(db_session)
    blocked = await _answer(db_session, created["code"], device="device-token-push2")
    assert await deliver_invite_answer_push(db_session, _FakeBot(forbid=True), blocked) is False
    notified_at, attempts = await _notified(db_session, blocked)
    assert notified_at is None and attempts == MAX_ATTEMPTS

    other, _ = await _invite(db_session)
    answer_id = await _answer(db_session, other["code"], device="device-token-push3")
    bot = _FakeBot(photo_fails=True)
    assert await deliver_invite_answer_push(db_session, bot, answer_id) is True
    assert bot.texts and bot.texts[0]["caption" if "caption" in bot.texts[0] else "text"].startswith("<b>Лера: ДА!</b>")


@pytest.mark.asyncio
async def test_sweep_delivers_what_the_request_missed(app_use_test_db, db_session) -> None:
    created, _ = await _invite(db_session)
    answer_id = await _answer(db_session, created["code"], device="device-token-push4")
    bot = _FakeBot()
    assert await process_invite_answer_pushes(db_session, bot) >= 1
    notified_at, _ = await _notified(db_session, answer_id)
    assert notified_at is not None


@pytest.mark.asyncio
async def test_answer_route_schedules_the_push(app_use_test_db, db_session, monkeypatch) -> None:
    scheduled: list[int] = []

    async def _record(answer_id: int) -> None:
        scheduled.append(answer_id)

    monkeypatch.setattr("src.api.routes.public_invites.push_answer_soon", _record)
    created, _ = await _invite(db_session)
    async with _client() as client:
        res = await client.post(
            f"/api/public/invites/{created['code']}/answer",
            json={"device_token": "device-token-route1", "tries": 1, "resist_ms": 1000, "falls": 0, "tricked": False},
            headers=_headers(),
        )
        again = await client.post(
            f"/api/public/invites/{created['code']}/answer",
            json={"device_token": "device-token-route1", "tries": 1, "resist_ms": 1000, "falls": 0, "tricked": False},
            headers=_headers(),
        )
    assert res.status_code == 200 and again.status_code == 200
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_card_says_whether_creator_gets_a_push(app_use_test_db, db_session) -> None:
    with_tg, _ = await _invite(db_session)
    without, _ = await _invite(db_session, telegram_id=None)
    async with _client() as client:
        a = (await client.get(f"/api/public/invites/{with_tg['code']}", headers=_headers())).json()
        b = (await client.get(f"/api/public/invites/{without['code']}", headers=_headers())).json()
    assert a["creator_notified"] is True
    assert b["creator_notified"] is False
    assert "creator_telegram_id" not in a


@pytest.mark.asyncio
async def test_status_page_shows_the_answer_to_the_key_holder(app_use_test_db, db_session) -> None:
    created, _ = await _invite(db_session, telegram_id=None)
    async with _client() as client:
        waiting = await client.get(created["status_path"])
        wrong = await client.get(f"/zovi/{created['code']}/s/not-the-key")
        await _answer(db_session, created["code"], device="device-token-status1")
        answered = await client.get(created["status_path"])
    assert waiting.status_code == 200
    assert "Ещё не открыли" in waiting.text
    assert 'http-equiv="refresh"' in waiting.text
    assert "noindex" in waiting.text
    assert wrong.status_code == 404
    assert answered.status_code == 200
    assert "Лера</span>: ДА!" in answered.text
    assert "Держались 5 с · отказов 2 · падений 0" in answered.text
    assert 'http-equiv="refresh"' not in answered.text
    assert 'id="yesBtn"' not in answered.text


@pytest.mark.asyncio
async def test_background_push_never_raises_and_skips_bot_without_telegram(
    app_use_test_db, db_session, monkeypatch
) -> None:
    from src.application import zovi_answer_push

    built: list[str] = []

    class _BrokenBot:
        def __init__(self, token, **_kw):
            built.append(token)
            raise ValueError("Token is invalid!")

    monkeypatch.setattr(zovi_answer_push, "Bot", _BrokenBot)
    no_tg, _ = await _invite(db_session, telegram_id=None)
    plain = await _answer(db_session, no_tg["code"], device="device-token-bg1")
    await zovi_answer_push.push_answer_soon(plain)
    assert built == []

    with_tg, _ = await _invite(db_session)
    pushed = await _answer(db_session, with_tg["code"], device="device-token-bg2")
    await zovi_answer_push.push_answer_soon(pushed)  # не бросает, хотя бот не создаётся
    assert len(built) == 1
