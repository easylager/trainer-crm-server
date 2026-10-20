"""Ответ на открытку доходит до того, кто позвал (TASK-235, ядро).

Открытку собрали в Mini App — у приглашения есть ``creator_telegram_id``. Когда получатель
говорит «да», клиентский бот присылает создателю билет картинкой и подпись: кто ответил,
на какой сеанс, сколько держались. Без Telegram ответ виден на странице статуса.

Доставка — захват строки ответа (``notify_claimed_at``), потом ``notified_at``:

* сразу после ответа — фоновой задачей запроса (:func:`push_answer_soon`);
* если не вышло (сеть, деплой) — из цикла уведомлений бота (:func:`process_invite_answer_pushes`).

Захват протухает через ``CLAIM_TTL``, попыток не больше ``MAX_ATTEMPTS``. Бот заблокирован
(403) — попытки заканчиваются сразу: повтор ничего не изменит.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import quote

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_invites import InviteRejected, get_invite
from src.application.png_render_cache import render_png_cached
from src.application.zovi_card_image import render_zovi_ticket
from src.application.zovi_card_page import day_short, image_version, verdict

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
CLAIM_TTL = timedelta(minutes=2)
#: Старее — не шлём: «Лера: ДА!» через неделю после сеанса только путает.
SWEEP_WINDOW = timedelta(days=2)
SWEEP_LIMIT = 20

_CLAIM = """
UPDATE ice_invite_answers AS a
SET notify_claimed_at = :now, notify_attempts = a.notify_attempts + 1
FROM ice_invites AS i
WHERE a.id = :answer_id
  AND i.id = a.invite_id
  AND i.creator_telegram_id IS NOT NULL
  AND a.notified_at IS NULL
  AND a.notify_attempts < :max_attempts
  AND (a.notify_claimed_at IS NULL OR a.notify_claimed_at < :stale)
RETURNING a.id
"""

_LOAD = """
SELECT
    a.id, a.tries, a.resist_ms, a.falls, a.tricked, a.responder_actor_hash,
    i.code, i.creator_telegram_id, i.creator_actor_hash,
    (SELECT count(*) FROM ice_invite_answers x WHERE x.invite_id = a.invite_id AND x.id <= a.id) AS nth
FROM ice_invite_answers a
JOIN ice_invites i ON i.id = a.invite_id
WHERE a.id = :answer_id
"""

_PENDING = """
SELECT a.id
FROM ice_invite_answers a
JOIN ice_invites i ON i.id = a.invite_id
WHERE a.notified_at IS NULL
  AND i.creator_telegram_id IS NOT NULL
  AND a.notify_attempts < :max_attempts
  AND (a.notify_claimed_at IS NULL OR a.notify_claimed_at < :stale)
  AND a.answered_at > :since
