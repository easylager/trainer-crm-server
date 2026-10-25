"""Сезонная рассылка клиентам Минска: старт сезона и «Лёд на выходные».

Шкала дня — общие правила TASK-290 (scope='all', характер steady).
Отправка идёт через клиентский бот; 403 и прочие ошибки пишутся в лог и не
останавливают остальных.
"""
from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal, Sequence
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.session_load import (
    LEVEL_BUSY,
    LEVEL_CALM,
    LEVEL_MEDIUM,
    LoadLevel,
    LoadRule,
    resolve_level,
)
from src.shared.config import Settings

logger = logging.getLogger(__name__)

MINSK_TZ = ZoneInfo("Europe/Minsk")
SEASON_START_KEY = "season_start_2026"
OPT_OUT_KIND = "ice_forecast"
OPT_OUT_CALLBACK = "ice_forecast:optout"
SEND_DELAY_SEC = 0.05
ALL_SESSIONS_LABEL = "⛸ Все сеансы"
OPT_OUT_LABEL = "🔕 Не присылать прогноз"
OPT_OUT_TOAST = "Больше не пришлём"
ICE_WEBAPP_PATH = "/webapp/ice"

CampaignKind = Literal["season_start", "weekly"]

_LEVEL_RANK = {LEVEL_CALM: 0, LEVEL_MEDIUM: 1, LEVEL_BUSY: 2}
_PARTS: tuple[tuple[str, time, time, time | None], ...] = (
    # name, sample, window start inclusive, window end exclusive (None = end of day)
    ("утро", time(10, 0), time(6, 0), time(12, 0)),
    ("день", time(14, 0), time(12, 0), time(17, 0)),
    ("вечер", time(19, 0), time(17, 0), None),
)
_GREEN = ("лёд почти ваш", "тихо и просторно")
_RED = ("весь город на катке", "самый разгар")
_DAY_TITLE = {5: "Суббота", 6: "Воскресенье"}
_DAY_SHORT = {5: "сб", 6: "вс"}

SHORT_ARENA_NAMES = {
    "zamok": "Замок",
    "chizhovka": "Чижовка",
    "konkobezhnaya-arena": "Конькобежный",
    "katok-na-nemige-u-dvortsa-sporta": "Немига",
    "ledby": "ЛДС",
}

SEASON_START_TEXT = (
    "⛸ <b>Сезон льда начинается!</b>\n"
    "\n"
    "Катки Минска выходят на полную — вечера и выходные заполняются первыми. "
    "Совет на сезон: на эти часы берите билет заранее.\n"
    "\n"
    "Онлайн это можно сделать здесь 👇\n"
    "\n"
    "А по четвергам будем присылать короткий прогноз: "
    "когда лёд почти ваш, а когда на катке весь город."
)
_FORECAST_CLOSING = "На красные часы билет лучше взять заранее 👇"


@dataclass(frozen=True)
class TicketArena:
    slug: str
    name: str
    tickets_url: str


@dataclass(frozen=True)
class SaleSlot:
    arena_name: str
    local_date: date
    starts_at: time
    capacity: int
    sold: int
    held: int


@dataclass(frozen=True)
class ForecastMessage:
    campaign_key: str
    text: str
    markup: InlineKeyboardMarkup | None
    audience_size: int


def in_forecast_season(day: date) -> bool:
    """26 октября – 15 февраля, через Новый год: выходные в Замке раскупают уже с конца октября."""
    if day.month == 10:
        return day.day >= 26
    if day.month in (11, 12):
        return True
    if day.month == 1:
        return True
    if day.month == 2:
        return day.day <= 15
    return False


def ice_forecast_due(now: datetime, *, enabled: bool) -> bool:
    """Четверг 18:00–20:00 Europe/Minsk внутри сезона, и только если флаг включён."""
    if not enabled:
        return False
    local = now.astimezone(MINSK_TZ) if now.tzinfo is not None else now
    day = local.date()
    if day.weekday() != 3 or not in_forecast_season(day):
        return False
    clock = local.time().replace(second=0, microsecond=0)
    return time(18, 0) <= clock < time(20, 0)


