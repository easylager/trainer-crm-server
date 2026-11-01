"""Бот-часть «Зимних катков» (TASK-343): подписки, фото, вопрос «Были?», модерация, фоновый цикл.

Клиентский бот: deeplink-и ``wbell_<id>`` / ``wnear`` / ``wphoto_<id>``, кнопки вопроса и
«Не присылать», ``/stop_ice``, приём геопозиции и фото. Админ-бот: Принять / Отклонить /
Не та точка / Бан по фото, решения по «точки больше нет». Все колбэки админа проверяют
``admin_telegram_ids`` и идемпотентны.
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from sqlalchemy import text

from src.application import winter_asks, winter_marks, winter_photos, winter_subscriptions
from src.application.winter_links import parse_winter_start
from src.infrastructure import s3
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

logger = logging.getLogger(__name__)

client_router = Router(name="winter_client")
admin_router = Router(name="winter_admin")

_awaiting_location: set[int] = set()
LOOP_INTERVAL_SEC = 60
SEND_PAUSE_SEC = 0.05  # <= 20 сообщений в секунду


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _enabled() -> bool:
    return bool(Settings().seasonal_rinks_enabled)


def stop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Не присылать", callback_data="w:stop")]])


def ask_keyboard(ask_id: int) -> InlineKeyboardMarkup:
    b = lambda t, a: InlineKeyboardButton(text=t, callback_data=f"w:ask:{ask_id}:{a}")  # noqa: E731
    return InlineKeyboardMarkup(inline_keyboard=[
        [b("Залит", "flooded"), b("Плохой лёд", "bad"), b("Не залит", "not_flooded")],
        [b("Не был", "not_been"), b("Не спрашивать совсем", "stop")],
    ])


def admin_photo_keyboard(photo_id: int) -> InlineKeyboardMarkup:
    b = lambda t, a: InlineKeyboardButton(text=t, callback_data=f"wp:{a}:{photo_id}")  # noqa: E731
    return InlineKeyboardMarkup(inline_keyboard=[
        [b("Принять", "accept"), b("Отклонить", "reject")],
        [b("Не та точка", "wrong_place"), b("Бан автора", "ban")],
    ])


# --- клиентский бот ---------------------------------------------------------------
async def handle_winter_start(message: Message, payload: str) -> bool:
    """Вызывается из ``/start``. True — payload зимний и обработан."""
    parsed = parse_winter_start(payload)
    if parsed is None:
        return False
    if not _enabled() or not message.from_user:
        await message.answer("Раздел «Зимой» пока не открыт.")
        return True
    kind, arena_id = parsed
    tg = message.from_user.id
    async with async_session_factory() as session:
        if kind == "bell":
            try:
                out = await winter_subscriptions.subscribe_point(session, tg, int(arena_id))
                await session.commit()
            except winter_subscriptions.SubscriptionError:
                await message.answer("Такой точки уже нет в списке.")
                return True
            await message.answer(
                f"Готово. Напишу, когда зальют «{html.escape(out['name'])}». Не чаще раза в день.",
                reply_markup=stop_keyboard(),
            )
        elif kind == "near":
            _awaiting_location.add(tg)
            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Отправить, где я", request_location=True)]],
                resize_keyboard=True, one_time_keyboard=True,
            )
            await message.answer(
                "Пришлите место, где вы катаетесь: напишу, когда зальют каток в 2 км по прямой. "
                "Или напишите «город» — без радиуса пока не подпишу.",
                reply_markup=kb,
            )
        elif kind == "photo":
            ok = await winter_photos.begin_session(session, tg, int(arena_id), _now())
            await session.commit()
            if not ok:
                await message.answer("Сейчас не получится принять фото для этой точки.")
            else:
                await message.answer("Пришлите 1-3 фото точки в ближайшие 30 минут. Фото проверит человек.")
    return True


@client_router.message(Command("stop_ice"))
async def on_stop_command(message: Message) -> None:
    if not message.from_user:
        return
    async with async_session_factory() as session:
        await winter_subscriptions.unsubscribe(session, message.from_user.id)
        await session.commit()
    await message.answer("Хорошо, зимние уведомления выключены.", reply_markup=ReplyKeyboardRemove())


@client_router.callback_query(F.data == "w:stop")
async def on_stop_button(query: CallbackQuery) -> None:
    async with async_session_factory() as session:
        await winter_subscriptions.unsubscribe(session, query.from_user.id)
        await session.commit()
    await query.answer("Больше не пишу")


def _awaiting_loc(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in _awaiting_location)


async def _has_photo_session(message: Message) -> bool:
    """Не перехватываем чужие фото: обработчик срабатывает только внутри сессии «фото точки N»."""
    if not message.from_user or not _enabled():
        return False
    async with async_session_factory() as session:
        return await winter_photos.active_session_arena(session, message.from_user.id, _now()) is not None


@client_router.message(F.location, _awaiting_loc)
async def on_location(message: Message) -> None:
    tg = message.from_user.id if message.from_user else 0
    _awaiting_location.discard(tg)
    async with async_session_factory() as session:
        try:
            await winter_subscriptions.subscribe_near(session, tg, message.location.latitude, message.location.longitude)
            await session.commit()
        except winter_subscriptions.SubscriptionError:
            await message.answer("Не получил координаты. Попробуйте ещё раз.")
            return
    await message.answer("Готово. Напишу, когда зальют каток в 2 км от вас. Не чаще раза в день.",
                         reply_markup=ReplyKeyboardRemove())
    await message.answer("Выключить можно в любой момент.", reply_markup=stop_keyboard())


@client_router.callback_query(F.data.startswith("w:ask:"))
async def on_ask_answer(query: CallbackQuery) -> None:
    try:
        _, _, ask_id, answer = (query.data or "").split(":")
        ask_id_i = int(ask_id)
    except ValueError:
        await query.answer()
        return
    async with async_session_factory() as session:
        res = await winter_asks.answer_ask(session, ask_id_i, query.from_user.id, answer, _now())
        await session.commit()
    toast = {"ok": "Спасибо, учёл", "not_been": "Понял, по этой точке больше не спрошу", "stopped": "Больше не спрашиваю",
             "already": "Уже отвечено"}.get(res, "Не получилось")
    await query.answer(toast)
    try:
        await query.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    except TelegramBadRequest:
        pass


@client_router.message(F.photo | F.document, _has_photo_session)
async def on_photo(message: Message, bot: Bot) -> None:
    tg = message.from_user.id if message.from_user else 0
    if message.document and not (message.document.mime_type or "").startswith("image/"):
        await message.answer("Пока только фото.")
        return
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id  # type: ignore[union-attr]
    buf = await bot.download(file_id)
    body = buf.read() if buf else b""
    async with async_session_factory() as session:
        try:
            pid = await winter_photos.add_photo(session, tg, body, _now())
            await session.commit()
        except winter_photos.PhotoError as exc:
            await message.answer({
                "limit": "На сегодня хватит фото (до 3 в сутки).", "duplicate": "Такое фото уже есть.",
                "too_large": "Файл слишком большой (до 10 МБ).", "not_image": "Не похоже на фото.",
                "no_session": "Сессия закончилась. Откройте точку и нажмите «Добавить фото» ещё раз.",
            }.get(exc.code, "Не получилось принять фото."))
            return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Лёд есть", callback_data=f"w:ice:{pid}:1"),
        InlineKeyboardButton(text="Льда нет", callback_data=f"w:ice:{pid}:0"),
    ]])
    await message.answer("Принял. Лёд на фото есть?", reply_markup=kb)
    await notify_admins_photo(pid)


@client_router.callback_query(F.data.startswith("w:ice:"))
async def on_ice_claim(query: CallbackQuery) -> None:
    try:
        _, _, pid, claim = (query.data or "").split(":")
    except ValueError:
        await query.answer()
        return
    async with async_session_factory() as session:
        ok = await winter_photos.set_ice_claim(session, int(pid), query.from_user.id, claim == "1", _now())
        await session.commit()
    await query.answer("Спасибо, фото уйдёт на проверку" if ok else "Уже учтено")
    try:
        await query.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    except TelegramBadRequest:
        pass


# --- админ-бот --------------------------------------------------------------------
def _is_admin(user_id: int | None) -> bool:
    return bool(user_id) and user_id in (Settings().admin_telegram_ids or [])


async def notify_admins_photo(photo_id: int) -> None:
    settings = Settings()
    token, admins = settings.telegram_bot_token_admin, list(dict.fromkeys(settings.admin_telegram_ids or []))
    if not token or not admins:
        return
    async with async_session_factory() as session:
        row = (await session.execute(
            text("SELECT p.storage_key, p.ice_claim, a.name, c.name AS city FROM seasonal_rink_photos p "
                 "JOIN arenas a ON a.id=p.arena_id JOIN cities c ON c.id=a.city_id WHERE p.id=:i"), {"i": photo_id})).first()
    if row is None:
        return
    found = s3.get_file(row.storage_key, allowed_prefixes=(s3.WINTER_PREFIX,))
    bot = Bot(token=token)
    try:
        for chat in admins:
            try:
                caption = f"Фото точки: {row.city}, {row.name}"
                if found:
                    await bot.send_photo(chat, BufferedInputFile(found[0], "p.jpg"), caption=caption,
                                         reply_markup=admin_photo_keyboard(photo_id))
                else:
                    await bot.send_message(chat, caption, reply_markup=admin_photo_keyboard(photo_id))
            except Exception:  # noqa: BLE001
                logger.exception("winter photo notify failed chat=%s", chat)
    finally:
        await bot.session.close()


@admin_router.callback_query(F.data.startswith("wp:"))
async def on_photo_decision(query: CallbackQuery) -> None:
    if not _is_admin(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    try:
        _, decision, pid = (query.data or "").split(":")
        photo_id = int(pid)
    except ValueError:
        await query.answer()
        return
    async with async_session_factory() as session:
        if decision == "ban":
            author = (await session.execute(text("SELECT author_telegram_id FROM seasonal_rink_photos WHERE id=:i"), {"i": photo_id})).scalar_one_or_none()
            if author:
                await winter_photos.ban_author(session, int(author))
            res = await winter_photos.decide(session, photo_id, "reject", query.from_user.id, _now())
        else:
            res = await winter_photos.decide(session, photo_id, decision, query.from_user.id, _now())
        await session.commit()
    await query.answer({"accepted": "Принято", "rejected": "Отклонено", "wrong_place": "Не та точка", "already": "Уже разобрано"}.get(res, res))
    try:
        await query.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    except TelegramBadRequest:
        pass


@admin_router.callback_query(F.data.startswith("wg:"))
async def on_gone_decision(query: CallbackQuery) -> None:
    if not _is_admin(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return
    try:
        _, decision, aid = (query.data or "").split(":")
        arena_id = int(aid)
    except ValueError:
        await query.answer()
        return
    async with async_session_factory() as session:
        await winter_marks.resolve_gone(session, arena_id, point_exists=(decision == "keep"), admin_id=query.from_user.id, now=_now())
        await session.commit()
    await query.answer("Готово")
    try:
        await query.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    except TelegramBadRequest:
        pass


def gone_keyboard(arena_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Точка есть", callback_data=f"wg:keep:{arena_id}"),
        InlineKeyboardButton(text="Точки нет, скрыть", callback_data=f"wg:hide:{arena_id}"),
    ]])


# --- фоновый цикл -------------------------------------------------------------------
async def make_sender(bot: Bot):
    async def send(tg: int, body: str, arena_ids: list[int]) -> str:
        await asyncio.sleep(SEND_PAUSE_SEC)
        for attempt in range(3):
            try:
                await bot.send_message(tg, body, reply_markup=stop_keyboard())
                return "ok"
            except TelegramForbiddenError:
                return "dead"
            except TelegramRetryAfter as exc:
                await asyncio.sleep(min(exc.retry_after, 30))
            except TelegramBadRequest as exc:
                return "dead" if "chat not found" in str(exc).lower() else "retry"
            except Exception:  # noqa: BLE001
                logger.exception("winter send failed tg=%s", tg)
                return "retry"
        return "retry"

    return send


async def run_winter_cycle(bot: Bot, now: datetime | None = None) -> dict:
    now = now or _now()
    out: dict = {}
    async with async_session_factory() as session:
        out["stale"] = await winter_marks.recompute_stale(session, now)
        out["queued"] = await winter_subscriptions.fan_out_events(session, now)
        out["ignored"] = await winter_asks.expire_ignored(session, now)
        await session.commit()
    async with async_session_factory() as session:
        out["delivery"] = await winter_subscriptions.deliver_pending(session, now, await make_sender(bot))
        await session.commit()
    async with async_session_factory() as session:
        asks = await winter_asks.due_asks(session, now)
        await session.commit()
    for a in asks:
        try:
            await bot.send_message(
                a["telegram_id"],
                f"Вы собирались на «{html.escape(a['name'])}». Были? Как лёд?",
                reply_markup=ask_keyboard(a["ask_id"]),
            )
        except TelegramForbiddenError:
            async with async_session_factory() as session:
                await winter_subscriptions.unsubscribe(session, a["telegram_id"])
                await session.commit()
        except Exception:  # noqa: BLE001
            logger.exception("winter ask send failed")
    return out


async def run_winter_loop(client_bot: Bot) -> None:
    while True:
        await asyncio.sleep(LOOP_INTERVAL_SEC)
        try:
            if _enabled():
                await run_winter_cycle(client_bot)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001
            logger.exception("Winter loop: %s", exc)
