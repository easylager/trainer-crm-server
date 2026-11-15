"""Админ-бот «Кто кого»: очередь ручной проверки итогов Экстралиги и закрытие месяца (TASK-334 S6, волна 2).

У Экстралиги нет второго источника итога (TASK-340): счёт публикуется после двух одинаковых опросов
hockey.by подряд. Если опросы разошлись, метки способа окончания нет или разница при овертайме/буллитах
не в одну шайбу, матч уходит в ``review``. Админ в боте может:

* принять счёт — тот, что последним увидел опрос (``result_probe``);
* поправить — прислать счёт и способ вручную;
* отменить матч — для игры это отмена: без очков, козыри возвращаются.

Любое решение закрывает матч сильнее автомата и пересчитывает очки. Кнопка «Закрыть месяц» — это
``hockey_races.confirm_close_month``: корона пишется сразу, не дожидаясь 2 суток окна исправления.
"""

from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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
CB_AUTO_OK = "hk:okd"  # hk:okd:<матч> — «Всё верно» под сообщением об автоматическом итоге Динамо
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
    league: str = "extraliga"

    @property
    def probe_ready(self) -> bool:
        p = self.probe or {}
        return p.get("home") is not None and p.get("away") is not None and p.get("decided_in") in DECIDED_VALUES


_QUEUE = text("""
    SELECT id, home_team, away_team, starts_at, review_reason AS reason, result_probe AS probe, league
    FROM hockey_matches
    WHERE status = 'review'
    ORDER BY starts_at
    LIMIT :limit
    """)

_ONE = text("""
    SELECT id, home_team, away_team, starts_at, review_reason AS reason, result_probe AS probe, league, status
    FROM hockey_matches WHERE id = :id
    """)

_UNALERTED = text("""
    SELECT id FROM hockey_matches
    WHERE status = 'review' AND review_alerted_at IS NULL
    ORDER BY starts_at
    """)

_ALERTED = text("UPDATE hockey_matches SET review_alerted_at = :now WHERE id = :id")


def _item(record) -> ReviewItem:
    return ReviewItem(
        record.id, record.home_team, record.away_team, record.starts_at, record.reason, record.probe, record.league
    )


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
    if item.league != "extraliga":
        return _dinamo_review_text(item)
    out = (
        f"<b>Экстралига: итог на проверке</b>\n"
        f"{html.escape(item.home_team)} — {html.escape(item.away_team)}, {_when(item.starts_at)}\n"
        f"Причина: {html.escape(item.reason or 'не записана')}"
    )
    seen = probe_title(item.probe)
    if seen:
        out += f"\nПоследний опрос hockey.by: {seen}"
    return out


def _dinamo_review_text(item: ReviewItem) -> str:
    """Карточка проверки матча Динамо: почему не принят сам и что показал каждый источник."""
    out = (
        f"<b>Динамо-Минск: итог на проверке</b>\n"
        f"{html.escape(item.home_team)} — {html.escape(item.away_team)}, {_when(item.starts_at)}\n"
        f"Почему не принят сам: {html.escape(item.reason or 'причина не записана')}"
    )
    sources = (item.probe or {}).get("sources")
    if sources:
        out += "\nЧто показали источники:\n" + html.escape(str(sources))
    seen = probe_title(item.probe)
    if seen:
        out += f"\nПоследнее чтение источников: {seen}"
    out += "\nМожно принять последнее чтение, ввести счёт или отменить матч."
    return out


def review_buttons(item: ReviewItem) -> list[list[dict]]:
    rows: list[list[dict]] = []
    if item.probe_ready:
        p = item.probe or {}
        label = f"Принять {p['home']}:{p['away']}"
        if item.league != "extraliga":
            label += f" ({ENDING_TITLES[p['decided_in']]})"
        rows.append([{"text": label, "callback_data": f"{CB_ACCEPT}:{item.id}"}])
    rows.append(
        [
            {"text": "Поправить", "callback_data": f"{CB_FIX}:{item.id}"},
            {"text": "Отменить матч", "callback_data": f"{CB_CANCEL}:{item.id}"},
        ]
    )
    return rows