def weekend_for(day: date) -> tuple[date, date]:
    """Суббота и воскресенье той недели, к которой относится day (пн–вс)."""
    saturday = day + timedelta(days=5 - day.weekday())
    return saturday, saturday + timedelta(days=1)


def weekly_campaign_key(day: date) -> str:
    thursday = weekend_for(day)[0] - timedelta(days=2)
    iso = thursday.isocalendar()
    return f"ice_forecast_{iso.year}-W{iso.week:02d}"


def campaign_key_for(kind: CampaignKind, day: date) -> str:
    if kind == "season_start":
        return SEASON_START_KEY
    return weekly_campaign_key(day)


def season_window(day: date) -> tuple[date, date]:
    return day, day + timedelta(days=6)


def ru_tickets(count: int) -> str:
    n = abs(int(count))
    if n % 100 in (11, 12, 13, 14):
        return "билетов"
    last = n % 10
    if last == 1:
        return "билет"
    if last in (2, 3, 4):
        return "билета"
    return "билетов"


def _part_index(name: str) -> int:
    for i, (part_name, *_rest) in enumerate(_PARTS):
        if part_name == name:
            return i
    return 0


def levels_for_day(rules: Sequence[LoadRule], day: date) -> tuple[LoadLevel, LoadLevel, LoadLevel]:
    """Уровень утро/день/вечер по общим правилам и характеру steady."""
    shared = tuple(rule for rule in rules if rule.scope == "all")
    levels: list[LoadLevel] = []
    for _name, sample, _start, _end in _PARTS:
        levels.append(
            resolve_level(
                shared,
                arena_id=0,
                character="steady",
                local_weekday=day.weekday(),
                starts_at_local=sample,
            )
        )
    return (levels[0], levels[1], levels[2])


def red_windows(levels: tuple[LoadLevel, LoadLevel, LoadLevel]) -> list[tuple[time, time | None]]:
    """Окна частей дня, которые в прогнозе отмечены 🔴."""
    lines = _day_marks(levels)
    windows: list[tuple[time, time | None]] = []
    for name, emoji, _phrase_slot in lines:
        if emoji != "🔴":
            continue
        _part, _sample, start, end = _PARTS[_part_index(name)]
        windows.append((start, end))
    return windows


def _day_marks(
    levels: tuple[LoadLevel, LoadLevel, LoadLevel],
) -> list[tuple[str, str, Literal["green", "red"]]]:
    """Самая свободная часть, если она calm, и самая людная, если она busy.

    При равенстве свободнее — более ранняя часть, люднее — более поздняя.
    Так два busy в субботу (день и вечер) сходятся в один 🔴 вечер.
    """
    ranked = list(enumerate(levels))
    freest = min(ranked, key=lambda item: (_LEVEL_RANK[item[1]], item[0]))
    busiest = max(ranked, key=lambda item: (_LEVEL_RANK[item[1]], item[0]))
    chosen: dict[int, Literal["green", "red"]] = {}
    if freest[1] == LEVEL_CALM:
        chosen[freest[0]] = "green"
    if busiest[1] == LEVEL_BUSY:
        chosen[busiest[0]] = "red"
    marks: list[tuple[str, str, Literal["green", "red"]]] = []
    for index, kind in sorted(chosen.items()):
        emoji = "🟢" if kind == "green" else "🔴"
        marks.append((_PARTS[index][0], emoji, kind))
    return marks


