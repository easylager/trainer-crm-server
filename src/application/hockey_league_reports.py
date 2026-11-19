"""Жалобы на лигу «Кто кого» и очистка лица лиги админом (TASK-361).

Владелец лиги задаёт картинку и строку «на что играем» без премодерации. Защита платформы — минимум:
участник (не владелец) жалуется одним тапом, админам уходит одно сообщение с кнопкой «Очистить», а
повторные жалобы на ту же лигу в течение суток сообщений не добавляют (строка в таблице пишется всегда).
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_league_images import image_urls, release_image
from src.application.hockey_leagues import League, _member_league

logger = logging.getLogger(__name__)

ALERT_WINDOW = timedelta(hours=24)
CLEAR_CALLBACK = "hk:lclr:"


class OwnLeagueReport(Exception):
    """Владелец жалуется на свою лигу: очистить её он вправе сам."""


@dataclass(frozen=True)
class LeagueReport:
    id: int
    league: League
    members: int
    reports_24h: int
    alert: bool  # слать ли сообщение админам: за последние сутки по лиге его ещё не слали


_ALERTED_SINCE = text("""
    SELECT EXISTS (SELECT 1 FROM hockey_league_reports
                   WHERE league_id = :league_id AND alerted_at IS NOT NULL AND alerted_at > :since)
    """)

_INSERT_REPORT = text("""
    INSERT INTO hockey_league_reports (league_id, reporter_key, created_at, alerted_at)
    VALUES (:league_id, :reporter_key, :now, :alerted_at)
    RETURNING id
    """)

_COUNT_SINCE = text("""
    SELECT COUNT(*) FROM hockey_league_reports WHERE league_id = :league_id AND created_at > :since
    """)

_MEMBERS = text("SELECT COUNT(*) FROM hockey_league_members WHERE league_id = :league_id")

_UNMARK = text("UPDATE hockey_league_reports SET alerted_at = NULL WHERE id = :id")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def report_league(session: AsyncSession, *, league_id: int, reporter_key: int, now: datetime) -> LeagueReport:
    """Записать жалобу. ``LookupError`` — нет лиги, ``PermissionError`` — жалуется не участник,
    ``OwnLeagueReport`` — владелец. Строку лиги держим под замком, чтобы две одновременные жалобы не дали два сообщения."""
    league = await _member_league(session, league_id, reporter_key)
    if league.owner_key == reporter_key:
        raise OwnLeagueReport(league_id)
    moment = _utc(now)
    since = moment - ALERT_WINDOW
    already = (await session.execute(_ALERTED_SINCE, {"league_id": league_id, "since": since})).scalar_one()
    alert = not already
    report_id = (
        await session.execute(
            _INSERT_REPORT,
            {
                "league_id": league_id,
                "reporter_key": reporter_key,
                "now": moment,
                # Метим сразу: жалоба, пришедшая следом, увидит отметку и сообщения не повторит. Не ушло — ``unmark_alerted``.
                "alerted_at": moment if alert else None,
            },
        )
    ).scalar_one()
    count = (await session.execute(_COUNT_SINCE, {"league_id": league_id, "since": since})).scalar_one()
    members = (await session.execute(_MEMBERS, {"league_id": league_id})).scalar_one()
    return LeagueReport(
        id=int(report_id), league=league, members=int(members), reports_24h=int(count), alert=alert
    )


async def unmark_alerted(session: AsyncSession, report_id: int) -> None:
    """Сообщение админам не ушло: следующая жалоба попробует ещё раз."""
    await session.execute(_UNMARK, {"id": report_id})


def _absolute(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith(("http://", "https://")):
        return url
    from src.shared.config import Settings

    base = (Settings().webapp_base_url or "").strip().rstrip("/")  # type: ignore[call-arg]
    return base + url if base else None


def format_report_alert(report: LeagueReport) -> str:
    """Текст для админ-бота (HTML): всё, что вписал пользователь, экранируем."""
    league = report.league
    image_url, _ = image_urls(league.image_key)
    link = _absolute(image_url)
    lines = [
        "<b>Жалоба на лигу «КТО КОГО»</b>",
        f"Лига #{league.id}: «{html.escape(league.name)}»",
        f"На что играем: «{html.escape(league.stake_text)}»" if league.stake_text else "На что играем: не задано",
        f"Картинка: {html.escape(link)}" if link else ("Картинка: есть" if league.image_key else "Картинка: нет"),
        f"Участников: {report.members} · жалоб за сутки: {report.reports_24h}",
    ]
    return "\n".join(lines)


def report_markup(league_id: int):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Очистить картинку и текст", callback_data=f"{CLEAR_CALLBACK}{int(league_id)}")]
        ]
    )


async def notify_admins(report: LeagueReport) -> bool | None:
    """Одно сообщение админам. Не поднимает исключений: жалоба уже записана, а сбой Telegram — не ошибка игрока.

    True — ушло, None — админ-бот не настроен (текст в логе), False — доставка не удалась."""
    from src.ingestion.alerts import send_ice_health_to_admins

    try:
        return await send_ice_health_to_admins(
            format_report_alert(report), event="kk league report", reply_markup=report_markup(report.league.id)
        )
    except Exception:  # noqa: BLE001
        logger.exception("league report alert failed league_id=%s", report.league.id)
        return False


_LEAGUE_FACE = text("SELECT id, name, image_key, stake_text FROM hockey_leagues WHERE id = :league_id FOR UPDATE")

_CLEAR = text("""
    UPDATE hockey_leagues SET image_key = NULL, stake_text = NULL, updated_at = now()
    WHERE id = :league_id OR (CAST(:key AS text) IS NOT NULL AND image_key = CAST(:key AS text))
    """)


async def clear_league_identity(session: AsyncSession, *, league_id: int) -> dict | None:
    """Очистить картинку и строку «на что играем». ``None`` — нет такой лиги.

    Продолжение лиги делит картинку с исходной, поэтому очищаем все лиги с этим файлом: иначе она осталась бы
    у «продлённой». Файл убирает вызывающий после commit (``release_image``)."""
    row = (await session.execute(_LEAGUE_FACE, {"league_id": league_id})).one_or_none()
    if row is None:
        return None
    result = await session.execute(_CLEAR, {"league_id": league_id, "key": row.image_key})
    return {
        "id": int(row.id),
        "name": row.name,
        "had_image": row.image_key is not None,
        "had_stake": row.stake_text is not None,
        "image_key": row.image_key,
        "leagues_cleared": int(result.rowcount or 0),
    }


async def clear_identity_now(session: AsyncSession, *, league_id: int) -> dict | None:
    """Очистка админом целиком: строки лиги, commit, файлы. Общая для API админки и кнопки в админ-боте.

    Возвращает то, что было очищено (без ключа в хранилище), или ``None`` — лиги нет."""
    cleared = await clear_league_identity(session, league_id=league_id)
    if cleared is None:
        return None
    await session.commit()
    await release_image(session, cleared.pop("image_key"))
    return cleared


__all__ = [
    "ALERT_WINDOW",
    "CLEAR_CALLBACK",
    "LeagueReport",
    "OwnLeagueReport",
    "clear_identity_now",
    "clear_league_identity",
    "format_report_alert",
    "notify_admins",
    "report_league",
    "report_markup",
    "unmark_alerted",
]
