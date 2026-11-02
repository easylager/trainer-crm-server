"""Колокольчик на матч с сайта (TASK-347): ``/start mbell_<матч>`` → напоминание за 3 часа и итог.

Сайт не знает, нажал ли человек «Начать» (F2), поэтому подписку ставит бот, когда пришёл ``/start``.
Одна строка на пару (человек, матч): повторное нажатие её не удваивает, ответ — «Уже стоит».
Сообщение сначала «занимается» отметкой в самой строке и только потом уходит, поэтому второй цикл или
повтор тика не пришлёт его дважды. Перенос матча даёт одно сообщение «перенесён на …» и новое
напоминание; отмена и пропажа из календаря — одно «отменён или перенесён». Итог — только если он
пришёл в течение суток после начала. Бот заблокирован — подписки человека снимаются, повторов нет.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application import site_matches
from src.application.hockey_matches import STATUS_FINAL
from src.application.hockey_teams import TEAMS
from src.shared.config import Settings

logger = logging.getLogger(__name__)

BELL_PREFIX = "mbell_"
OFF_PREFIX = "mbell_off:"
_START_RE = re.compile(r"^mbell_([1-9][0-9]{0,8})$")
REMIND_AHEAD = timedelta(hours=3)
# Итог шлём, пока он свежий; старый матч подписчику не напоминаем.
FRESH = timedelta(hours=24)

KIND_REMIND = "remind"
KIND_MOVED = "moved"
KIND_RESULT = "result"
KIND_CANCEL = "cancel"


def parse_bell_start(payload: str | None) -> int | None:
    """``mbell_42`` → 42; всё остальное, включая ``watch_42`` и ``mbell_42_x``, → ``None``."""
    found = _START_RE.match((payload or "").strip())
    return int(found.group(1)) if found else None


def off_data(match_id: int) -> str:
    return f"{OFF_PREFIX}{int(match_id)}"


def parse_off_data(data: str | None) -> int | None:
    raw = (data or "")
    if not raw.startswith(OFF_PREFIX):
        return None
    tail = raw[len(OFF_PREFIX):]
    return int(tail) if tail.isdigit() and 0 < int(tail) < 2**31 else None


# ── Тексты ───────────────────────────────────────────────────────────


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _title(row: Any) -> str:
    return f"{html.escape(row.home_team)} — {html.escape(row.away_team)}"


def _when(starts_at: datetime) -> str:
    loc = site_matches.local(starts_at)
    return f"{site_matches.WEEKDAYS_SHORT[loc.weekday()]}, {loc.day} {site_matches.MONTHS_GEN[loc.month - 1]}, {loc:%H:%M}"


def _remind_time(starts_at: datetime) -> str:
    loc = site_matches.local(_utc(starts_at) - REMIND_AHEAD)
    return f"{loc:%H:%M}"


def subscribed_text(row: Any, *, now: datetime, already: bool) -> str:
    head = "Уже стоит" if already else "Готово"
    starts = _utc(row.starts_at)
    if now >= starts - REMIND_AHEAD:
        when = f"Матч {_title(row)} скоро — {_when(starts)}. Напомню в ближайшие минуты."
        return f"{head}: {when}"
    return (
        f"{head}: напомню о матче {_title(row)} — {_when(starts)}, "
        f"сообщение придёт в {_remind_time(starts)}, за 3 часа до начала. После матча пришлю счёт."
    )


def remind_text(row: Any, *, now: datetime, arena: str | None) -> str:
    starts = _utc(row.starts_at)
    left = starts - now
    lead = "Через 3 часа" if left >= timedelta(hours=2, minutes=40) else "Скоро"
    place = f", {html.escape(arena)}" if arena else ""
    return f"<b>{lead}:</b> {_title(row)}, {site_matches.local(starts):%H:%M}{place}."


def moved_text(row: Any) -> str:
    return f"Матч {_title(row)} перенесён: теперь {_when(row.starts_at)}. Напомню за 3 часа."


def result_text(row: Any) -> str:
    score = site_matches.score_text(
        {"home_score": row.home_score, "away_score": row.away_score, "decided_in": row.decided_in}
    )
    return f"<b>{_title(row)} {score}.</b> Матч закончился."


def cancel_text(row: Any) -> str:
    return f"Матч {_title(row)} перенесён или отменён — напоминание снято. Уточните на hockey.by."


def past_text(row: Any) -> str:
    score = ""
    if row.home_score is not None:
        score = " " + site_matches.score_text(
            {"home_score": row.home_score, "away_score": row.away_score, "decided_in": row.decided_in}
        )
    return f"Матч {_title(row)} уже сыгран{score}. Подписаться можно на ближайшие матчи — их список на сайте."


# ── Подписка ─────────────────────────────────────────────────────────

_MATCH = text(f"""
    SELECT {site_matches._COLUMNS} FROM hockey_matches WHERE id = :id
    """)  # noqa: SLF001
_EXISTING = text("SELECT unsubscribed_at FROM hockey_match_bells WHERE telegram_id = :tg AND match_id = :mid")
_INSERT = text("""
    INSERT INTO hockey_match_bells (telegram_id, match_id, known_starts_at) VALUES (:tg, :mid, :starts)
    ON CONFLICT DO NOTHING RETURNING match_id
    """)
_RESUBSCRIBE = text("""
    UPDATE hockey_match_bells SET unsubscribed_at = NULL, known_starts_at = :starts
    WHERE telegram_id = :tg AND match_id = :mid AND unsubscribed_at IS NOT NULL
    """)
_UNSUBSCRIBE = text("""
    UPDATE hockey_match_bells SET unsubscribed_at = :now
    WHERE telegram_id = :tg AND match_id = :mid AND unsubscribed_at IS NULL RETURNING match_id
    """)


def in_scope(row: Any, scope: site_matches.Scope) -> bool:
    """Тот же предикат, что у страницы и ленты (``site_matches._SCOPE``): Динамо дома и в гостях."""
    return site_matches.in_scope(row, scope)


async def subscribe(
    session: AsyncSession,
    *,
    telegram_id: int,
    match_id: int,
    now: datetime,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Поставить колокольчик. ``None`` — матча на сайте нет (чужой id, клуб не включён): обычное приветствие.

    Ответ: ``{"text", "state", "match_id", "path"}``; ``state``: ``new`` | ``already`` | ``closed`` (подписки нет).
    """
    cfg = settings or Settings()  # type: ignore[call-arg]
    scope = site_matches.scope_of(cfg)
    if scope.empty:
        return None
    row = (await session.execute(_MATCH, {"id": int(match_id)})).one_or_none()
    if row is None or not in_scope(row, scope):
        return None
    mid = int(match_id)
    if site_matches.hidden(row):
        return {"text": cancel_text(row), "state": "closed", "match_id": mid, "path": None}
    if site_matches.phase_of(row, now) == site_matches.PHASE_AFTER:
        return {"text": past_text(row), "state": "closed", "match_id": mid, "path": site_matches.match_path(row)}
    params = {"tg": int(telegram_id), "mid": mid, "starts": _utc(row.starts_at)}
    existing = (await session.execute(_EXISTING, params)).one_or_none()
    if existing is None:
        created = (await session.execute(_INSERT, params)).first() is not None
        already = not created  # параллельный второй клик успел раньше
    elif existing.unsubscribed_at is not None:
        await session.execute(_RESUBSCRIBE, params)
        already = False
    else:
        already = True
    return {
        "text": subscribed_text(row, now=now, already=already),
        "state": "already" if already else "new",
        "match_id": mid,
        "path": site_matches.match_path(row),
    }


