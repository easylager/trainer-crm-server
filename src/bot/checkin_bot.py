"""TASK-446: «Я здесь» — бот-часть (флаг ``redesign_s5``).

Цикл (60 c, из notification_service):
1. создаёт ``ice_checkin_prompts`` по ``ice_checkins.candidate_rows`` — только людям
   с флагом, включённым тумблером «Сообщения в чате» (``hockey_player_prefs.remind``,
   нет строки = вкл), без ``bot_blocked_at``, без отметки сегодня, без вопроса сегодня,
   без мута катка (два «Я не на катке» подряд → 30 дней тишины);
2. шлёт пришедшие вопросы — не больше одного на человека в минские сутки;
3. гасит просроченные (сеанс кончился — status expired, клавиатуру снимаем best-effort).

Колбэк ``ci:{prompt_id}:{1|2|3|no}``: оценка = отметка source=chat с load_level;
«no» → not_here и серия мутов. Успешная отметка на катке серию сбрасывает
(``ice_checkins.check_in``).
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application import ice_checkins as ic
from src.application.client_ui_flags import redesign_s5_enabled
from src.application.hockey_notices import mark_blocked
from src.application.place_links import place_start_param, public_telegram_entry_link
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings, get_settings

logger = logging.getLogger(__name__)

LOOP_INTERVAL_SEC = 60

client_router = Router(name="checkin_client")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Тексты и клавиатура ──────────────────────────────────────────────────


def prompt_text(arena_name: str, ends_local: str, streak_next: int | None) -> str:
    text = f"Ты на катке?\n{arena_name}, сеанс идёт до {ends_local}. Сколько сейчас народу? Отметка засчитается в серию"
    if streak_next and streak_next >= 2:
        text += f": это будет {streak_next}-я неделя подряд"
    return text + "."


def prompt_keyboard(prompt_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Свободно", callback_data=f"ci:{prompt_id}:1"),
                InlineKeyboardButton(text="В меру", callback_data=f"ci:{prompt_id}:2"),
                InlineKeyboardButton(text="Людно", callback_data=f"ci:{prompt_id}:3"),
            ],
            [InlineKeyboardButton(text="Я не на катке", callback_data=f"ci:{prompt_id}:no")],
        ]
    )


def answered_text(season_days: int, streak: int) -> str:
    lines = [f"Отмечено · {season_days}-й раз за сезон."]
    if streak:
        lines.append(f"Серия: {streak} {ic.plural_week(streak)} подряд.")
    return "\n".join(lines)


def answered_keyboard(share_url: str | None) -> InlineKeyboardMarkup | None:
    if not share_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Позвать сюда", url=share_url)]]
    )


# ── Создание вопросов ────────────────────────────────────────────────────


async def _eligible_telegram_ids(
    session: AsyncSession, rows: list[dict], now: datetime, settings: Any
) -> list[dict]:
    """Отсев кандидатов: флаг, тумблер, блок, отметка сегодня, вопрос сегодня, мут."""
    if not rows:
        return []
    tgs = sorted({int(r["telegram_id"]) for r in rows})
    prefs = (
        (
            await session.execute(
                text(
                    """
                    SELECT player_key, COALESCE(remind, true) AS remind, bot_blocked_at
                    FROM hockey_player_prefs WHERE player_key = ANY(:ids)
                    """
                ),
                {"ids": tgs},
            )
        )
        .mappings()
        .all()
    )
    prefs_by = {int(p["player_key"]): p for p in prefs}
    today = now.astimezone(ic.MINSK).date()
    checked_today = {
        int(r[0])
        for r in (
            await session.execute(
                text("SELECT DISTINCT telegram_id FROM ice_checkins WHERE telegram_id = ANY(:ids) AND local_date = :d"),
                {"ids": tgs, "d": today},
            )
        ).all()
    }
    prompted_today = {
        int(r[0])
        for r in (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT telegram_id FROM ice_checkin_prompts
                    WHERE telegram_id = ANY(:ids)
                      AND (due_at AT TIME ZONE 'Europe/Minsk')::date = :d
                    """
                ),
                {"ids": tgs, "d": today},
            )
        ).all()
    }
    muted = {
        (int(r["telegram_id"]), int(r["arena_id"]))
        for r in (
            (
                await session.execute(
                    text(
                        """
                        SELECT telegram_id, arena_id FROM ice_checkin_mutes
                        WHERE telegram_id = ANY(:ids) AND muted_until IS NOT NULL AND muted_until > :now
                        """
                    ),
                    {"ids": tgs, "now": now},
                )
            )
            .mappings()
            .all()
        )
    }
    out = []
    for r in rows:
        tg = int(r["telegram_id"])
        if not redesign_s5_enabled(tg, settings):
            continue
        p = prefs_by.get(tg)
        if p is not None:
            if not p["remind"]:
                continue
            if p["bot_blocked_at"] is not None:
                continue
        if tg in checked_today or tg in prompted_today:
            continue
        if (tg, int(r["arena_id"])) in muted:
            continue
        out.append(r)
    return out