_RECENT_FINALS = text("""
    SELECT id, home_team, away_team, starts_at, home_score, away_score, decided_in, result_source
    FROM hockey_matches
    WHERE status = 'final' AND finalized_at >= :since AND home_score IS NOT NULL
    ORDER BY starts_at DESC
    LIMIT :limit
    """)


async def recent_finals(session: AsyncSession, *, now: datetime, hours: int = 48, limit: int = 5) -> list:
    from datetime import timedelta

    params = {"since": now - timedelta(hours=hours), "limit": limit}
    return list((await session.execute(_RECENT_FINALS, params)).all())


def recent_final_text(row, delivered: int) -> str:
    ending = ENDING_TITLES.get(row.decided_in or "", "")
    out = (
        f"<b>Недавний итог</b>\n"
        f"{html.escape(row.home_team)} — {html.escape(row.away_team)}, {_when(row.starts_at)}: "
        f"{row.home_score}:{row.away_score}" + (f" ({ending})" if ending else "")
    )
    if delivered:
        out += f"\nИтог уже разослан {delivered} игрокам: поправка отправит им исправление."
    return out + "\nОшибка? Нажмите «Поправить» и пришлите верный счёт."


# ---------- автоматический итог Динамо: сообщение админу и удержание рассылки ----------

# Пока админ правит итог (нажал «Поправить»), рассылку держим не дольше этого времени: ввод могли забросить,
# а игра не должна зависнуть. Хватает набрать «3:2 от»; по истечении — напоминание админу и рассылка как обычно.
HOLD_FOR = timedelta(minutes=30)
# Сообщение об автоитоге ищем среди недавних: на первом запуске старые итоги админов не заваливают.
AUTO_FINAL_RECENT = timedelta(hours=3)

_AUTO_FINALS = text("""
    SELECT id, home_team, away_team, home_score, away_score, decided_in, finalized_at, result_probe AS probe
    FROM hockey_matches
    WHERE league = 'khl' AND status = 'final' AND result_source = 'auto' AND finalized_at >= :since
      AND result_probe->>'admin_notified_at' IS NULL
    ORDER BY finalized_at, id
    """)

_HOLD_EXPIRED = text("""
    SELECT id, home_team, away_team, home_score, away_score, decided_in, result_probe AS probe
    FROM hockey_matches
    WHERE league = 'khl' AND status = 'final' AND result_probe->>'hold_until' IS NOT NULL
      AND CAST(result_probe->>'hold_until' AS TIMESTAMPTZ) <= :now AND result_probe->>'hold_reminded_at' IS NULL
    ORDER BY id
    """)

_MERGE_PROBE = text("""
    UPDATE hockey_matches SET result_probe = COALESCE(result_probe, CAST('{}' AS jsonb)) || CAST(:patch AS jsonb)
    WHERE id = :id
    """)

_SET_HOLD = text("""
    UPDATE hockey_matches
    SET result_probe = COALESCE(result_probe, CAST('{}' AS jsonb)) || CAST(:patch AS jsonb)
    WHERE id = :id AND status = 'final'
    """)

_DROP_HOLD = text("""
    UPDATE hockey_matches SET result_probe = result_probe - 'hold_until' - 'hold_reminded_at'
    WHERE id = :id AND result_probe->>'hold_until' IS NOT NULL
    """)


async def hold_delivery(session: AsyncSession, match_id: int, *, now: datetime) -> None:
    """Админ начал правку итога: рассылку этого итога клиентам держим ``HOLD_FOR`` (в ``result_probe``, без миграций)."""
    patch = {"hold_until": (now + HOLD_FOR).isoformat(), "hold_reminded_at": None}
    await session.execute(_SET_HOLD, {"id": match_id, "patch": json.dumps(patch)})


async def release_hold(session: AsyncSession, match_id: int) -> None:
    await session.execute(_DROP_HOLD, {"id": match_id})


