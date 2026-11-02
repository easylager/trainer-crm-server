"""Админ-бот «Кто кого»: очередь ручной проверки итогов Экстралиги и закрытие месяца (TASK-334 S6, волна 2).

У Экстралиги нет второго источника итога (TASK-340): счёт публикуется после двух одинаковых опросов
hockey.by подряд. Если опросы разошлись, метки способа окончания нет или разница при овертайме/буллитах
не в одну шайбу, матч уходит в ``review``. Админ в боте может:

* принять счёт — тот, что последним увидел опрос (``result_probe``);
* поправить — прислать счёт и способ вручную;
* отменить матч — для игры это отмена: без очков, козыри возвращаются.

Любое решение закрывает матч сильнее автомата и пересчитывает очки. Кнопка «Закрыть месяц» — это
``hockey_races.confirm_close_month``: корона пишется сразу, не дожидаясь 7 суток окна исправления.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_game import score_finished_matches
from src.application.hockey_matches import DECIDED_VALUES, cancel_match, set_manual_result
from src.ingestion.hockey_sources import MINSK_TZ

logger = logging.getLogger(__name__)

CB_ACCEPT = "hk:ok"  # hk:ok:<матч>
CB_FIX = "hk:fix"  # hk:fix:<матч>
CB_CANCEL = "hk:no"  # hk:no:<матч> — спросить; hk:no2:<матч> — подтвердить
CB_CANCEL_YES = "hk:no2"
CB_CLOSE_MONTH = "hk:cm"  # hk:cm:<гонка>:<клуб|->
ALL_CLUBS = "-"

ENDING_TITLES = {"regulation": "основное время", "ot": "овертайм", "so": "буллиты"}
_ENDING_WORDS = {
    "": "regulation",
    "осн": "regulation",
    "основное": "regulation",
    "от": "ot",
    "овертайм": "ot",
    "б": "so",
    "бул": "so",
    "буллиты": "so",
}
_FIX_RE = re.compile(r"^\s*(\d{1,2})\s*[:\-]\s*(\d{1,2})\s*([^\W\d_]*)\s*$", re.IGNORECASE)

Sender = Callable[[str, list[list[dict]]], Awaitable["bool | None"]]


@dataclass(frozen=True)
class ReviewItem:
    id: int
    home_team: str
    away_team: str
    starts_at: datetime
    reason: str | None
    probe: dict | None

    @property
    def probe_ready(self) -> bool:
        p = self.probe or {}
        return p.get("home") is not None and p.get("away") is not None and p.get("decided_in") in DECIDED_VALUES


_QUEUE = text("""
    SELECT id, home_team, away_team, starts_at, review_reason AS reason, result_probe AS probe
    FROM hockey_matches
    WHERE league = 'extraliga' AND status = 'review'
    ORDER BY starts_at
    LIMIT :limit
    """)

_ONE = text("""
    SELECT id, home_team, away_team, starts_at, review_reason AS reason, result_probe AS probe, status
    FROM hockey_matches WHERE id = :id AND league = 'extraliga'
    """)

_UNALERTED = text("""
    SELECT id FROM hockey_matches
    WHERE league = 'extraliga' AND status = 'review' AND review_alerted_at IS NULL
    ORDER BY starts_at
    """)

_ALERTED = text("UPDATE hockey_matches SET review_alerted_at = :now WHERE id = :id")


def _item(record) -> ReviewItem:
    return ReviewItem(record.id, record.home_team, record.away_team, record.starts_at, record.reason, record.probe)


async def review_queue(session: AsyncSession, *, limit: int = 10) -> list[ReviewItem]:
    return [_item(r) for r in (await session.execute(_QUEUE, {"limit": limit})).all()]


async def get_review_item(session: AsyncSession, match_id: int) -> tuple[ReviewItem, str] | None:
    record = (await session.execute(_ONE, {"id": match_id})).one_or_none()
    return None if record is None else (_item(record), record.status)


def _when(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MINSK_TZ).strftime("%d.%m %H:%M")


def probe_title(probe: dict | None) -> str | None:
    if not probe or probe.get("home") is None or probe.get("away") is None:
        return None
    ending = ENDING_TITLES.get(probe.get("decided_in") or "", "способ окончания не указан")
    return f"{probe['home']}:{probe['away']}, {ending}"


def review_text(item: ReviewItem) -> str:
    out = (
        f"<b>Экстралига: итог на проверке</b>\n"
        f"{html.escape(item.home_team)} — {html.escape(item.away_team)}, {_when(item.starts_at)}\n"
        f"Причина: {html.escape(item.reason or 'не записана')}"
    )
    seen = probe_title(item.probe)
    if seen:
        out += f"\nПоследний опрос hockey.by: {seen}"
    return out


def review_buttons(item: ReviewItem) -> list[list[dict]]:
    rows: list[list[dict]] = []
    if item.probe_ready:
        p = item.probe or {}
        rows.append([{"text": f"Принять {p['home']}:{p['away']}", "callback_data": f"{CB_ACCEPT}:{item.id}"}])
    rows.append(
        [
            {"text": "Поправить", "callback_data": f"{CB_FIX}:{item.id}"},
            {"text": "Отменить матч", "callback_data": f"{CB_CANCEL}:{item.id}"},
        ]
    )
    return rows


class ReviewError(ValueError):
    """Решение админа не применено: текст ошибки показываем ему как есть."""


async def _settle(session: AsyncSession, match_id: int) -> tuple[ReviewItem, str]:
    found = await get_review_item(session, match_id)
    if found is None:
        raise ReviewError("Такого матча Экстралиги нет")
    return found


async def accept_probe(session: AsyncSession, match_id: int, *, now: datetime) -> str:
    """Принять счёт последнего опроса. Возвращает подпись итога для ответа админу."""
    item, status = await _settle(session, match_id)
    if status != "review":
        raise ReviewError("Матч уже не на проверке")
    if not item.probe_ready:
        raise ReviewError("В последнем опросе нет полного итога — поправьте счёт вручную")
    p = item.probe or {}
    await set_manual_result(
        session, match_id, home_score=int(p["home"]), away_score=int(p["away"]), decided_in=p["decided_in"], now=now
    )
    await score_finished_matches(session, now=now)
    return f"{p['home']}:{p['away']} ({ENDING_TITLES[p['decided_in']]})"


def parse_fix(raw: str) -> tuple[int, int, str]:
    """«3:2», «3:2 от», «3-2 б» → (3, 2, 'ot'). ``ReviewError`` — с подсказкой формата."""
    m = _FIX_RE.match(raw or "")
    word = (m.group(3) if m else "").lower()
    if not m or word not in _ENDING_WORDS:
        raise ReviewError("Формат: 3:2 — основное время, 3:2 от — овертайм, 3:2 б — буллиты")
    return int(m.group(1)), int(m.group(2)), _ENDING_WORDS[word]


async def fix_result(session: AsyncSession, match_id: int, *, raw: str, now: datetime) -> str:
    """Счёт вручную: закрывает матч, пересчитывает очки. Проверка — та же, что у ручного ввода из админки."""
    home, away, decided_in = parse_fix(raw)
    item, status = await _settle(session, match_id)
    if status not in ("review", "scheduled", "final"):
        raise ReviewError("С этим матчем так нельзя")
    try:
        await set_manual_result(session, match_id, home_score=home, away_score=away, decided_in=decided_in, now=now)
    except ValueError as exc:
        raise ReviewError(str(exc)) from exc
    await score_finished_matches(session, now=now)
    return f"{item.home_team} — {item.away_team}: {home}:{away} ({ENDING_TITLES[decided_in]})"


async def cancel_review(session: AsyncSession, match_id: int, *, now: datetime) -> str:
    item, status = await _settle(session, match_id)
    if status != "review":
        raise ReviewError("Матч уже не на проверке")
    await cancel_match(session, match_id, reason="admin", now=now)
    await score_finished_matches(session, now=now)
    return f"{item.home_team} — {item.away_team}"


async def notify_new_reviews(session_factory, *, now: datetime, send: Sender) -> int:
    """Карточка с кнопками в админ-бот — один раз на матч, попавший на проверку. Возвращает число карточек."""
    async with session_factory() as session:
        ids = list((await session.execute(_UNALERTED)).scalars().all())
    sent = 0
    for match_id in ids:
        async with session_factory() as session:
            found = await get_review_item(session, match_id)
        if found is None:
            continue
        item, _ = found
        delivered = await send(review_text(item), review_buttons(item))
        if delivered is False:
            continue  # админ-бот недоступен: повторим на следующем тике
        async with session_factory() as session:
            await session.execute(_ALERTED, {"id": match_id, "now": now})
            await session.commit()
        sent += 1
    return sent


def month_close_text(item: dict) -> str:
    leaders = ", ".join(f"{html.escape(n)} ({p})" for n, p in item["leaders"])
    scope = item["club"] or "общая таблица"
    return (
        f"<b>Корона: {html.escape(item['title'])} · {html.escape(scope)}</b>\n"
        f"Всё сыграно. Лидер: {leaders}.\n"
        f"Сама запишется {item['auto_at'].astimezone(MINSK_TZ).strftime('%d.%m')} — после окна исправления итога."
    )


def month_close_buttons(item: dict) -> list[list[dict]]:
    club = item["club"] or ALL_CLUBS
    return [[{"text": "Закрыть месяц сейчас", "callback_data": f"{CB_CLOSE_MONTH}:{item['race_id']}:{club}"}]]


async def send_card_to_admins(text_body: str, buttons: list[list[dict]]) -> bool | None:
    """Карточка с кнопками в чаты админов (те же, что у алертов льда). ``None`` — бот не настроен."""
    import os

    from src.ingestion.alerts import ice_alert_chat_ids
    from src.shared.config import Settings

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    settings = Settings()  # type: ignore[call-arg]
    token = getattr(settings, "telegram_bot_token_admin", None)
    chat_ids = ice_alert_chat_ids(settings)
    if not token or not chat_ids:
        logger.warning("Admin bot not configured, hockey review card (log only):\n%s", text_body)
        return None
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(**b) for b in row] for row in buttons])
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    delivered = False
    try:
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=text_body, reply_markup=markup)
                delivered = True
            except Exception:  # noqa: BLE001
                logger.warning("hockey review card to %s failed", chat_id, exc_info=True)
    finally:
        await bot.session.close()
    return delivered


__all__ = [
    "ALL_CLUBS",
    "CB_ACCEPT",
    "CB_CANCEL",
    "CB_CANCEL_YES",
    "CB_CLOSE_MONTH",
    "CB_FIX",
    "ReviewError",
    "ReviewItem",
    "accept_probe",
    "cancel_review",
    "fix_result",
    "month_close_buttons",
    "month_close_text",
    "notify_new_reviews",
    "parse_fix",
    "review_buttons",
    "review_queue",
    "review_text",
    "send_card_to_admins",
]