ORDER BY a.answered_at
LIMIT :limit
"""


def _nth_word(n: int) -> str:
    return f"{n}-е"


def answer_push_text(
    *,
    to_name: str | None,
    kind: str | None,
    day: str,
    time: str,
    arena_name: str,
    tries: int,
    resist_ms: int,
    falls: int,
    tricked: bool,
    nth: int,
) -> str:
    """Подпись к билету. Без рода: открытку шлют кому угодно, пол получателя неизвестен."""
    to = (to_name or "").strip()
    if to and nth <= 1:
        head = f"<b>{html.escape(to)}: ДА!</b>"
    elif nth <= 1:
        head = "<b>На твою открытку ответили «ДА»!</b>"
    else:
        head = f"<b>Ещё одно «ДА» — уже {_nth_word(nth)}</b>"
    what = {"hockey_practice": "Хоккей", "hockey_match": "Матч"}.get(kind or "", "Каток")
    when = ", ".join(p for p in (day, time) if p)
    seconds = max(0, round(int(resist_ms) / 1000))
    lines = [
        head,
        "",
        html.escape(f"{what} · {when}"),
        html.escape(arena_name),
        "",
        html.escape(verdict(int(tries), int(falls), bool(tricked))),
        html.escape(f"Держались {seconds} с · отказов {int(tries)} · падений {int(falls)}"),
    ]
    return "\n".join(lines)


def route_url(arena: Mapping[str, Any]) -> str:
    query = ", ".join(str(p) for p in (arena.get("city"), arena.get("address") or arena.get("name")) if p)
    return "https://yandex.by/maps/?text=" + quote(query)


async def _claim(session: AsyncSession, answer_id: int, now: datetime) -> bool:
    row = (
        await session.execute(
            text(_CLAIM),
            {"answer_id": answer_id, "now": now, "stale": now - CLAIM_TTL, "max_attempts": MAX_ATTEMPTS},
        )
    ).first()
    await session.commit()
    return row is not None


async def _finish(session: AsyncSession, answer_id: int, *, sent: bool, give_up: bool = False) -> None:
    if sent:
        sql = "UPDATE ice_invite_answers SET notified_at = now() WHERE id = :id"
    elif give_up:
        sql = "UPDATE ice_invite_answers SET notify_attempts = :max_attempts WHERE id = :id"
    else:
        sql = "UPDATE ice_invite_answers SET notify_claimed_at = NULL WHERE id = :id"
    await session.execute(text(sql), {"id": answer_id, "max_attempts": MAX_ATTEMPTS})
    await session.commit()


async def deliver_invite_answer_push(session: AsyncSession, bot: Bot, answer_id: int) -> bool:
    """Одна доставка. True — сообщение ушло. Никогда не бросает наружу."""
    now = datetime.now(timezone.utc)
    try:
        if not await _claim(session, int(answer_id), now):
            return False
        row = (await session.execute(text(_LOAD), {"answer_id": int(answer_id)})).mappings().first()
        if row is None:
            return False
        # Создатель сам ответил на свою открытку (проверял) — это не новость.
        if row["creator_actor_hash"] and row["creator_actor_hash"] == row["responder_actor_hash"]:
            await _finish(session, int(answer_id), sent=True)
            return False
        try:
            invite = await get_invite(session, str(row["code"]), device_token=None, mark_opened=False)
        except InviteRejected:
            await _finish(session, int(answer_id), sent=False, give_up=True)
            return False
        s = invite["session"]
        caption = answer_push_text(
            to_name=invite.get("to_name"),
            kind=invite.get("kind"),
            day=day_short(s.get("local_date")),
            time=str(s.get("starts_at_local") or ""),
            arena_name=str(s["arena"].get("name") or ""),
            tries=int(row["tries"]),
            resist_ms=int(row["resist_ms"]),
            falls=int(row["falls"]),
            tricked=bool(row["tricked"]),
            nth=int(row["nth"]),
        )
        stats = {
            "tries": int(row["tries"]),
            "seconds": max(0, min(600, round(int(row["resist_ms"]) / 1000))),
            "falls": int(row["falls"]),
            "tricked": bool(row["tricked"]),
        }
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Маршрут", url=route_url(s["arena"]))]]
        )
        chat_id = int(row["creator_telegram_id"])
        try:
            png = await render_png_cached(
                "zovi_ticket",
                {"code": invite["code"], **stats},
                {"v": image_version(invite), "ticket": [s["arena"].get("address"), s.get("price")]},
                render_zovi_ticket,
                invite,
                **stats,
            )
            await bot.send_photo(
                chat_id=chat_id,
                photo=BufferedInputFile(png, filename="glide-bilet.png"),
                caption=caption,
                reply_markup=keyboard,
            )
        except TelegramForbiddenError:
            await _finish(session, int(answer_id), sent=False, give_up=True)
            return False
        except Exception:
            # Картинка не ушла — текст важнее картинки.
            logger.warning("zovi answer push: photo failed, sending text answer_id=%s", answer_id, exc_info=True)
            await bot.send_message(chat_id=chat_id, text=caption, reply_markup=keyboard)
        await _finish(session, int(answer_id), sent=True)
        return True
    except TelegramForbiddenError:
        await _finish(session, int(answer_id), sent=False, give_up=True)
        return False
    except Exception:
        logger.exception("zovi answer push failed answer_id=%s", answer_id)
        try:
            await session.rollback()
            await _finish(session, int(answer_id), sent=False)
        except Exception:  # noqa: BLE001 — повтор подберёт цикл
            logger.exception("zovi answer push: release failed answer_id=%s", answer_id)
        return False


async def process_invite_answer_pushes(session: AsyncSession, bot: Bot) -> int:
    """Добрать недоставленные ответы (цикл уведомлений бота)."""
    now = datetime.now(timezone.utc)
    ids = [
        int(r[0])
        for r in (
            await session.execute(
                text(_PENDING),
                {
                    "max_attempts": MAX_ATTEMPTS,
                    "stale": now - CLAIM_TTL,
                    "since": now - SWEEP_WINDOW,
                    "limit": SWEEP_LIMIT,
                },
            )
        ).all()
    ]
    sent = 0
    for answer_id in ids:
        if await deliver_invite_answer_push(session, bot, answer_id):
            sent += 1
    return sent


_NEEDS_PUSH = """
SELECT 1
FROM ice_invite_answers a
JOIN ice_invites i ON i.id = a.invite_id
WHERE a.id = :answer_id AND a.notified_at IS NULL AND i.creator_telegram_id IS NOT NULL
"""


async def push_answer_soon(answer_id: int) -> None:
    """Фоновая задача после ответа: своя сессия и свой бот. Никогда не бросает наружу.

    Бот создаётся, только если пуш вообще нужен: открытки без Telegram — большинство
    ответов с сайта, и aiogram падает уже на создании бота с негодным токеном.
    """
    from src.infrastructure.db.session import async_session_factory
    from src.shared.config import Settings

    bot: Bot | None = None
    try:
        async with async_session_factory() as session:
            needed = (await session.execute(text(_NEEDS_PUSH), {"answer_id": int(answer_id)})).first()
            if needed is None:
                return
            token = Settings().telegram_bot_token_client
            if not token:
                return
            bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            await deliver_invite_answer_push(session, bot, int(answer_id))
    except Exception:
        logger.exception("zovi answer push task failed answer_id=%s", answer_id)
    finally:
        if bot is not None:
            await bot.session.close()