async def create_prompts(session: AsyncSession, now: datetime, settings: Any) -> list[dict]:
    """Строки ``ice_checkin_prompts`` для кандидатов: pending + due_at=start+20мин."""
    candidates = await ic.candidate_rows(session, now)
    eligible = await _eligible_telegram_ids(session, candidates, now, settings)
    created: list[dict] = []
    for r in eligible:
        ins = (
            (
                await session.execute(
                    text(
                        """
                        INSERT INTO ice_checkin_prompts (telegram_id, session_id, arena_id, reason, due_at)
                        VALUES (:t, :s, :a, :r, :d)
                        ON CONFLICT (telegram_id, session_id) DO NOTHING
                        RETURNING id, telegram_id, session_id, arena_id, due_at
                        """
                    ),
                    {
                        "t": int(r["telegram_id"]),
                        "s": int(r["session_id"]),
                        "a": int(r["arena_id"]),
                        "r": r["reason"],
                        "d": r["due_at"],
                    },
                )
            )
            .mappings()
            .first()
        )
        if ins is not None:
            created.append(dict(ins))
    return created


# ── Отправка и истечение ─────────────────────────────────────────────────


async def due_prompts(session: AsyncSession, now: datetime) -> list[dict]:
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT p.id, p.telegram_id, p.session_id, p.arena_id, a.name AS arena_name,
                           s.ends_at_local, s.ends_at_utc
                    FROM ice_checkin_prompts p
                    JOIN arenas a ON a.id = p.arena_id
                    JOIN ice_sessions s ON s.id = p.session_id
                    WHERE p.status = 'pending' AND p.due_at <= :now
                    ORDER BY p.due_at
                    """
                ),
                {"now": now},
            )
        )
        .mappings()
        .all()
    )
    # Не больше одного вопроса на человека в сутки: если сегодня уже отправляли —
    # снимаем лишние (skipped), не держим в pending.
    today = now.astimezone(ic.MINSK).date()
    sent_today = {
        int(r[0])
        for r in (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT telegram_id FROM ice_checkin_prompts
                    WHERE sent_at IS NOT NULL AND (sent_at AT TIME ZONE 'Europe/Minsk')::date = :d
                    """
                ),
                {"d": today},
            )
        ).all()
    }
    send, skip = [], []
    for r in rows:
        (skip if int(r["telegram_id"]) in sent_today else send).append(r)
        sent_today.add(int(r["telegram_id"]))
    if skip:
        await session.execute(
            text("UPDATE ice_checkin_prompts SET status = 'skipped' WHERE id = ANY(:ids)"),
            {"ids": [int(r["id"]) for r in skip]},
        )
    return send


async def _streak_next(session: AsyncSession, telegram_id: int, now: datetime) -> int | None:
    """«это будет N-я неделя подряд» — только если серия есть и в этой неделе отметки нет."""
    today = now.astimezone(ic.MINSK).date()
    stats = await ic.me_stats(session, telegram_id, None, today)
    if stats["streak_weeks"] >= 1 and not stats["has_this_week"]:
        return stats["streak_weeks"] + 1
    return None