def render_forecast(
    saturday: tuple[LoadLevel, LoadLevel, LoadLevel],
    sunday: tuple[LoadLevel, LoadLevel, LoadLevel],
    live: str | None = None,
) -> str | None:
    """Текст «Лёд на выходные». None — за выходные нет ни одного 🔴, слать нечего."""
    days = ((5, saturday), (6, sunday))
    rendered: list[tuple[int, list[tuple[str, str, Literal["green", "red"]]]]] = []
    red_count = 0
    for weekday, levels in days:
        marks = _day_marks(levels)
        if not marks:
            continue
        red_count += sum(1 for _name, emoji, _kind in marks if emoji == "🔴")
        rendered.append((weekday, marks))
    if red_count == 0:
        return None

    green_i = 0
    red_i = 0
    blocks: list[str] = ["🧊 <b>Лёд на выходные</b>", ""]
    for weekday, marks in rendered:
        blocks.append(f"<b>{_DAY_TITLE[weekday]}</b>")
        for name, emoji, kind in marks:
            if kind == "green":
                phrase = _GREEN[green_i % len(_GREEN)]
                green_i += 1
            else:
                phrase = _RED[red_i % len(_RED)]
                red_i += 1
            blocks.append(f"{emoji} {name} — {phrase}")
        blocks.append("")
    if live:
        blocks.append(live)
    blocks.append(_FORECAST_CLOSING)
    return "\n".join(blocks)


def live_line_from_slots(
    slots: Sequence[SaleSlot],
    *,
    saturday: date,
    sunday: date,
    saturday_levels: tuple[LoadLevel, LoadLevel, LoadLevel],
    sunday_levels: tuple[LoadLevel, LoadLevel, LoadLevel],
) -> str | None:
    """Сеанс с наименьшей долей остатка среди 🔴 часов, если остаток > 0 и ≤ 30%."""
    windows = {
        saturday: red_windows(saturday_levels),
        sunday: red_windows(sunday_levels),
    }
    best: tuple[SaleSlot, int] | None = None
    for slot in slots:
        if slot.local_date not in windows or slot.capacity <= 0:
            continue
        if not _starts_in_windows(slot.starts_at, windows[slot.local_date]):
            continue
        left = slot.capacity - slot.sold - slot.held
        if left <= 0 or left * 100 > slot.capacity * 30:
            continue
        if best is None or _tighter(left, slot.capacity, slot, best[0]):
            best = (slot, left)
    if best is None:
        return None
    slot, left = best
    when = _DAY_SHORT.get(slot.local_date.weekday(), "")
    clock = slot.starts_at.strftime("%H:%M")
    name = html.escape(slot.arena_name)
    return f"В {name} на {when} {clock} осталось {left} {ru_tickets(left)}."


def _tighter(left: int, capacity: int, slot: SaleSlot, other: SaleSlot) -> bool:
    other_left = other.capacity - other.sold - other.held
    # left/capacity < other_left/other.capacity
    if left * other.capacity != other_left * capacity:
        return left * other.capacity < other_left * capacity
    if slot.starts_at != other.starts_at:
        return slot.starts_at < other.starts_at
    return slot.arena_name < other.arena_name


def _starts_in_windows(starts_at: time, windows: Sequence[tuple[time, time | None]]) -> bool:
    clock = starts_at.replace(tzinfo=None)
    for start, end in windows:
        if clock < start:
            continue
        if end is None or clock < end:
            return True
    return False


def button_label(slug: str, name: str) -> str:
    short = SHORT_ARENA_NAMES.get(slug) or name
    return f"🎟 {short}"