def delivery_time(finalized_at: datetime) -> tuple[datetime, bool]:
    """Когда клиентам уйдёт итог: ``finalized_at`` + буфер, а в тихие часы — в 09:00. Второе значение: «утром»."""
    from src.application.hockey_notices import QUIET_FROM, QUIET_TO, RESULT_SEND_DELAY, in_quiet_hours

    when = (finalized_at + RESULT_SEND_DELAY).astimezone(MINSK_TZ)
    if not in_quiet_hours(when):
        return when, False
    morning = when.replace(hour=QUIET_TO, minute=0, second=0, microsecond=0)
    if when.hour >= QUIET_FROM:
        morning += timedelta(days=1)
    return morning, True


def auto_final_text(row) -> str:
    ending = ENDING_TITLES.get(row.decided_in or "", "")
    when, morning = delivery_time(row.finalized_at)
    sources = (row.probe or {}).get("confirmed_by") or "Источники: подтверждено двумя опросами."
    return (
        f"<b>Итог записан:</b> {html.escape(row.home_team)} — {html.escape(row.away_team)} "
        f"{row.home_score}:{row.away_score}" + (f" ({ending})" if ending else "") + ".\n"
        f"{html.escape(sources)}\n"
        + (
            f"Клиентам уйдёт утром в {when:%H:%M}."
            if morning
            else f"Клиентам уйдёт около {when:%H:%M}."
        )
    )


def auto_final_buttons(match_id: int) -> list[list[dict]]:
    return [
        [
            {"text": "Всё верно", "callback_data": f"{CB_AUTO_OK}:{match_id}"},
            {"text": "Поправить", "callback_data": f"{CB_FIX}:{match_id}"},
        ]
    ]


async def notify_auto_finals(session_factory, *, now: datetime, send: Sender) -> int:
    """Матч Динамо получил итог автоматически → админу одно сообщение с кнопками (один раз на матч).

    Рассылка клиентам от этого не зависит: ``send`` вернул ``False`` (админ-бот недоступен) — повторим на
    следующем тике, а итог клиентам уйдёт по таймеру. Вторая часть: удержание рассылки истекло, а админ так
    и не закончил правку → напоминание (один раз), рассылка идёт как обычно."""
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    async with session_factory() as session:
        fresh = (await session.execute(_AUTO_FINALS, {"since": now - AUTO_FINAL_RECENT})).all()
        expired = (await session.execute(_HOLD_EXPIRED, {"now": now})).all()
    sent = 0
    for row in fresh:
        if await send(auto_final_text(row), auto_final_buttons(row.id)) is False:
            continue
        async with session_factory() as session:
            await session.execute(_MERGE_PROBE, {"id": row.id, "patch": json.dumps({"admin_notified_at": now.isoformat()})})
            await session.commit()
        sent += 1
    for row in expired:
        ending = ENDING_TITLES.get(row.decided_in or "", "")
        body = (
            f"<b>Правка не завершена:</b> {html.escape(row.home_team)} — {html.escape(row.away_team)} "
            f"{row.home_score}:{row.away_score}" + (f" ({ending})" if ending else "") + ".\n"
            "Итог уходит клиентам как записан. Если он неверный — нажмите «Поправить» ещё раз."
        )
        if await send(body, [[{"text": "Поправить", "callback_data": f"{CB_FIX}:{row.id}"}]]) is False:
            continue
        async with session_factory() as session:
            await session.execute(_MERGE_PROBE, {"id": row.id, "patch": json.dumps({"hold_reminded_at": now.isoformat()})})
            await session.commit()
        sent += 1
    return sent


class ReviewError(ValueError):
    """Решение админа не применено: текст ошибки показываем ему как есть."""


async def _settle(session: AsyncSession, match_id: int) -> tuple[ReviewItem, str]:
    found = await get_review_item(session, match_id)
    if found is None:
        raise ReviewError("Такого матча нет")
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
    "HOLD_FOR",
    "CB_AUTO_OK",
    "auto_final_buttons",
    "auto_final_text",
    "hold_delivery",
    "notify_auto_finals",
    "release_hold",
    "recent_final_text",
    "recent_finals",
    "review_buttons",
    "review_queue",
    "review_text",
    "send_card_to_admins",
]
