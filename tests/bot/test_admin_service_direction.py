"""TASK-353: «Своя услуга #N» в админ-боте — кнопки направлений, «Не показывать», «Сменить»."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message
from sqlalchemy import text

from src.bot.admin_service_direction_card import direction_keyboard
from src.bot.handlers import admin_handlers
from src.infrastructure.repositories.service_direction_repository import list_directions

ADMIN = 4_242_000_353
BODY = "🆕 <b>Своя услуга #1</b>\nНазвание: прыжки"


@pytest.fixture(autouse=True)
def _env(monkeypatch, _test_db_core):
    monkeypatch.setattr(admin_handlers, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(admin_handlers, "Settings", lambda: SimpleNamespace(admin_telegram_ids=[ADMIN]))


async def _seed(db_session):
    """Своя услуга + две публичные ice-услуги (id, direction_a, direction_b)."""
    ids = []
    for name, public, vk, owner in (("T353-prygki", False, None, 1), ("T353-A", True, "ice", None), ("T353-B", True, "ice", None)):
        r = await db_session.execute(
            text(
                "INSERT INTO services (name, sort_order, vertical_key, is_public, created_by_trainer_id) "
                "VALUES (:n, 9000, :vk, :p, :o) RETURNING id"
            ),
            {"n": name, "vk": vk, "p": public, "o": None},
        )
        ids.append(int(r.scalar_one()))
    return ids


async def _make_custom(db_session, sid):
    # Своя услуга = есть автор-тренер.
    tid = (await db_session.execute(text("INSERT INTO trainers DEFAULT VALUES RETURNING id"))).scalar_one()
    await db_session.execute(text("UPDATE services SET created_by_trainer_id=:t WHERE id=:s"), {"t": tid, "s": sid})


def _cb(data, user_id=ADMIN, username="boss", html_text=BODY):
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock(id=user_id, username=username, full_name="Boss")
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.html_text = html_text
    cb.message.edit_text = AsyncMock()
    return cb


async def _row(db_session, sid):
    return (
        await db_session.execute(
            text("SELECT direction_service_id, direction_decided_at, direction_decided_by FROM services WHERE id=:s"),
            {"s": sid},
        )
    ).one()


@pytest.mark.asyncio
async def test_list_directions_is_public_ice_in_sort_order(db_session):
    own, a, b = await _seed(db_session)
    got = [d["id"] for d in await list_directions(db_session)]
    assert a in got and b in got and own not in got
    assert got.index(a) < got.index(b)
    kb = direction_keyboard(own, [{"id": a, "name": "A"}])
    assert kb.inline_keyboard[-1][0].text == "Не показывать"
    assert kb.inline_keyboard[0][0].callback_data == f"svd:{own}:{a}"


@pytest.mark.asyncio
async def test_pick_direction_links_and_edits_message(db_session):
    own, a, _ = await _seed(db_session)
    await _make_custom(db_session, own)
    cb = _cb(f"svd:{own}:{a}")
    await admin_handlers.on_service_direction(cb)

    dir_id, decided_at, by = await _row(db_session, own)
    assert dir_id == a and decided_at is not None and by == ADMIN
    sent = cb.message.edit_text.await_args
    assert sent.args[0] == BODY + "\n\n➡️ Привязано к: T353-A · @boss"
    assert sent.kwargs["reply_markup"].inline_keyboard[0][0].text == "Сменить"


@pytest.mark.asyncio
async def test_hide_sets_decided_without_direction(db_session):
    own, _, _ = await _seed(db_session)
    await _make_custom(db_session, own)
    cb = _cb(f"svd:{own}:n")
    await admin_handlers.on_service_direction(cb)

    dir_id, decided_at, _ = await _row(db_session, own)
    assert dir_id is None and decided_at is not None
    assert cb.message.edit_text.await_args.args[0].endswith("➡️ Скрыто из каталога · @boss")


@pytest.mark.asyncio
async def test_non_admin_is_rejected(db_session):
    own, a, _ = await _seed(db_session)
    await _make_custom(db_session, own)
    cb = _cb(f"svd:{own}:{a}", user_id=ADMIN + 1)
    await admin_handlers.on_service_direction(cb)

    cb.answer.assert_awaited_once_with("Нет доступа", show_alert=True)
    cb.message.edit_text.assert_not_awaited()
    assert (await _row(db_session, own))[1] is None


@pytest.mark.asyncio
async def test_repeat_press_is_idempotent(db_session):
    own, a, _ = await _seed(db_session)
    await _make_custom(db_session, own)
    await admin_handlers.on_service_direction(_cb(f"svd:{own}:{a}"))
    first = await _row(db_session, own)

    again = _cb(f"svd:{own}:{a}", html_text=BODY + "\n\n➡️ Привязано к: T353-A · @boss")
    await admin_handlers.on_service_direction(again)
    assert await _row(db_session, own) == first
    again.message.edit_text.assert_not_awaited()  # текст уже тот же
    again.answer.assert_awaited_once_with("Уже выбрано")


@pytest.mark.asyncio
async def test_change_restores_keyboard_then_new_choice_replaces_line(db_session):
    own, a, b = await _seed(db_session)
    await _make_custom(db_session, own)
    decided = BODY + "\n\n➡️ Привязано к: T353-A · @boss"
    ch = _cb(f"svd:{own}:c", html_text=decided)
    await admin_handlers.on_service_direction(ch)
    assert ch.message.edit_text.await_args.args[0] == BODY
    assert ch.message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard[-1][0].text == "Не показывать"

    await admin_handlers.on_service_direction(_cb(f"svd:{own}:{a}"))
    nxt = _cb(f"svd:{own}:{b}", html_text=decided)
    await admin_handlers.on_service_direction(nxt)
    assert (await _row(db_session, own))[0] == b
    assert nxt.message.edit_text.await_args.args[0] == BODY + "\n\n➡️ Привязано к: T353-B · @boss"


@pytest.mark.asyncio
async def test_rejects_private_target_and_non_custom_service(db_session):
    own, a, _ = await _seed(db_session)
    await _make_custom(db_session, own)
    bad = _cb(f"svd:{own}:{own}")  # цель — непубличная
    await admin_handlers.on_service_direction(bad)
    assert bad.answer.await_args.kwargs.get("show_alert") is True
    assert (await _row(db_session, own))[1] is None

    ref = _cb(f"svd:{a}:{a}")  # справочная услуга — не своя
    await admin_handlers.on_service_direction(ref)
    ref.answer.assert_awaited_once_with("Это не своя услуга тренера", show_alert=True)