def build_forecast_markup(
    arenas: Sequence[TicketArena],
    *,
    webapp_base_url: str,
    opt_out: bool,
) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    ticket_buttons = [
        InlineKeyboardButton(text=button_label(arena.slug, arena.name), url=arena.tickets_url)
        for arena in arenas
        if (arena.tickets_url or "").strip()
    ]
    for offset in range(0, len(ticket_buttons), 3):
        rows.append(ticket_buttons[offset : offset + 3])
    base = (webapp_base_url or "").rstrip("/")
    if base.lower().startswith("https://"):
        rows.append(
            [
                InlineKeyboardButton(
                    text=ALL_SESSIONS_LABEL,
                    web_app=WebAppInfo(url=f"{base}{ICE_WEBAPP_PATH}"),
                )
            ]
        )
    if opt_out:
        rows.append(
            [InlineKeyboardButton(text=OPT_OUT_LABEL, callback_data=OPT_OUT_CALLBACK)]
        )
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def markup_without_optout(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    if markup is None:
        return None
    rows = []
    for row in markup.inline_keyboard:
        if any(button.callback_data == OPT_OUT_CALLBACK for button in row):
            continue
        rows.append(row)
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def describe_markup(markup: InlineKeyboardMarkup | None) -> list[str]:
    if markup is None:
        return []
    lines: list[str] = []
    for row in markup.inline_keyboard:
        parts: list[str] = []
        for button in row:
            if button.web_app is not None:
                parts.append(f"{button.text} → webapp {button.web_app.url}")
            elif button.url:
                parts.append(f"{button.text} → {button.url}")
            elif button.callback_data:
                parts.append(f"{button.text} → callback {button.callback_data}")
            else:
                parts.append(button.text)
        lines.append(" | ".join(parts))
    return lines


async def _minsk_city_id(session: AsyncSession) -> int | None:
    city_id = (
        await session.execute(
            text(
                """
                SELECT id FROM cities
                WHERE country = 'BY' AND name = 'Минск'
                ORDER BY id
                LIMIT 1
                """
            )
        )
    ).scalar_one_or_none()
    return int(city_id) if city_id is not None else None


async def fetch_forecast_audience(
    session: AsyncSession,
    *,
    respect_optout: bool,
) -> list[int]:
    """Telegram-id клиентского бота с городом Минск.

    Пул: не-sandbox клиенты, члены семейного доступа и все, кто открывал клиентский
    бот (client_sessions). Город — из client_sessions; пустой город — только если
    у клиента с этим telegram_id есть запись на арене Минска.
    """
    rows = (
        await session.execute(
            text(
                """
                WITH minsk AS (
                    SELECT id FROM cities
                    WHERE country = 'BY' AND name = 'Минск'
                    ORDER BY id
                    LIMIT 1
                ),
                pool AS (
                    SELECT telegram_id
                    FROM clients
                    WHERE telegram_id IS NOT NULL
                      AND is_sandbox = false
                    UNION
                    SELECT member_telegram_id
                    FROM client_family_access_members
                    UNION
                    -- Открывал клиентский бот, но к тренеру не записывался — это и есть
                    -- аудитория каталога. Без них рассылка шла бы только тем, кто уже клиент.
                    SELECT telegram_id
                    FROM client_sessions
                )
                SELECT p.telegram_id
                FROM pool p
                LEFT JOIN client_sessions cs ON cs.telegram_id = p.telegram_id
                WHERE (
                    cs.city_id = (SELECT id FROM minsk)
                    OR (
                        cs.city_id IS NULL
                        AND EXISTS (
                            SELECT 1
                            FROM clients c
                            JOIN bookings b ON b.client_id = c.id
                            JOIN arenas a ON a.id = b.arena_id
                            WHERE c.telegram_id = p.telegram_id
                              AND c.is_sandbox = false
                              AND a.city_id = (SELECT id FROM minsk)
                        )
                    )
                )
                -- Демо-клиент тренера (sandbox) рассылку не получает, даже если открывал бот.
                AND NOT (
                    EXISTS (SELECT 1 FROM clients sc WHERE sc.telegram_id = p.telegram_id AND sc.is_sandbox)
                    AND NOT EXISTS (
                        SELECT 1 FROM clients rc WHERE rc.telegram_id = p.telegram_id AND NOT rc.is_sandbox
                    )
                )
                AND (
                    NOT :respect_optout
                    OR NOT EXISTS (
                        SELECT 1 FROM client_broadcast_optouts o
                        WHERE o.telegram_id = p.telegram_id
                          AND o.kind = :kind
                    )
                )
                ORDER BY p.telegram_id
                """
            ),
            {"respect_optout": respect_optout, "kind": OPT_OUT_KIND},
        )
    ).scalars().all()
    return [int(tid) for tid in rows]


async def list_ticket_arenas(
    session: AsyncSession,
    *,
    start: date,
    end: date,
) -> list[TicketArena]:
    """Кассы Минска: есть tickets_url и сеанс public_skate/open_ice в окне."""
    rows = (
        await session.execute(
            text(
                """
                SELECT ap.slug, a.name, ap.tickets_url
                FROM arenas a
                JOIN arena_profiles ap ON ap.arena_id = a.id
                JOIN cities c ON c.id = a.city_id
                WHERE c.country = 'BY'
                  AND c.name = 'Минск'
                  AND COALESCE(btrim(ap.tickets_url), '') <> ''
                  AND EXISTS (
                      SELECT 1 FROM ice_sessions s
                      WHERE s.arena_id = a.id
                        AND s.status = 'active'
                        AND s.kind IN ('public_skate', 'open_ice')
                        AND s.local_date BETWEEN :start AND :end
                  )
                ORDER BY a.name, a.id
                """
            ),
            {"start": start, "end": end},
        )
    ).all()
    return [
        TicketArena(slug=str(row[0]), name=str(row[1]), tickets_url=str(row[2]))
        for row in rows
    ]


async def load_sale_slots(
    session: AsyncSession,
    *,
    saturday: date,
    sunday: date,
) -> list[SaleSlot]:
    """Последний снимок продаж на каждый сеанс выходных."""
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT ON (s.arena_id, s.local_date, s.starts_at_local)
                    a.name,
                    s.local_date,
                    s.starts_at_local,
                    snap.capacity,
                    snap.sold,
                    snap.held
                FROM ice_sessions s
                JOIN arenas a ON a.id = s.arena_id
                JOIN cities c ON c.id = a.city_id
                JOIN ice_sales_snapshots snap
                  ON snap.arena_id = s.arena_id
                 AND snap.local_date = s.local_date
                 AND snap.starts_at_local = s.starts_at_local
                WHERE c.country = 'BY'
                  AND c.name = 'Минск'
                  AND s.status = 'active'
                  AND s.kind IN ('public_skate', 'open_ice')
                  AND s.local_date IN (:saturday, :sunday)
                ORDER BY s.arena_id, s.local_date, s.starts_at_local, snap.observed_at DESC
                """
            ),
            {"saturday": saturday, "sunday": sunday},
        )
    ).all()
    slots: list[SaleSlot] = []
    for row in rows:
        starts = row[2]
        if isinstance(starts, datetime):
            starts = starts.time()
        slots.append(
            SaleSlot(
                arena_name=str(row[0]),
                local_date=row[1],
                starts_at=starts.replace(tzinfo=None) if isinstance(starts, time) else time(0, 0),
                capacity=int(row[3]),
                sold=int(row[4]),
                held=int(row[5]),
            )
        )
    return slots


async def _shared_rules(session: AsyncSession) -> tuple[LoadRule, ...]:
    from src.application.session_load import load_session_load_context

    ctx = await load_session_load_context(session)
    return tuple(rule for rule in ctx.rules if rule.scope == "all")


async def build_campaign_message(
    session: AsyncSession,
    kind: CampaignKind,
    *,
    on: date,
    settings: Settings,
    audience_size: int,
) -> ForecastMessage | None:
    key = campaign_key_for(kind, on)
    if kind == "season_start":
        start, end = season_window(on)
        arenas = await list_ticket_arenas(session, start=start, end=end)
        markup = build_forecast_markup(
            arenas,
            webapp_base_url=settings.webapp_base_url,
            opt_out=False,
        )
        return ForecastMessage(
            campaign_key=key,
            text=SEASON_START_TEXT,
            markup=markup,
            audience_size=audience_size,
        )

    saturday, sunday = weekend_for(on)
    rules = await _shared_rules(session)
    sat_levels = levels_for_day(rules, saturday)
    sun_levels = levels_for_day(rules, sunday)
    slots = await load_sale_slots(session, saturday=saturday, sunday=sunday)
    live = live_line_from_slots(
        slots,
        saturday=saturday,
        sunday=sunday,
        saturday_levels=sat_levels,
        sunday_levels=sun_levels,
    )
    body = render_forecast(sat_levels, sun_levels, live)
    if body is None:
        return None
    arenas = await list_ticket_arenas(session, start=saturday, end=sunday)
    markup = build_forecast_markup(
        arenas,
        webapp_base_url=settings.webapp_base_url,
        opt_out=True,
    )
    return ForecastMessage(
        campaign_key=key,
        text=body,
        markup=markup,
        audience_size=audience_size,
    )


async def _already_logged(session: AsyncSession, campaign_key: str) -> set[int]:
    rows = (
        await session.execute(
            text(
                """
                SELECT telegram_id FROM client_broadcast_log
                WHERE campaign_key = :key
                """
            ),
            {"key": campaign_key},
        )
    ).scalars().all()
    return {int(tid) for tid in rows}


async def _write_log(
    session: AsyncSession,
    *,
    telegram_id: int,
    campaign_key: str,
    status: str,
    error: str | None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO client_broadcast_log (telegram_id, campaign_key, status, error)
            VALUES (:tid, :key, :status, :error)
            ON CONFLICT (telegram_id, campaign_key) DO NOTHING
            """
        ),
        {
            "tid": telegram_id,
            "key": campaign_key,
            "status": status,
            "error": error[:500] if error else None,
        },
    )
    # Сразу в журнал: упавший на середине прогон не должен прислать второе сообщение тем,
    # кто его уже получил.
    await session.commit()