async def send_due_prompts(bot: Bot, session: AsyncSession, now: datetime) -> int:
    sent = 0
    for r in await due_prompts(session, now):
        tg = int(r["telegram_id"])
        streak_next = await _streak_next(session, tg, now)
        try:
            msg = await bot.send_message(
                tg,
                prompt_text(str(r["arena_name"]), str(r["ends_at_local"])[:5], streak_next),
                reply_markup=prompt_keyboard(int(r["id"])),
            )
        except TelegramForbiddenError:
            await mark_blocked(session, tg, now=now)
            await session.execute(
                text("UPDATE ice_checkin_prompts SET status = 'skipped' WHERE id = :id"),
                {"id": int(r["id"])},
            )
            continue
        except Exception:  # noqa: BLE001
            logger.exception("checkin prompt send failed prompt=%s", r["id"])
            continue
        await session.execute(
            text(
                """
                UPDATE ice_checkin_prompts
                SET status = 'sent', sent_at = :now, message_id = :mid
                WHERE id = :id AND status = 'pending'
                """
            ),
            {"now": now, "mid": int(msg.message_id), "id": int(r["id"])},
        )
        sent += 1
    return sent


async def expire_prompts(session: AsyncSession, bot: Bot | None, now: datetime) -> int:
    """Сеанс закончился, ответа нет → expired; клавиатуру с присланного снимаем."""
    rows = (
        (
            await session.execute(
                text(
                    """
                    UPDATE ice_checkin_prompts p SET status = 'expired'
                    FROM ice_sessions s
                    WHERE p.session_id = s.id AND s.ends_at_utc <= :now
                      AND p.status IN ('pending','sent')
                    RETURNING p.id, p.telegram_id, p.message_id, p.status
                    """
                ),
                {"now": now},
            )
        )
        .mappings()
        .all()
    )
    if bot is not None:
        for r in rows:
            if r["message_id"] is None:
                continue
            try:
                await bot.edit_message_reply_markup(
                    chat_id=int(r["telegram_id"]), message_id=int(r["message_id"]), reply_markup=None
                )
            except Exception:  # noqa: BLE001 — сообщение могли удалить
                pass
    return len(rows)


async def run_checkin_cycle(bot: Bot, now: datetime | None = None) -> dict:
    """Один тик: создать → отправить → погасить."""
    now = now or _now()
    settings = get_settings()
    async with async_session_factory() as session:
        created = await create_prompts(session, now, settings)
        await session.commit()
    sent = 0
    try:
        async with async_session_factory() as session:
            sent = await send_due_prompts(bot, session, now)
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("checkin send tick failed")
    expired = 0
    try:
        async with async_session_factory() as session:
            expired = await expire_prompts(session, bot, now)
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("checkin expire tick failed")
    return {"created": len(created), "sent": sent, "expired": expired}


async def run_checkin_loop(client_bot: Bot) -> None:
    import asyncio

    while True:
        await asyncio.sleep(LOOP_INTERVAL_SEC)
        try:
            await run_checkin_cycle(client_bot)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001
            logger.exception("Checkin loop: %s", exc)


# ── Колбэк кнопок ────────────────────────────────────────────────────────