async def unsubscribe(session: AsyncSession, *, telegram_id: int, match_id: int, now: datetime) -> bool:
    """Снять колокольчик одной кнопкой. ``False`` — уже снят (повторное нажатие)."""
    params = {"tg": int(telegram_id), "mid": int(match_id), "now": _utc(now)}
    return (await session.execute(_UNSUBSCRIBE, params)).first() is not None


# ── Доставка ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Notice:
    kind: str
    telegram_id: int
    match_id: int
    text: str
    buttons: list[list[dict]]
    starts_at: datetime
    known_starts_at: datetime | None


_DUE = text(f"""
    SELECT b.telegram_id, b.match_id, b.known_starts_at, b.remind_for,
           {", ".join("m." + c.strip() for c in site_matches._COLUMNS.split(",") if c.strip() and c.strip() != "id")}
    FROM hockey_match_bells b
    JOIN hockey_matches m ON m.id = b.match_id
    WHERE b.unsubscribed_at IS NULL AND b.result_claimed_at IS NULL AND m.starts_at > :recent
    ORDER BY m.starts_at, b.telegram_id
    """)  # noqa: SLF001
_CLAIM_REMIND = text("""
    UPDATE hockey_match_bells SET remind_for = :starts, remind_claimed_at = :now, remind_sent_at = NULL
    WHERE telegram_id = :tg AND match_id = :mid AND unsubscribed_at IS NULL
      AND remind_for IS DISTINCT FROM :starts
    RETURNING match_id
    """)