async def send_ice_forecast(
    session: AsyncSession,
    bot: Bot | None,
    kind: CampaignKind,
    *,
    settings: Settings,
    on: date | None = None,
    dry_run: bool = False,
    only_telegram_id: int | None = None,
    send_delay_sec: float = SEND_DELAY_SEC,
) -> ForecastMessage | None:
    """Собрать и разослать кампанию. Повторный запуск не шлёт тем, кто уже в логе.

    dry_run ничего не пишет и не шлёт. only_telegram_id — превью одному адресату,
    лог кампании для него всё равно заполняется, чтобы полный прогон не продублировал.
    """
    day = on or datetime.now(MINSK_TZ).date()
    respect_optout = kind == "weekly"
    audience = await fetch_forecast_audience(session, respect_optout=respect_optout)
    message = await build_campaign_message(
        session,
        kind,
        on=day,
        settings=settings,
        audience_size=len(audience),
    )
    if message is None:
        logger.info("ice_forecast skip kind=%s on=%s: no busy hours", kind, day)
        return None
    if dry_run or bot is None:
        return message

    targets = [only_telegram_id] if only_telegram_id is not None else audience
    already = await _already_logged(session, message.campaign_key)
    pending = [tid for tid in targets if tid not in already]
    for index, telegram_id in enumerate(pending):
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=message.text,
                reply_markup=message.markup,
                disable_web_page_preview=True,
            )
            await _write_log(
                session,
                telegram_id=telegram_id,
                campaign_key=message.campaign_key,
                status="sent",
                error=None,
            )
        except TelegramForbiddenError as exc:
            await _write_log(
                session,
                telegram_id=telegram_id,
                campaign_key=message.campaign_key,
                status="failed",
                error=str(exc),
            )
            logger.info("ice_forecast blocked telegram_id=%s: %s", telegram_id, exc)
        except Exception as exc:
            await _write_log(
                session,
                telegram_id=telegram_id,
                campaign_key=message.campaign_key,
                status="failed",
                error=str(exc),
            )
            logger.warning("ice_forecast failed telegram_id=%s: %s", telegram_id, exc)
        if index + 1 < len(pending) and send_delay_sec > 0:
            await asyncio.sleep(send_delay_sec)
    return message


async def record_ice_forecast_optout(session: AsyncSession, telegram_id: int) -> None:
    await session.execute(
        text(
            """
            INSERT INTO client_broadcast_optouts (telegram_id, kind)
            VALUES (:tid, :kind)
            ON CONFLICT (telegram_id) DO NOTHING
            """
        ),
        {"tid": telegram_id, "kind": OPT_OUT_KIND},
    )


def format_dry_run(message: ForecastMessage | None, *, kind: CampaignKind, on: date) -> str:
    key = campaign_key_for(kind, on)
    if message is None:
        return f"campaign: {key}\naudience: 0\nskip: нет людных часов на выходных, сообщение не отправляется"
    lines = [
        f"campaign: {message.campaign_key}",
        f"audience: {message.audience_size}",
        "---",
        message.text,
        "---",
        "buttons:",
        *describe_markup(message.markup),
    ]
    return "\n".join(lines)
