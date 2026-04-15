"""
Notify all roster clients when a trainer replaces a training group's recurring series schedule.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import messages as msg
from src.infrastructure.db.session import async_session_factory
from src.shared.config import Settings

logger = logging.getLogger(__name__)


async def _load_series_update_payload(
    session: AsyncSession,
    trainer_id: int,
    group_id: int,
) -> dict[str, Any] | None:
    r = await session.execute(
        text(
            """
            SELECT tg.name, tg.season_start_date,
                   s.name AS service_name,
                   a.name AS arena_name,
                   p.first_name, p.last_name
            FROM training_groups tg
            JOIN services s ON s.id = tg.service_id
            LEFT JOIN arenas a ON a.id = tg.arena_id
            JOIN trainers t ON t.id = tg.trainer_id
            LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
            WHERE tg.id = :gid AND tg.trainer_id = :tid
            """
        ),
        {"gid": group_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    rules_r = await session.execute(
        text(
            """
            SELECT day_of_week, start_time, duration_minutes
            FROM training_group_schedule_rules
            WHERE training_group_id = :gid
            ORDER BY day_of_week, start_time
            """
        ),
        {"gid": group_id},
    )
    rules: list[dict] = []
    for rr in rules_r.fetchall():
        st = rr[1]
        rules.append(
            {
                "day_of_week": int(rr[0]),
                "start_time": st.strftime("%H:%M") if hasattr(st, "strftime") else str(st)[:5],
                "duration_minutes": int(rr[2] or 60),
            }
        )
    mem_r = await session.execute(
        text(
            """
            SELECT DISTINCT c.telegram_id
            FROM training_group_members m
            JOIN clients c ON c.id = m.client_id
            WHERE m.training_group_id = :gid
              AND m.status IN ('active', 'trial', 'waitlist')
              AND c.telegram_id IS NOT NULL
            """
        ),
        {"gid": group_id},
    )
    telegram_ids = [int(x[0]) for x in mem_r.fetchall() if x[0] is not None]
    fn, ln = row[4], row[5]
    trainer_parts = [p for p in [(fn or "").strip(), (ln or "").strip()] if p]
    trainer_name = " ".join(trainer_parts) if trainer_parts else "Тренер"
    ssd = row[1]
    season_s: str | None = None
    if ssd is not None:
        season_s = ssd.strftime("%d.%m.%Y") if hasattr(ssd, "strftime") else str(ssd)
    return {
        "group_name": (row[0] or "").strip() or "Группа",
        "season_start_date": season_s,
        "service_name": (row[2] or "").strip() or "—",
        "arena_name": (row[3] or "").strip() if row[3] else None,
        "trainer_name": trainer_name,
        "rules": rules,
        "telegram_ids": telegram_ids,
    }


async def notify_clients_group_series_schedule_updated(trainer_id: int, group_id: int) -> None:
    """Send client-bot HTML message to every roster member with Telegram linked."""
    async with async_session_factory() as session:
        payload = await _load_series_update_payload(session, trainer_id, group_id)
    if not payload or not payload.get("telegram_ids"):
        return
    text_html = msg.format_client_group_series_schedule_updated_html(
        trainer_name=payload["trainer_name"],
        group_name=payload["group_name"],
        service_name=payload["service_name"],
        arena_name=payload["arena_name"],
        season_start_date=payload["season_start_date"],
        rules=payload["rules"],
    )
    settings = Settings()
    bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:

        async def _one(chat_id: int) -> None:
            try:
                await bot.send_message(chat_id=chat_id, text=text_html)
            except Exception as e:
                logger.warning(
                    "Group series schedule notify failed chat_id=%s group_id=%s: %s",
                    chat_id,
                    group_id,
                    e,
                )

        # Per-member failures must not block the rest (Telegram limits, blocked users).
        await asyncio.gather(*(_one(tid) for tid in payload["telegram_ids"]), return_exceptions=True)
    finally:
        await bot.session.close()