_CLAIM_MOVED = text("""
    UPDATE hockey_match_bells SET known_starts_at = :starts
    WHERE telegram_id = :tg AND match_id = :mid AND unsubscribed_at IS NULL
      AND known_starts_at IS NOT DISTINCT FROM :known
    RETURNING match_id
    """)
_CLAIM_RESULT = text("""
    UPDATE hockey_match_bells SET result_claimed_at = :now
    WHERE telegram_id = :tg AND match_id = :mid AND unsubscribed_at IS NULL AND result_claimed_at IS NULL
    RETURNING match_id
    """)
_SENT_REMIND = text("UPDATE hockey_match_bells SET remind_sent_at = :now WHERE telegram_id = :tg AND match_id = :mid")
_SENT_RESULT = text("UPDATE hockey_match_bells SET result_sent_at = :now WHERE telegram_id = :tg AND match_id = :mid")
_DROP_ALL = text("UPDATE hockey_match_bells SET unsubscribed_at = :now WHERE telegram_id = :tg AND unsubscribed_at IS NULL")

Sender = Callable[[int, str, list[list[dict]]], Awaitable[str]]
SENT_OK = "ok"
SENT_BLOCKED = "blocked"
SENT_ERROR = "error"


def _buttons(row: Any, *, base_url: str, off: bool = True) -> list[list[dict]]:
    out: list[list[dict]] = []
    if base_url.lower().startswith("https://"):
        out.append([{"text": "Открыть матч", "url": f"{base_url}{site_matches.match_path(row)}"}])
    if off:
        out.append([{"text": "Отписаться", "callback_data": off_data(int(row.id))}])
    return out


async def due_notices(
    session: AsyncSession, *, now: datetime, settings: Settings | None = None
) -> list[Notice]:
    """Что пора отправить. Ничего не пишет; одно сообщение на подписку за тик."""
    cfg = settings or Settings()  # type: ignore[call-arg]
    scope = site_matches.scope_of(cfg)
    if scope.empty:
        return []
    base = (cfg.webapp_base_url or "").strip().rstrip("/")
    out: list[Notice] = []
    for r in (await session.execute(_DUE, {"recent": now - FRESH})).all():
        if not in_scope(r, scope):
            continue
        starts = _utc(r.starts_at)
        row = _Row(r, id=int(r.match_id))
        common = {"telegram_id": int(r.telegram_id), "match_id": int(r.match_id), "starts_at": starts, "known_starts_at": r.known_starts_at}
        if site_matches.hidden(r):
            out.append(Notice(KIND_CANCEL, text=cancel_text(r), buttons=[], **common))
        elif r.status == STATUS_FINAL and r.home_score is not None:
            if starts > now - FRESH:
                out.append(Notice(KIND_RESULT, text=result_text(r), buttons=_buttons(row, base_url=base, off=False), **common))
        elif now < starts:
            known = _utc(r.known_starts_at) if r.known_starts_at is not None else None
            if known is not None and known != starts:
                out.append(Notice(KIND_MOVED, text=moved_text(r), buttons=_buttons(row, base_url=base), **common))
            elif starts - REMIND_AHEAD <= now and (r.remind_for is None or _utc(r.remind_for) != starts):
                arena, _city = site_matches.place_of(r)
                out.append(
                    Notice(KIND_REMIND, text=remind_text(r, now=now, arena=arena), buttons=_buttons(row, base_url=base), **common)
                )
    return out


class _Row:
    """Строка подписки с полями матча для ``match_path``: ему нужны id и команды."""

    def __init__(self, r: Any, *, id: int) -> None:  # noqa: A002
        self.id = id
        self.home_team = r.home_team
        self.away_team = r.away_team


