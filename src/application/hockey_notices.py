"""Напоминания «Кто кого» в бот: за час до матча и итог после него (TASK-335).

Включает сам игрок, одним переключателем на все матчи Динамо. На матч — не больше двух сообщений:
«через час» и итог. Итог финала месяца говорит и про корону: гонка закрывается сразу после финала
(``hockey_races.close_due_races``). В каждом сообщении — «Не напоминать».

Сообщение сначала «занимается» строкой в ``hockey_notices`` и только потом уходит: второй цикл
или повтор тика не пришлёт его дважды. Сбой отправки (бот заблокирован) не повторяем.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_game import DEFAULT_PLAYER_NAME, POINTS_EXACT, race_window
from src.ingestion.hockey_sources import MINSK_TZ

logger = logging.getLogger(__name__)

REMIND_AHEAD = timedelta(hours=1)
# Итог шлём, пока он свежий: включивший напоминания не получит пачку старых матчей.
RESULT_FRESH = timedelta(hours=6)
KIND_BEFORE = "before"
KIND_RESULT = "result"

MONTHS_GEN = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

# Параметры ссылок в Mini App (glide-deeplink.js): ход за сторону, матчи, итоги месяца, выключить.
START_PICK = "kkn"
START_MONTH = "kkmo"
START_OFF = "kkoff"


@dataclass(frozen=True)
class Notice:
    kind: str
    player_key: int
    match_id: int
    text: str
    buttons: list[list[dict]]


Sender = Callable[[int, str, list[list[dict]]], Awaitable[bool]]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---------- настройка ----------

_REMIND = text("SELECT remind FROM hockey_player_prefs WHERE player_key = :player_key")

_ENSURE_PLAYER = text("""
    INSERT INTO hockey_players (player_key, display_name) VALUES (:player_key, :name)
    ON CONFLICT (player_key) DO NOTHING
    """)

_SET_REMIND = text("""
    INSERT INTO hockey_player_prefs (player_key, remind) VALUES (:player_key, :on)
    ON CONFLICT (player_key) DO UPDATE SET remind = EXCLUDED.remind, updated_at = now()
    """)


async def remind_on(session: AsyncSession, player_key: int) -> bool:
    return bool((await session.execute(_REMIND, {"player_key": player_key})).scalar_one_or_none())


async def set_remind(session: AsyncSession, player_key: int, on: bool, *, display_name: str = "") -> bool:
    name = (display_name or "").strip()[:40] or DEFAULT_PLAYER_NAME
    await session.execute(_ENSURE_PLAYER, {"player_key": player_key, "name": name})
    await session.execute(_SET_REMIND, {"player_key": player_key, "on": bool(on)})
    return bool(on)


# ---------- кому и что ----------

_DUE_BEFORE = text("""
    SELECT pr.player_key, m.id AS match_id, m.home_team, m.away_team, m.starts_at,
           p.side, p.home_score, p.away_score, COALESCE(p.doubled, false) AS doubled
    FROM hockey_player_prefs AS pr
    JOIN hockey_players AS pl ON pl.player_key = pr.player_key
    JOIN kk_matches AS m ON m.status = 'scheduled' AND m.starts_at > :now AND m.starts_at <= :until
    LEFT JOIN hockey_picks AS p ON p.match_id = m.id AND p.player_key = pr.player_key
    WHERE pr.remind
      AND NOT EXISTS (
          SELECT 1 FROM hockey_notices AS n
          WHERE n.player_key = pr.player_key AND n.match_id = m.id AND n.kind = 'before'
      )
    ORDER BY m.starts_at, pr.player_key
    """)

_DUE_RESULT = text("""
    SELECT p.player_key, m.id AS match_id, m.home_team, m.away_team, m.starts_at,
           m.home_score AS final_home, m.away_score AS final_away,
           p.side, p.home_score, p.away_score, p.doubled, p.points
    FROM hockey_picks AS p
    JOIN hockey_player_prefs AS pr ON pr.player_key = p.player_key AND pr.remind
    JOIN kk_matches AS m ON m.id = p.match_id AND m.status = 'final' AND m.finalized_at > :fresh
    WHERE p.points IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM hockey_notices AS n
          WHERE n.player_key = p.player_key AND n.match_id = m.id AND n.kind = 'result'
      )
    ORDER BY m.starts_at, p.player_key
    """)

_CLAIM = text("""
    INSERT INTO hockey_notices (player_key, match_id, kind) VALUES (:player_key, :match_id, :kind)
    ON CONFLICT DO NOTHING
    RETURNING player_key
    """)

_DONE = text("""
    UPDATE hockey_notices SET sent_at = CASE WHEN CAST(:ok AS BOOLEAN) THEN CAST(:now AS TIMESTAMPTZ) END, failed = NOT CAST(:ok AS BOOLEAN)
    WHERE player_key = :player_key AND match_id = :match_id AND kind = :kind
    """)


def _link(start_param: str) -> str | None:
    from src.application.place_links import telegram_open_link
    from src.shared.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    return telegram_open_link(
        client_bot_username=settings.client_bot_username,
        mini_app_short_name=settings.client_mini_app_short_name,
        main_mini_app=settings.client_bot_main_mini_app,
        start_param=start_param,
    )


def _buttons(rows: list[list[tuple[str, str]]]) -> list[list[dict]]:
    out = []
    for row in rows:
        built = [{"text": label, "url": url} for label, param in row if (url := _link(param))]
        if built:
            out.append(built)
    return out


def _hhmm(value: datetime) -> str:
    return _utc(value).astimezone(MINSK_TZ).strftime("%H:%M").lstrip("0").rjust(4, "0")


def _move(side: str | None, home: int | None, away: int | None, teams: dict[str, str]) -> str:
    if home is not None and away is not None:
        return f"{home}:{away}"
    return f"за {teams[side]}" if side else ""


def before_text(
    *,
    home: str,
    away: str,
    starts_at: datetime,
    side: str | None,
    home_score: int | None,
    away_score: int | None,
    doubled: bool,
    month_final: bool,
) -> str:
    local = _utc(starts_at).astimezone(MINSK_TZ)
    head = f"<b>Через час:</b> {html.escape(home)} — {html.escape(away)}, {_hhmm(starts_at)}."
    if month_final:
        head += f" Финал {MONTHS_GEN[local.month - 1]}."
    if not side:
        return head + "\nХода ещё нет — один тап, и ты в игре."
    move = _move(side, home_score, away_score, {"home": home, "away": away})
    return head + f"\nТвой ход — {html.escape(move)}{', ×2' if doubled else ''}. Поменять можно до начала."


def _points_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "очко"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "очка"
    return "очков"


def result_text(
    *,
    home: str,
    away: str,
    final_home: int,
    final_away: int,
    points: int,
    doubled: bool,
    place: tuple[str, int] | None,
    crown: str | None,
) -> str:
    """``points`` — базовые очки хода; ``crown`` — готовая строка про корону, если это был финал месяца."""
    total = points * (2 if doubled else 1)
    x2 = " с ×2" if doubled else ""
    if points == POINTS_EXACT:
        verdict = f"В точку: +{total}{x2}."
    elif points:
        verdict = f"+{total} {_points_word(total)}{x2}."
    else:
        verdict = "В этот раз мимо."
    out = f"<b>{html.escape(home)} — {html.escape(away)} {final_home}:{final_away}.</b> {verdict}"
    if crown:
        out += "\n" + crown
    elif place:
        out += f"\nВ «{html.escape(place[0])}» ты {place[1]}-й."
    return out


async def _best_place(session: AsyncSession, player_key: int, at: datetime) -> tuple[int, str, int] | None:
    from src.application.hockey_leagues import player_leagues

    leagues = [x for x in await player_leagues(session, player_key=player_key, now=at) if x.members > 1]
    if not leagues:
        return None
    best = min(leagues, key=lambda x: (x.my_rank, -x.my_points, x.id))
    return best.id, best.name, best.my_rank


async def _crown_line(session: AsyncSession, *, player_key: int, match_id: int, starts_at: datetime) -> str | None:
    """Итог финала месяца: у кого корона — в лучшей лиге игрока или в общей таблице."""
    from src.application.hockey_races import current_race, race_final_match_id, race_winners

    race = await current_race(session, now=starts_at)
    if race is None or race.closed_at is None or await race_final_match_id(session, race) != match_id:
        return None
    best = await _best_place(session, player_key, starts_at)
    league_id = best[0] if best else None
    winners = await race_winners(session, race_id=race.id, league_id=league_id)
    where = f"в «{html.escape(best[1])}»" if best else "в общей таблице"
    month = MONTHS_GEN[_utc(starts_at).astimezone(MINSK_TZ).month - 1]
    if any(w["player_key"] == player_key for w in winners):
        return f"Это был финал {month}: корона {where} — твоя."
    if winners:
        names = " и ".join(html.escape(w["display_name"]) for w in winners)
        return f"Это был финал {month}: корона {where} досталась: {names}."
    return f"Это был финал {month}: {where} без короны."


async def due_notices(session: AsyncSession, *, now: datetime) -> list[Notice]:
    """Что пора отправить: «через час» и свежие итоги. Ничего не пишет."""
    from src.application.hockey_races import current_race, race_final_match_id

    now = _utc(now)
    out: list[Notice] = []
    finals: dict[datetime, int | None] = {}
    for r in (await session.execute(_DUE_BEFORE, {"now": now, "until": now + REMIND_AHEAD})).all():
        since = race_window(r.starts_at).since
        if since not in finals:
            finals[since] = await race_final_match_id(session, await current_race(session, now=r.starts_at))
        text_body = before_text(
            home=r.home_team,
            away=r.away_team,
            starts_at=r.starts_at,
            side=r.side,
            home_score=r.home_score,
            away_score=r.away_score,
            doubled=r.doubled,
            month_final=finals[since] == r.match_id,
        )
        if r.side:
            rows = [[("Открыть матч", f"{START_PICK}_{r.match_id}")]]
        else:
            rows = [
                [
                    (f"За {r.home_team}", f"{START_PICK}_{r.match_id}_h"),
                    (f"За {r.away_team}", f"{START_PICK}_{r.match_id}_a"),
                ]
            ]
        rows.append([("Не напоминать", START_OFF)])
        out.append(Notice(KIND_BEFORE, r.player_key, r.match_id, text_body, _buttons(rows)))

    for r in (await session.execute(_DUE_RESULT, {"fresh": now - RESULT_FRESH})).all():
        crown = await _crown_line(session, player_key=r.player_key, match_id=r.match_id, starts_at=r.starts_at)
        best = None if crown else await _best_place(session, r.player_key, r.starts_at)
        text_body = result_text(
            home=r.home_team,
            away=r.away_team,
            final_home=r.final_home,
            final_away=r.final_away,
            points=r.points,
            doubled=r.doubled,
            place=(best[1], best[2]) if best else None,
            crown=crown,
        )
        if crown:
            race = await current_race(session, now=r.starts_at)
            first = ("Итоги месяца", f"{START_MONTH}_{race.id}") if race else ("Открыть игру", START_PICK)
        else:
            first = ("Открыть игру", f"{START_PICK}_{r.match_id}")
        rows = [[first], [("Не напоминать", START_OFF)]]
        out.append(Notice(KIND_RESULT, r.player_key, r.match_id, text_body, _buttons(rows)))
    return out


async def claim(session: AsyncSession, notice: Notice) -> bool:
    params = {"player_key": notice.player_key, "match_id": notice.match_id, "kind": notice.kind}
    return (await session.execute(_CLAIM, params)).first() is not None


async def mark_done(session: AsyncSession, notice: Notice, *, ok: bool, now: datetime) -> None:
    params = {"player_key": notice.player_key, "match_id": notice.match_id, "kind": notice.kind}
    await session.execute(_DONE, {**params, "ok": ok, "now": _utc(now)})


async def deliver(session_factory, *, now: datetime, send: Sender) -> dict[str, int]:
    """Занять — закоммитить — отправить — отметить. Каждое сообщение — своя короткая транзакция."""
    counts = {"sent": 0, "failed": 0}
    async with session_factory() as session:
        notices = await due_notices(session, now=now)
    for notice in notices:
        async with session_factory() as session:
            if not await claim(session, notice):
                continue
            await session.commit()
        try:
            ok = await send(notice.player_key, notice.text, notice.buttons)
        except Exception:  # noqa: BLE001 — сбой одного сообщения не роняет остальные
            logger.warning("kto-kogo notice %s/%s failed", notice.kind, notice.match_id, exc_info=True)
            ok = False
        async with session_factory() as session:
            await mark_done(session, notice, ok=ok, now=now)
            await session.commit()
        counts["sent" if ok else "failed"] += 1
    return counts


async def send_via_client_bot(chat_id: int, text_body: str, buttons: list[list[dict]]) -> bool:
    """Личное сообщение клиентским ботом. Заблокировал бота или не разрешил писать — ``False``."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from src.shared.config import Settings

    token = (Settings().telegram_bot_token_client or "").strip()  # type: ignore[call-arg]
    if not token:
        return False
    markup = (
        InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=b["text"], url=b["url"]) for b in row] for row in buttons]
        )
        if buttons
        else None
    )
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await bot.send_message(chat_id=int(chat_id), text=text_body, reply_markup=markup)
        return True
    except Exception:  # noqa: BLE001 — Forbidden/BadRequest: не повторяем
        logger.info("kto-kogo notice to %s not delivered", chat_id, exc_info=True)
        return False
    finally:
        await bot.session.close()


__all__ = [
    "KIND_BEFORE",
    "KIND_RESULT",
    "Notice",
    "REMIND_AHEAD",
    "START_MONTH",
    "START_OFF",
    "START_PICK",
    "before_text",
    "claim",
    "deliver",
    "due_notices",
    "mark_done",
    "remind_on",
    "result_text",
    "send_via_client_bot",
    "set_remind",
]