async def _prompt_row(session: AsyncSession, prompt_id: int, tg: int):
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT p.id, p.telegram_id, p.session_id, p.arena_id, p.status,
                           a.name AS arena_name, s.ends_at_local
                    FROM ice_checkin_prompts p
                    JOIN arenas a ON a.id = p.arena_id
                    JOIN ice_sessions s ON s.id = p.session_id
                    WHERE p.id = :id
                    """
                ),
                {"id": int(prompt_id)},
            )
        )
        .mappings()
        .first()
    )


def _share_url(settings: Any, arena_id: int, session_id: int, caption: str) -> str | None:
    from urllib.parse import quote

    url = public_telegram_entry_link(
        settings, start_param=place_start_param(int(arena_id), int(session_id))
    )
    if not url:
        return None
    return f"https://t.me/share/url?url={quote(url, safe='')}&text={quote(caption, safe='')}"


async def _answer(
    session: AsyncSession, prompt: dict, tg: int, level: int, now: datetime
) -> dict:
    """Оценка → отметка source=chat; возвращает {status, season_days, streak}."""
    if prompt["status"] == "answered":
        return {"status": "already"}
    try:
        res = await ic.check_in(
            session, tg, None, int(prompt["session_id"]), "chat", load_level=level, now=now
        )
    except ic.CheckinError as err:
        if err.code == "not_ongoing":
            return {"status": "ended"}
        raise
    today = now.astimezone(ic.MINSK).date()
    stats = await ic.me_stats(session, tg, None, today)
    await session.execute(
        text(
            """
            UPDATE ice_checkin_prompts SET status = 'answered', answered_at = :now WHERE id = :id
            """
        ),
        {"now": now, "id": int(prompt["id"])},
    )
    return {"status": "ok", "season_days": stats["season_days"], "streak_weeks": stats["streak_weeks"],
            "session_id": res["session_id"]}


async def _not_here(session: AsyncSession, prompt: dict, tg: int, now: datetime) -> None:
    await session.execute(
        text(
            """
            UPDATE ice_checkin_prompts SET status = 'not_here', answered_at = :now
            WHERE id = :id AND status IN ('pending','sent')
            """
        ),
        {"now": now, "id": int(prompt["id"])},
    )
    await session.execute(
        text(
            """
            INSERT INTO ice_checkin_mutes (telegram_id, arena_id, not_here_streak, muted_until)
            VALUES (:t, :a, 1, NULL)
            ON CONFLICT (telegram_id, arena_id) DO UPDATE SET
                not_here_streak = ice_checkin_mutes.not_here_streak + 1,
                muted_until = CASE
                    WHEN ice_checkin_mutes.not_here_streak + 1 >= :lim THEN :mute
                    ELSE ice_checkin_mutes.muted_until END
            """
        ),
        {
            "t": tg,
            "a": int(prompt["arena_id"]),
            "lim": ic.NOT_HERE_MUTE_AFTER,
            "mute": now + timedelta(days=ic.NOT_HERE_MUTE_DAYS),
        },
    )


@client_router.callback_query(F.data.regexp(r"^ci:\d+:(1|2|3|no)$"))
async def on_checkin_button(query: CallbackQuery) -> None:
    try:
        _, prompt_id_s, action = (query.data or "").split(":")
        prompt_id = int(prompt_id_s)
    except ValueError:
        await query.answer()
        return
    tg = query.from_user.id if query.from_user else 0
    now = _now()
    async with async_session_factory() as session:
        prompt = await _prompt_row(session, prompt_id, tg)
        if prompt is None or int(prompt["telegram_id"]) != tg:
            await query.answer()
            return
        if action == "no":
            await _not_here(session, prompt, tg, now)
            await session.commit()
            await query.answer("Понял, сегодня не спрашиваю")
            try:
                await query.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass
            return
        level = int(action)
        try:
            res = await _answer(session, dict(prompt), tg, level, now)
        except ic.CheckinError:
            await session.rollback()
            await query.answer("Не получилось отметиться")
            return
        if res["status"] == "ended":
            await session.execute(
                text("UPDATE ice_checkin_prompts SET status = 'expired' WHERE id = :id"),
                {"id": prompt_id},
            )
            await session.commit()
            await query.answer("Сеанс уже закончился")
            try:
                await query.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass
            return
        if res["status"] == "already":
            await session.commit()
            await query.answer("Уже отмечено")
            return
        await session.commit()

    settings = get_settings()
    share = _share_url(
        settings,
        int(prompt["arena_id"]),
        int(res["session_id"]),
        f"На «{prompt['arena_name']}» до {str(prompt['ends_at_local'])[:5]}\nПодъезжай!",
    )
    try:
        await query.message.edit_text(  # type: ignore[union-attr]
            answered_text(int(res["season_days"]), int(res["streak_weeks"])),
            reply_markup=answered_keyboard(share),
        )
    except Exception:  # noqa: BLE001
        pass
    await query.answer("Спасибо, учёл")