async def claim(session: AsyncSession, notice: Notice, *, now: datetime) -> bool:
    params = {"tg": notice.telegram_id, "mid": notice.match_id, "now": _utc(now), "starts": _utc(notice.starts_at)}
    if notice.kind == KIND_REMIND:
        return (await session.execute(_CLAIM_REMIND, params)).first() is not None
    if notice.kind == KIND_MOVED:
        known = _utc(notice.known_starts_at) if notice.known_starts_at is not None else None
        return (await session.execute(_CLAIM_MOVED, {**params, "known": known})).first() is not None
    return (await session.execute(_CLAIM_RESULT, params)).first() is not None


async def mark_sent(session: AsyncSession, notice: Notice, *, now: datetime) -> None:
    params = {"tg": notice.telegram_id, "mid": notice.match_id, "now": _utc(now)}
    if notice.kind == KIND_REMIND:
        await session.execute(_SENT_REMIND, params)
    elif notice.kind in (KIND_RESULT, KIND_CANCEL):
        await session.execute(_SENT_RESULT, params)


async def deliver(session_factory, *, now: datetime, send: Sender) -> dict[str, int]:
    """Занять — закоммитить — отправить — отметить. Каждое сообщение — своя короткая транзакция."""
    counts = {"sent": 0, "failed": 0, "blocked": 0}
    async with session_factory() as session:
        notices = await due_notices(session, now=now)
    for notice in notices:
        async with session_factory() as session:
            if not await claim(session, notice, now=now):
                continue
            await session.commit()
        try:
            result = await send(notice.telegram_id, notice.text, notice.buttons)
        except Exception:  # noqa: BLE001 — сбой одного сообщения не роняет остальные
            logger.warning("match bell %s/%s failed", notice.kind, notice.match_id, exc_info=True)
            result = SENT_ERROR
        async with session_factory() as session:
            if result == SENT_OK:
                await mark_sent(session, notice, now=now)
            elif result == SENT_BLOCKED:
                # Бот заблокирован: все подписки человека снимаем, повторов не будет.
                await session.execute(_DROP_ALL, {"tg": notice.telegram_id, "now": _utc(now)})
            await session.commit()
        counts["sent" if result == SENT_OK else "blocked" if result == SENT_BLOCKED else "failed"] += 1
    return counts


async def send_bell(chat_id: int, text_body: str, buttons: list[list[dict]]) -> str:
    """Личное сообщение клиентским ботом. 403 (бот заблокирован) отличаем от прочих сбоев."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.exceptions import TelegramForbiddenError
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    token = (Settings().telegram_bot_token_client or "").strip()  # type: ignore[call-arg]
    if not token:
        return SENT_ERROR
    markup = (
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=b["text"], url=b.get("url"), callback_data=b.get("callback_data"))
                    for b in row
                ]
                for row in buttons
            ]
        )
        if buttons
        else None
    )
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await bot.send_message(chat_id=int(chat_id), text=text_body, reply_markup=markup)
        return SENT_OK
    except TelegramForbiddenError:
        return SENT_BLOCKED
    except Exception:  # noqa: BLE001 — BadRequest и сеть: без повторов, цикл жив
        logger.info("match bell to %s not delivered", chat_id, exc_info=True)
        return SENT_ERROR
    finally:
        await bot.session.close()


def reply_buttons(result: dict[str, Any], *, base_url: str) -> list[list[dict]]:
    """Кнопки ответа на ``/start``: открыть матч и отписаться (одной кнопкой)."""
    rows: list[list[dict]] = []
    if result.get("path") and base_url.lower().startswith("https://"):
        rows.append([{"text": "Открыть матч", "url": f"{base_url}{result['path']}"}])
    if result["state"] in ("new", "already"):
        rows.append([{"text": "Отписаться", "callback_data": off_data(result["match_id"])}])
    return rows


__all__ = [
    "BELL_PREFIX",
    "OFF_PREFIX",
    "deliver",
    "due_notices",
    "off_data",
    "parse_bell_start",
    "parse_off_data",
    "reply_buttons",
    "send_bell",
    "subscribe",
    "unsubscribe",
]
