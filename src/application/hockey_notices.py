"""Бот «Кто кого»: четыре повода написать игроку и ход прямо из чата (TASK-334 S6, PDEC-031).

Поводы, по убыванию важности:

* ``result`` — итог хода: очки и место. Единственный, что не считается в дневной бюджет;
  если за один проход итогов несколько, уходит одно сообщение-сводка.
* ``mfinal`` — последний матч месяца: «корона решится сегодня» (клуб игрока, последний матч месяца, 12:00 по Минску).
* ``overtook`` — тебя обошли в лиге.
* ``nomove`` — нет хода за 3 часа до матча «своей» команды.

Бюджет: не больше одного сообщения в день (сутки по Минску) на игрока, кроме итогов. Из повода, что
мог бы уйти в один проход, выбирается более важный; остальные в тот же день не уходят. Часы тишины
23:00–09:00 по Минску: ничего не шлём, итог откладывается до утра.

«Своя» команда — «болею за» из настроек, иначе клуб, за который игрок чаще всего ходил за последние
30 дней; без ходов поводов про команду нет. Включает сам игрок (``remind``), каждый тип отключается
отдельно; заблокировавшему бота больше не пишем, пока он снова не зайдёт.

Все правила допуска (тихие часы, бюджеты, блокировка, «не присылать», выключатели новых поводов) проверяет
один модуль — ``kk_notify_gate``; ``deliver`` зовёт его перед каждой отправкой (TASK-426).

Сообщение сначала «занимается» строкой в ``hockey_notices`` и только потом уходит: второй цикл
или повтор тика не пришлёт его дважды. Постоянный сбой (BadRequest) не повторяем; временный (429, сеть, 5xx) освобождает
строку, и сообщение уходит на следующем проходе — не более ``MAX_ATTEMPTS`` раз.

Ход из чата — тот же ``hockey_game.make_pick``, что у Mini App: срок закрытия и запись одни и те же.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_game import (
    DEFAULT_PLAYER_NAME,
    MONTHS,
    POINTS_EXACT,
    PICK_CLOSES_BEFORE,
    PicksClosed,
    make_pick,
    month_bounds,
)
from src.application.hockey_slices import (
    Period,
    club_scope,
    crown_eligible,
    month_period,
    season_period,
    slice_rows,
)
from src.application.hockey_slices_sql import SCOPE_SQL
from src.application.hockey_teams import display_name as club_name
from src.application.kk_notify_gate import (  # noqa: F401
    QUIET_FROM,
    QUIET_TO,
    admit,
    day_bounds,
    in_quiet_hours,
    lock_player,
)
from src.application.kk_notify_journal import UNKNOWN_PHASE, cleanup_journal, write_journal
from src.application.kk_notify_phase import load_one
from src.ingestion.hockey_sources import MINSK_TZ

logger = logging.getLogger(__name__)

KIND_NOMOVE = "nomove"
KIND_RESULT = "result"
KIND_OVERTOOK = "overtook"
KIND_MFINAL = "mfinal"
KIND_MOVED = "moved"
KIND_MOVED_FREE = "mvfree"
KIND_RESCORE = "rescore"  # итог поправили после рассылки: «Мы ошиблись с итогом…»
KIND_OUTFIT = "outfit"  # получателю: капитан выдаёт ему экипировку (TASK-432)
KIND_BEFORE = "before"  # прежнее «за час»: больше не шлём, записи остались в таблице
# Приоритет внутри дневного бюджета (меньше — важнее).
PRIORITY = {KIND_MFINAL: 0, KIND_OVERTOOK: 1, KIND_NOMOVE: 2}
# Короткие коды типов в callback_data (лимит Telegram — 64 байта).
TYPE_CODES = {
    "nm": KIND_NOMOVE,
    "rs": KIND_RESULT,
    "ot": KIND_OVERTOOK,
    "mf": KIND_MFINAL,
    "li": "lginvite",
    "of": KIND_OUTFIT,
}
CODE_OF = {v: k for k, v in TYPE_CODES.items()}
# Типы со своей колонкой, которых нет в настройках Mini App (``TYPE_COLUMN``): письма лиги и приглашение собрать лигу.
EXTRA_TYPE_COLUMN = {"league": "notify_league", "lginvite": "notify_lginvite", KIND_OUTFIT: "notify_outfit"}
TYPE_COLUMN = {
    KIND_NOMOVE: "notify_nomove",
    KIND_RESULT: "notify_result",
    KIND_OVERTOOK: "notify_overtook",
    KIND_MFINAL: "notify_mfinal",
}
TYPE_TITLES = {
    KIND_NOMOVE: "напоминания о ходе",
    KIND_RESULT: "итоги ходов",
    KIND_OVERTOOK: "«тебя обошли»",
    KIND_MFINAL: "«последний матч месяца»",
    "lginvite": "приглашения собрать лигу",
    KIND_OUTFIT: "экипировка от капитана",
}

NOMOVE_AHEAD = timedelta(hours=3)
# Напоминать о матче, который начнётся вот-вот, незачем: ход закрывается за минуту до старта.
NOMOVE_MIN_LEFT = timedelta(minutes=15)
FAN_WINDOW = timedelta(days=30)
# Итог шлём, пока он свежий; ночной итог, отложенный до 09:00, остаётся свежим и утром.
RESULT_FRESH = timedelta(hours=6)
RESULT_FRESH_AFTER_NIGHT = timedelta(hours=16)
# Итог уходит в чат не раньше, чем через столько после ``finalized_at``: ошибочный итог (15.11.2026 матч ушёл
# в итог в третьем периоде) успевают поймать и поправить до рассылки. Цикл в окне итога тикает раз в 2 минуты,
# так что 5 минут — это пара тиков для второго взгляда, а клиент ждёт итог на пять минут дольше, чем раньше.
RESULT_SEND_DELAY = timedelta(minutes=5)
MFINAL_FROM_HOUR = 12
# В «корону решится сегодня» зовём тех, у кого она ещё в досягаемости.
MFINAL_TOP = 3

# Параметры ссылок в Mini App (glide-deeplink.js).
START_PICK = "kkn"
START_MONTH = "kkmo"
START_OFF = "kkoff"
START_LEAGUE = "kkl"
START_EVENING = "kkv"  # kkv_<лига>_<ГГГГММДД> — «Вечер» лиги за игровой день (TASK-431)

# callback_data кнопок в чате.
CB_PICK = "kk:p"  # kk:p:<матч>:<h|a>
CB_NEXT = "kk:n"
CB_OFF = "kk:off"  # kk:off:<тип>
CB_LEAVE = "kk:lv"  # kk:lv:<лига>
CB_OUTFIT = "kk:o"  # kk:o:<лига>:<ггммдд>:<pid получателя>:<вещь> — выдача капитана в один тап (TASK-432)

SENT = "ok"
BLOCKED = "blocked"
FAILED = "failed"
GONE = "gone"  # чат не найден / аккаунт удалён: недостижим, трактуется как блокировка
RETRY = "retry"  # временный сбой (429, сеть, 5xx): сообщение не потеряно, повторим на следующем проходе
# Попыток на одно сообщение; счётчик в памяти процесса — дальше страхуют окна свежести и тишина.
MAX_ATTEMPTS = 5

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


@dataclass(frozen=True)
class Notice:
    kind: str
    player_key: int
    match_id: int
    text: str
    buttons: list[list[dict]]
    # Итоги, слитые в одну сводку: остальные матчи (каждый занимается отдельной строкой).
    also: tuple[int, ...] = field(default=())
    # Строка в hockey_notices уже есть (повод ставится событием, не сканом): claim пропускаем.
    preclaimed: bool = False
    # Фото к сообщению (путь к файлу): текст уходит подписью (sendPhoto). Только у новых поводов (TASK-431).
    photo: str | None = None

    @property
    def match_ids(self) -> tuple[int, ...]:
        return (self.match_id, *self.also)


@dataclass(frozen=True)
class Overtake:
    """В лиге ``league_id`` игрока ``player_key`` обошёл ``by_name``: теперь он на месте ``rank``."""

    league_id: int
    league_name: str
    player_key: int
    by_name: str
    rank: int
    anchor_match_id: int
    scope: tuple[str, tuple[str, ...]] = ("dinamo", ())
    starts_at: datetime | None = None
    ends_at: datetime | None = None


Sender = Callable[[int, str, list[list[dict]]], Awaitable["bool | str"]]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _local(value: datetime) -> datetime:
    return _utc(value).astimezone(MINSK_TZ)


# ---------- настройки ----------

_PREFS = text("""
    SELECT remind, fav_club, notify_nomove, notify_result, notify_overtook, notify_mfinal, notify_league,
           bot_blocked_at
    FROM hockey_player_prefs WHERE player_key = :player_key
    """)

_ENSURE_PLAYER = text("""
    INSERT INTO hockey_players (player_key, display_name) VALUES (:player_key, :name)
    ON CONFLICT (player_key) DO NOTHING
    """)

_SET_REMIND = text("""
    INSERT INTO hockey_player_prefs (player_key, remind) VALUES (:player_key, :on)
    ON CONFLICT (player_key) DO UPDATE SET remind = EXCLUDED.remind, updated_at = now()
    """)

_SET_TYPE = text("""
    INSERT INTO hockey_player_prefs (player_key) VALUES (:player_key) ON CONFLICT (player_key) DO NOTHING
    """)

_SET_FAV = text("""
    INSERT INTO hockey_player_prefs (player_key, fav_club) VALUES (:player_key, :club)
    ON CONFLICT (player_key) DO UPDATE SET fav_club = EXCLUDED.fav_club, updated_at = now()
    """)

# Строки настроек у игрока может не быть (тогда всё включено по умолчанию): блокировку записываем и в этом случае,
# иначе заблокировавшему продолжали бы писать (TASK-426, гарантия 8).
_MARK_BLOCKED = text("""
    INSERT INTO hockey_player_prefs (player_key, bot_blocked_at) VALUES (:player_key, :now)
    ON CONFLICT (player_key) DO UPDATE SET bot_blocked_at = EXCLUDED.bot_blocked_at, updated_at = now()
    """)

_CLEAR_BLOCKED = text("""
    UPDATE hockey_player_prefs SET bot_blocked_at = NULL, updated_at = now()
    WHERE player_key = :player_key AND bot_blocked_at IS NOT NULL
    """)


async def remind_on(session: AsyncSession, player_key: int) -> bool:
    row = (await session.execute(_PREFS, {"player_key": player_key})).one_or_none()
    return True if row is None else bool(row.remind)


async def set_remind(session: AsyncSession, player_key: int, on: bool, *, display_name: str = "") -> bool:
    """Главный выключатель бота. Включение — новый вход: снимает отметку «заблокировал бота»."""
    name = (display_name or "").strip()[:40] or DEFAULT_PLAYER_NAME
    await session.execute(_ENSURE_PLAYER, {"player_key": player_key, "name": name})
    await session.execute(_SET_REMIND, {"player_key": player_key, "on": bool(on)})
    if on:
        await clear_blocked(session, player_key)
    return bool(on)


_SET_CONSENT = text("""
    INSERT INTO hockey_player_prefs (player_key, notify_consent) VALUES (:player_key, :value)
    ON CONFLICT (player_key) DO UPDATE SET notify_consent = EXCLUDED.notify_consent, updated_at = now()
    """)


async def set_consent(session: AsyncSession, player_key: int, value: bool) -> None:
    """Согласие на новые сообщения игры (напоминания о матчах, итоги недели и месяца, возврат).
    «Не присылать» выключает их все сразу; итог хода, перенос и поправка итога от этого не зависят.
    Вернуть согласие игрок может сам (кнопка «Присылать» в вопросе или настройки)."""
    await session.execute(_ENSURE_PLAYER, {"player_key": player_key, "name": DEFAULT_PLAYER_NAME})
    await session.execute(_SET_CONSENT, {"player_key": player_key, "value": bool(value)})


async def get_prefs(session: AsyncSession, player_key: int) -> dict:
    row = (await session.execute(_PREFS, {"player_key": player_key})).one_or_none()
    return {
        "on": True if row is None else bool(row.remind),
        "fav_club": row.fav_club if row else None,
        "types": {kind: (True if row is None else bool(getattr(row, col))) for kind, col in TYPE_COLUMN.items()},
        "league": True if row is None else bool(row.notify_league),
        "blocked": bool(row and row.bot_blocked_at),
    }


async def set_type(session: AsyncSession, player_key: int, kind: str, on: bool) -> None:
    """Включить или отключить один тип сообщений. ``kind`` — один из ``TYPE_COLUMN`` или ``EXTRA_TYPE_COLUMN``."""
    column = EXTRA_TYPE_COLUMN.get(kind) or TYPE_COLUMN[kind]
    await session.execute(_SET_TYPE, {"player_key": player_key})
    await session.execute(
        text(f"UPDATE hockey_player_prefs SET {column} = :on, updated_at = now() WHERE player_key = :player_key"),
        {"player_key": player_key, "on": bool(on)},
    )


async def set_fav_club(
    session: AsyncSession, player_key: int, club: str | None, *, display_name: str = ""
) -> str | None:
    """«Болею за». ``None`` — вернуться к клубу с наибольшим числом ходов. Неизвестный клуб — ``ValueError``."""
    club = (club or "").strip() or None
    if club is not None and club not in known_clubs():
        raise ValueError("Неизвестная команда")
    name = (display_name or "").strip()[:40] or DEFAULT_PLAYER_NAME
    await session.execute(_ENSURE_PLAYER, {"player_key": player_key, "name": name})
    await session.execute(_SET_FAV, {"player_key": player_key, "club": club})
    return club


def known_clubs() -> frozenset[str]:
    from src.application.hockey_leagues import _known_clubs

    return _known_clubs()


async def mark_blocked(session: AsyncSession, player_key: int, *, now: datetime) -> None:
    await session.execute(_MARK_BLOCKED, {"player_key": player_key, "now": _utc(now)})


async def clear_blocked(session: AsyncSession, player_key: int) -> None:
    await session.execute(_CLEAR_BLOCKED, {"player_key": player_key})


# ---------- кому и что ----------

# «Своя» команда: «болею за», иначе клуб, за который чаще ходил за 30 дней (сторона хода = клуб).
_FAN_CLUB = """
    COALESCE(
        pr.fav_club,
        (SELECT CASE x.side WHEN 'home' THEN xm.home_team ELSE xm.away_team END
         FROM hockey_picks AS x JOIN game_matches AS xm ON xm.id = x.match_id
         WHERE x.player_key = pl.player_key AND xm.starts_at >= :fan_since AND xm.starts_at <= :now
         GROUP BY 1 ORDER BY COUNT(*) DESC, MAX(x.picked_at) DESC, 1
         LIMIT 1)
    )"""

# По умолчанию пишем всем, у кого есть хоть один ход (решение координатора); без ходов — не пишем.
# Строки настроек может не быть: тогда всё включено. Главный выключатель — ``remind``.
_ELIGIBLE = (
    "COALESCE(pr.remind, true) AND pr.bot_blocked_at IS NULL"
    " AND EXISTS (SELECT 1 FROM hockey_picks AS hp WHERE hp.player_key = pl.player_key)"
)

_DUE_NOMOVE = text(f"""
    SELECT pl.player_key, m.id AS match_id, m.home_team, m.away_team, m.starts_at
    FROM hockey_players AS pl
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = pl.player_key
    JOIN game_matches AS m ON m.status = 'scheduled'
         AND m.starts_at > :from_ AND m.starts_at <= :until
         AND {_FAN_CLUB} IN (m.home_team, m.away_team)
    WHERE {_ELIGIBLE} AND COALESCE(pr.notify_nomove, true)
      AND NOT EXISTS (SELECT 1 FROM hockey_picks AS p WHERE p.match_id = m.id AND p.player_key = pl.player_key)
      AND NOT EXISTS (
          SELECT 1 FROM hockey_notices AS n
          WHERE n.player_key = pl.player_key AND n.match_id = m.id AND n.kind = 'nomove'
      )
    ORDER BY pl.player_key, m.starts_at
    """)

_DUE_RESULT = text(f"""
    SELECT p.player_key, m.id AS match_id, m.home_team, m.away_team, m.starts_at, m.league,
           m.home_score AS final_home, m.away_score AS final_away,
           p.side, p.home_score, p.away_score, p.doubled, p.points,
           (SELECT COUNT(*) FROM hockey_picks x WHERE x.match_id = m.id AND x.side = 'home')::int AS home_picks,
           (SELECT COUNT(*) FROM hockey_picks x WHERE x.match_id = m.id AND x.side = 'away')::int AS away_picks,
           (SELECT COUNT(*) FROM hockey_picks x
            WHERE x.match_id = m.id AND x.player_key <> p.player_key
              AND x.home_score = p.home_score AND x.away_score = p.away_score)::int AS same_exact
    FROM hockey_picks AS p
    JOIN hockey_players AS pl ON pl.player_key = p.player_key
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = p.player_key
    JOIN game_matches AS m ON m.id = p.match_id AND m.status = 'final' AND m.finalized_at > :fresh
                                  AND m.finalized_at <= :ready
         -- админ нажал «Поправить» и ещё не закончил: рассылку держим до ``hold_until`` (hockey_review.HOLD_FOR)
         AND (m.result_probe->>'hold_until' IS NULL
              OR CAST(m.result_probe->>'hold_until' AS TIMESTAMPTZ) <= :ready_now)
    WHERE {_ELIGIBLE} AND COALESCE(pr.notify_result, true) AND p.points IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM hockey_notices AS n
          WHERE n.player_key = p.player_key AND n.match_id = m.id AND n.kind = 'result'
      )
    ORDER BY m.finalized_at, m.id, p.player_key
    """)

# Месяц, последний матч клуба в нём и «сегодня» — финал месяца для болельщиков этого клуба.
_FINAL_OF_MONTH = text("""
    SELECT m.id, m.home_team, m.away_team, m.starts_at
    FROM game_matches AS m
    WHERE m.starts_at >= :since AND m.starts_at < :until
      AND (m.home_team = :club OR m.away_team = :club) AND m.status <> 'cancelled'
    ORDER BY m.starts_at DESC, m.id DESC
    LIMIT 1
    """)

_MFINAL_FANS = text(f"""
    SELECT pl.player_key, {_FAN_CLUB} AS club
    FROM hockey_players AS pl
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = pl.player_key
    WHERE {_ELIGIBLE} AND COALESCE(pr.notify_mfinal, true)
    """)

_SENT_TODAY = text("""
    SELECT DISTINCT player_key FROM hockey_notices
    WHERE sent_at >= :since AND sent_at < :until AND kind NOT IN ('result', 'moved', 'mvfree', 'rescore')
    """)

_HAS_PICK = text("SELECT 1 FROM hockey_picks WHERE match_id = :match_id AND player_key = :player_key")

_NEXT_FOR_CLUB = text("""
    SELECT m.id AS match_id, m.home_team, m.away_team, m.starts_at
    FROM game_matches AS m
    WHERE m.status = 'scheduled' AND m.starts_at > :from_
      AND (CAST(:club AS text) IS NULL OR m.home_team = :club OR m.away_team = :club)
      AND NOT EXISTS (SELECT 1 FROM hockey_picks AS p WHERE p.match_id = m.id AND p.player_key = :player_key)
    ORDER BY m.starts_at, m.id
    LIMIT 1
    """)

_FAN_CLUB_OF = text(f"""
    SELECT {_FAN_CLUB} AS club FROM hockey_players AS pl LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = pl.player_key WHERE pl.player_key = :player_key
    """)


def _link(start_param: str) -> str | None:
    """Кнопки в пушах: тот же публичный вход (при via_start — ``?start=``, чат уже есть)."""
    from src.application.place_links import public_telegram_entry_link
    from src.shared.config import Settings

    return public_telegram_entry_link(Settings(), start_param=start_param)  # type: ignore[call-arg]


def url_button(label: str, start_param: str) -> dict | None:
    url = _link(start_param)
    return {"text": label, "url": url} if url else None


def pick_buttons(match_id: int, home: str, away: str) -> list[dict]:
    """Ход в один тап: за хозяев или за гостей. Ту же запись делает Mini App."""
    return [
        {"text": club_name(home), "callback_data": f"{CB_PICK}:{match_id}:h"},
        {"text": club_name(away), "callback_data": f"{CB_PICK}:{match_id}:a"},
    ]


def off_button(kind: str) -> list[dict]:
    return [{"text": "Отключить такие сообщения", "callback_data": f"{CB_OFF}:{CODE_OF[kind]}"}]


def _rows(*rows: list[dict | None]) -> list[list[dict]]:
    out = []
    for row in rows:
        built = [b for b in row if b]
        if built:
            out.append(built)
    return out


def _hhmm(value: datetime) -> str:
    return _local(value).strftime("%H:%M").lstrip("0").rjust(4, "0")


def _day_word(starts_at: datetime, now: datetime) -> str:
    days = (_local(starts_at).date() - _local(now).date()).days
    if days in (0, 1):
        return "сегодня" if days == 0 else "завтра"
    day = _local(starts_at)
    return f"{day.day} {MONTHS_GEN[day.month - 1]}"


def _points_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "очко"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "очка"
    return "очков"


def _ordinal(n: int) -> str:
    return f"{n}-е"


def nomove_text(*, home: str, away: str, starts_at: datetime, now: datetime) -> str:
    return (
        f"<b>{html.escape(club_name(home))} — {html.escape(club_name(away))}</b> {_day_word(starts_at, now)} в {_hhmm(starts_at)}. "
        "КТО КОГО? 🏒"
    )


def _your_move(home: str, away: str, side: str | None, pick_home: int | None, pick_away: int | None) -> str:
    """Счёт хода, если игрок его назвал; иначе сторона, за которую он ходил."""
    if pick_home is not None and pick_away is not None:
        return f"Твой ход {pick_home}:{pick_away}."
    if side == "home":
        return f"Твой ход — {html.escape(club_name(home))}."
    if side == "away":
        return f"Твой ход — {html.escape(club_name(away))}."
    return ""


def result_text(
    *,
    home: str,
    away: str,
    final_home: int,
    final_away: int,
    points: int,
    doubled: bool,
    side: str | None = None,
    pick_home: int | None = None,
    pick_away: int | None = None,
) -> str:
    """Строка одного итога без места: счёт матча, ход игрока, вердикт и очки."""
    total = points * (2 if doubled else 1)
    x2 = " с козырем" if doubled else ""
    # Слова вердикта те же, что ``verdict`` в kto-kogo-model.js: бот и Mini App называют исход одинаково.
    head = {POINTS_EXACT: "В точку!", 30: "Почти в точку", 20: "Победитель угадан", 10: "Шайбы угаданы"}.get(points)
    if head is None:
        verdict = "Мимо. Бывает."
    elif points == POINTS_EXACT:
        verdict = f"{head} +{total}{x2}."
    else:
        verdict = f"{head}: +{total}{x2}."
    head_line = f"<b>{html.escape(club_name(home))} — {html.escape(club_name(away))} {final_home}:{final_away}.</b>"
    move = _your_move(home, away, side, pick_home, pick_away)
    return " ".join(part for part in (head_line, move, verdict) if part)


# «Трибуна» — с какой долей игроков совпал ход. На паре ходов проценты ничего не значат.
TRIBUNE_MIN = 8


def _percent(part: int, total: int) -> int:
    """Половина вверх, как ``Math.round`` в Mini App: бот и экран итога пишут одно число."""
    return (200 * part + total) // (2 * total)


def tribune_line(
    *,
    home: str,
    away: str,
    final_home: int,
    final_away: int,
    side: str | None,
    points: int,
    home_picks: int,
    away_picks: int,
    same_exact: int,
) -> str:
    """Строка «Трибуны» под итогом; меньше ``TRIBUNE_MIN`` ходов — пусто. Те же правила, что ``tribune`` в Mini App."""
    total = home_picks + away_picks
    if total < TRIBUNE_MIN or side not in ("home", "away"):
        return ""
    if points == POINTS_EXACT:
        if not same_exact:
            return f"Такой счёт больше никто из {total} не назвал."
        return f"Такой счёт назвали ещё {same_exact} из {total}."
    winner = "home" if final_home > final_away else "away"
    # Как в Mini App: доля хозяев округляется, гостей — остаток до 100, чтобы бот и экран писали одно число.
    home_pct = _percent(home_picks, total)
    pct = {"home": home_pct, "away": 100 - home_pct}
    if side == winner:
        return f"Победителя угадали {pct[winner]}% игроков — и ты в их числе."
    mine = home_picks if side == "home" else away_picks
    if 2 * mine > total:
        club = html.escape(club_name(home if side == "home" else away))
        return f"Трибуна тоже промахнулась: {pct[side]}% были за {club}."
    return f"Победителя угадали {pct[winner]}% игроков."


def cap_line(*, league_name: str, holders: tuple[str, ...] | list[str], mine: bool) -> str:
    """Строка сводки про кепку дня в лиге (TASK-431). Имена и названия не склоняем: «в лиге «Бригада» — у тебя», но «— Олег»."""
    league = html.escape(league_name)
    if len(holders) == 1:
        who = "у тебя" if mine else html.escape(holders[0])
        return f"<b>Кепка дня</b> в лиге «{league}» — {who}: хуже всех в этот вечер."
    names = [html.escape(n) for n in holders]
    joined = ", ".join(names[:-1]) + " и " + names[-1]
    return f"<b>Кепка дня</b> в лиге «{league}» — {joined}: хуже всех в этот вечер."


def captain_line(*, league_name: str, offer: dict | None = None) -> str:
    """Строка сводки капитану вечера (TASK-432) и готовое предложение для выдачи в один тап (кнопка — ``offer_button``).
    Имена не склоняем: «Олег — 0 из 4», «Олег — автор твоей каски»."""
    from src.application.hockey_league_captain import OUTFIT_WORDS

    head = f"<b>Ты капитан</b> в лиге «{html.escape(league_name)}»"
    if not offer or offer["item"] not in OUTFIT_WORDS:
        return head + " — выдай экипировку кому хочешь, хоть себе."
    _, what, of_what = OUTFIT_WORDS[offer["item"]]
    name = html.escape(offer["name"])
    if offer["revenge"]:
        return f"{head}. {name} — автор {of_what}. Самое время вернуть — или выбери другое в «Вечере»."
    if offer["me"]:
        return f"{head}. Выдать себе {what}? Или выбери кому в «Вечере»."
    return f"{head}. {name} — {offer['hits']} из {offer['matches']}: выдать {what}? Или выбери другое в «Вечере»."


def offer_button(league_id: int, day, offer: dict) -> dict:
    from src.application.hockey_league_captain import OUTFIT_WORDS

    verb = "Вернуть" if offer["revenge"] else "Выдать себе" if offer["me"] else "Выдать"
    return {
        "text": f"{verb} {OUTFIT_WORDS[offer['item']][1]}",
        "callback_data": f"{CB_OUTFIT}:{league_id}:{day:%y%m%d}:{offer['pid']}:{offer['item']}",
    }


def evening_button(league_id: int, day) -> dict | None:
    return url_button("Вечер в лиге", f"{START_EVENING}_{league_id}_{day:%Y%m%d}")


def summary_text(lines: list[str]) -> str:
    return "<b>Итоги твоих ходов</b>\n" + "\n".join(lines)


def _slice_title(club: str | None, period: Period) -> str:
    """Подпись среза как в Mini App: «Юность · ноябрь», «Все · сезон»."""
    when = "сезон" if period.title.startswith("сезон") else period.title
    return f"{club_name(club) if club else 'Все'} · {when}"


async def _rows_cached(session: AsyncSession, cache: dict, club: str | None, period: Period):
    key = (club, period.key)
    if key not in cache:
        cache[key] = await slice_rows(session, scope=club_scope(club), period=period)
    return cache[key]


def _place_line(rank: int, size: int, title: str) -> str:
    return f"Твоё место в «{title}»: {_ordinal(rank)} из {size}."


async def best_place(
    session: AsyncSession, *, player_key: int, home: str, away: str, starts_at: datetime, cache: dict
) -> tuple[tuple, str] | None:
    """Лучший срез матча и готовая строка места. Ключ сравнивается между матчами одной пачки."""
    month = month_period(_local(starts_at).date())
    season = season_period(starts_at)
    best: tuple[tuple, str] | None = None
    for club in (home, away, None):
        for period in (month, season):
            rows = await _rows_cached(session, cache, club, period)
            mine = next((r for r in rows if r.player_key == player_key), None)
            if mine is None or not crown_eligible(rows):
                continue
            title = _slice_title(club, period)
            key = (mine.rank / len(rows), -len(rows), mine.rank, title)
            if best is None or key < best[0]:
                best = (key, _place_line(mine.rank, len(rows), title))
    return best


async def _next_for(session: AsyncSession, player_key: int, *, now: datetime, club: str | None) -> dict | None:
    row = (
        await session.execute(
            _NEXT_FOR_CLUB, {"player_key": player_key, "from_": _utc(now) + PICK_CLOSES_BEFORE, "club": club}
        )
    ).one_or_none()
    return dict(row._mapping) if row else None


async def fan_club(session: AsyncSession, player_key: int, *, now: datetime) -> str | None:
    params = {"player_key": player_key, "now": _utc(now), "fan_since": _utc(now) - FAN_WINDOW}
    return (await session.execute(_FAN_CLUB_OF, params)).scalar_one_or_none()


# ---------- «тебя обошли в лиге» ----------

_ACTIVE_LEAGUES = text("""
    SELECT id, name, invite_code, owner_key, scope, clubs, term_kind, starts_at, ends_at FROM hockey_leagues AS l
    WHERE starts_at <= :now AND ends_at > :now
      AND EXISTS (SELECT 1 FROM hockey_league_members AS m WHERE m.league_id = l.id)  -- архивные пропускаем
    ORDER BY id
    """)

_MARKS = text("SELECT player_key, rank, points FROM hockey_rank_marks WHERE league_id = :league_id")

_SET_MARK = text("""
    INSERT INTO hockey_rank_marks (league_id, player_key, rank, points, updated_at)
    VALUES (:league_id, :player_key, :rank, :points, :now)
    ON CONFLICT (league_id, player_key) DO UPDATE
    SET rank = EXCLUDED.rank, points = EXCLUDED.points, updated_at = EXCLUDED.updated_at
    """)

_LEAGUE_LAST_FINAL = text(f"""
    SELECT m.id FROM game_matches AS m
    WHERE m.status = 'final' AND m.starts_at >= :since AND m.starts_at < :until
      {SCOPE_SQL}
    ORDER BY m.finalized_at DESC NULLS LAST, m.id DESC
    LIMIT 1
    """)


async def scan_league_ranks(session: AsyncSession, *, now: datetime) -> list[Overtake]:
    """Сверить места в активных лигах с прошлым проходом: кого и кто обошёл. Обновляет метки мест.

    Первый проход по лиге места только запоминает. Обошёл — тот, кто был ниже и стал выше; из нескольких
    берётся лучший по месту. Новый участник и вышедший событий не дают."""
    from src.application.hockey_leagues import League, league_table_rows

    out: list[Overtake] = []
    for rec in (await session.execute(_ACTIVE_LEAGUES, {"now": _utc(now)})).all():
        league = League(
            id=rec.id,
            name=rec.name,
            invite_code=rec.invite_code,
            owner_key=rec.owner_key,
            scope=rec.scope,
            clubs=tuple(rec.clubs or ()),
            term_kind=rec.term_kind,
            starts_at=rec.starts_at,
            ends_at=rec.ends_at,
        )
        rows = await league_table_rows(session, league)
        if len(rows) < 2:
            continue
        marks = {m.player_key: m for m in (await session.execute(_MARKS, {"league_id": league.id})).all()}
        changed = [
            r
            for r in rows
            if r.player_key not in marks or (marks[r.player_key].rank, marks[r.player_key].points) != (r.rank, r.points)
        ]
        if not changed:
            continue
        anchor = None
        for r in rows:
            old = marks.get(r.player_key)
            if old is None or r.rank <= old.rank:
                continue
            culprits = [
                c
                for c in rows
                if c.player_key != r.player_key
                and c.rank < r.rank
                and (c.player_key in marks and marks[c.player_key].rank > old.rank)
            ]
            if not culprits:
                continue
            if anchor is None:
                params = {
                    **league.match_scope.params,
                    "since": _utc(league.starts_at),  # type: ignore[arg-type]
                    "until": _utc(league.ends_at),  # type: ignore[arg-type]
                }
                anchor = (await session.execute(_LEAGUE_LAST_FINAL, params)).scalar_one_or_none()
            if anchor is None:
                continue
            by = min(culprits, key=lambda c: (c.rank, -c.points, c.display_name))
            out.append(
                Overtake(
                    league_id=league.id,
                    league_name=league.name,
                    player_key=r.player_key,
                    by_name=by.display_name,
                    rank=r.rank,
                    anchor_match_id=anchor,
                    scope=(league.scope, league.clubs),
                    starts_at=league.starts_at,
                    ends_at=league.ends_at,
                )
            )
        for r in changed:
            await session.execute(
                _SET_MARK,
                {
                    "league_id": league.id,
                    "player_key": r.player_key,
                    "rank": r.rank,
                    "points": r.points,
                    "now": _utc(now),
                },
            )
    return out


_PREFS_OF = text(f"""
    SELECT pl.player_key FROM hockey_players AS pl
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = pl.player_key
    WHERE pl.player_key = ANY(:keys) AND {_ELIGIBLE} AND COALESCE(pr.notify_overtook, true)
    """)

_NEXT_IN_SCOPE = text(f"""
    SELECT m.id AS match_id, m.home_team, m.away_team, m.starts_at FROM game_matches AS m
    WHERE m.status = 'scheduled' AND m.starts_at > :from_ AND m.starts_at < :until
      {SCOPE_SQL}
    ORDER BY m.starts_at, m.id
    LIMIT 1
    """)


async def _overtook_notice(session: AsyncSession, o: Overtake, *, now: datetime) -> Notice:
    from src.application.hockey_slices import league_scope

    scope = league_scope(*o.scope)
    nxt = (
        await session.execute(
            _NEXT_IN_SCOPE,
            {**scope.params, "from_": _utc(now) + PICK_CLOSES_BEFORE, "until": _utc(o.ends_at or now)},
        )
    ).one_or_none()
    body = f"В лиге «{html.escape(o.league_name)}» {html.escape(o.by_name)} теперь выше тебя. Твоё место — {_ordinal(o.rank)}."
    rows: list[list[dict | None]] = []
    if nxt is not None:
        body += (
            f"\n{html.escape(club_name(nxt.home_team))} — {html.escape(club_name(nxt.away_team))}, "
            f"{_day_word(nxt.starts_at, now)} в {_hhmm(nxt.starts_at)} — шанс вернуть. КТО КОГО? 🏒"
        )
        if not (await session.execute(_HAS_PICK, {"match_id": nxt.match_id, "player_key": o.player_key})).first():
            rows.append([url_button("Сыграть", f"{START_PICK}_{nxt.match_id}")])
    rows.append([url_button("Таблица лиги", f"{START_LEAGUE}_{await _invite_code(session, o.league_id)}")])
    rows.append(off_button(KIND_OVERTOOK))
    return Notice(KIND_OVERTOOK, o.player_key, o.anchor_match_id, body, _rows(*rows))


async def _invite_code(session: AsyncSession, league_id: int) -> str:
    return (
        await session.execute(text("SELECT invite_code FROM hockey_leagues WHERE id = :id"), {"id": league_id})
    ).scalar_one()


# ---------- сборка ----------


async def _result_notices(session: AsyncSession, *, now: datetime, cache: dict) -> list[Notice]:
    fresh = now - (RESULT_FRESH if _local(now).hour >= 15 else RESULT_FRESH_AFTER_NIGHT)
    by_player: dict[int, list] = {}
    for r in (
        await session.execute(
            _DUE_RESULT, {"fresh": _utc(fresh), "ready": _utc(now) - RESULT_SEND_DELAY, "ready_now": _utc(now)}
        )
    ).all():
        by_player.setdefault(r.player_key, []).append(r)
    out: list[Notice] = []
    for player_key, rows in by_player.items():
        texts: list[str] = []
        places: list[tuple[tuple, str]] = []
        for r in rows:
            found = await best_place(
                session, player_key=player_key, home=r.home_team, away=r.away_team, starts_at=r.starts_at, cache=cache
            )
            if found is not None:
                places.append(found)
            texts.append(
                result_text(
                    home=r.home_team,
                    away=r.away_team,
                    final_home=r.final_home,
                    final_away=r.final_away,
                    points=r.points,
                    doubled=bool(r.doubled),
                    side=r.side,
                    pick_home=r.home_score,
                    pick_away=r.away_score,
                )
            )
        # В пачке место одно: лучший срез среди этих матчей, уже после всех ходов.
        place = min(places)[1] if places else None
        if len(rows) == 1:
            r = rows[0]
            body = texts[0]
            # В сводке нескольких итогов «Трибуну» не пишем: строк и так много.
            tribune = tribune_line(
                home=r.home_team,
                away=r.away_team,
                final_home=r.final_home,
                final_away=r.final_away,
                side=r.side,
                points=r.points,
                home_picks=r.home_picks,
                away_picks=r.away_picks,
                same_exact=r.same_exact,
            )
            if tribune:
                body += "\n" + tribune
        else:
            body = summary_text(texts)
        if place:
            body += "\n" + place
        # Кепка дня решилась матчем из этой сводки — по строке на лигу; кнопка ведёт в «Вечер» первой (TASK-431).
        news = await _cap_news(session, player_key, rows, now=now, cache=cache.setdefault("cap_news", {}))
        offer, evening = None, news[0] if news else None
        for item in news:
            if item.holders:
                body += "\n" + cap_line(league_name=item.league_name, holders=item.holders, mine=item.mine)
            if item.captain:
                # Кнопка в один тап — одна на сообщение: предложение пишем только в той лиге, где кнопка.
                one_tap = offer is None and item.offer is not None
                body += "\n" + captain_line(league_name=item.league_name, offer=item.offer if one_tap else None)
                if one_tap:
                    offer, evening = offer_button(item.league_id, item.day, item.offer), item
        buttons = _rows(
            [
                {"text": "Следующий ход", "callback_data": CB_NEXT},
                url_button("Таблица", f"{START_PICK}_{rows[-1].match_id}"),
            ],
            [offer] if offer else [],
            [evening_button(evening.league_id, evening.day)] if evening else [],
            off_button(KIND_RESULT),
        )
        out.append(
            Notice(KIND_RESULT, player_key, rows[0].match_id, body, buttons, also=tuple(r.match_id for r in rows[1:]))
        )
    return out


async def _cap_news(session: AsyncSession, player_key: int, rows: list, *, now: datetime, cache: dict) -> list:
    """Сбой подсчёта кепки не должен задержать итог: без строки про кепку сводка уходит как раньше."""
    from src.application.hockey_league_evening import cap_news

    try:
        async with session.begin_nested():
            return await cap_news(
                session, player_key=player_key, matches=[dict(r._mapping) for r in rows], now=now, cache=cache
            )
    except Exception:  # noqa: BLE001
        logger.warning("kk cap news failed for %s", player_key, exc_info=True)
        return []


async def _nomove_candidates(session: AsyncSession, *, now: datetime) -> dict[int, Notice]:
    params = {
        "from_": _utc(now) + NOMOVE_MIN_LEFT,
        "until": _utc(now) + NOMOVE_AHEAD,
        "now": _utc(now),
        "fan_since": _utc(now) - FAN_WINDOW,
    }
    out: dict[int, Notice] = {}
    for r in (await session.execute(_DUE_NOMOVE, params)).all():
        if r.player_key in out:
            continue
        body = nomove_text(home=r.home_team, away=r.away_team, starts_at=r.starts_at, now=now)
        buttons = _rows([url_button("Сыграть", f"{START_PICK}_{r.match_id}")], off_button(KIND_NOMOVE))
        out[r.player_key] = Notice(KIND_NOMOVE, r.player_key, r.match_id, body, buttons)
    return out


async def _mfinal_candidates(session: AsyncSession, *, now: datetime, cache: dict) -> dict[int, Notice]:
    local = _local(now)
    if local.hour < MFINAL_FROM_HOUR:
        return {}
    since, until = month_bounds(local.date())
    month = month_period(local.date())
    fans = (await session.execute(_MFINAL_FANS, {"now": _utc(now), "fan_since": _utc(now) - FAN_WINDOW})).all()
    finals: dict[str, object] = {}
    out: dict[int, Notice] = {}
    for fan in fans:
        club = fan.club
        if not club:
            continue
        if club not in finals:
            finals[club] = (
                await session.execute(_FINAL_OF_MONTH, {"since": since, "until": until, "club": club})
            ).one_or_none()
        final = finals[club]
        if (
            final is None
            or _local(final.starts_at).date() != local.date()
            or _utc(final.starts_at) <= _utc(now) + NOMOVE_MIN_LEFT
        ):
            continue
        rows = await _rows_cached(session, cache, club, month)
        mine = next((r for r in rows if r.player_key == fan.player_key), None)
        if mine is None or mine.rank > MFINAL_TOP or not crown_eligible(rows):
            continue
        rivals = [r for r in rows if r.player_key != fan.player_key]
        body = (
            f"<b>Корона за {MONTHS[local.month - 1]} решится сегодня:</b> "
            f"{html.escape(club_name(final.home_team))} — {html.escape(club_name(final.away_team))}, {_hhmm(final.starts_at)}, "
            "последний матч месяца. "
        )
        if mine.rank == 1:
            second = rivals[0] if rivals else None
            gap = mine.points - second.points if second else 0
            body += f"Ты на 1-м месте" + (
                f", {html.escape(second.display_name)} позади на {gap} {_points_word(gap)}." if second and gap else "."
            )
        else:
            leader = rows[0]
            gap = leader.points - mine.points
            body += (
                f"Ты на {mine.rank}-м месте, до короны {gap} {_points_word(gap)}."
                if gap
                else f"Ты на {mine.rank}-м месте — в очках вровень с первым."
            )
        body += " КТО КОГО? 🏒"
        has_pick = (await session.execute(_HAS_PICK, {"match_id": final.id, "player_key": fan.player_key})).first()
        buttons = _rows(
            [] if has_pick else [url_button("Сыграть", f"{START_PICK}_{final.id}")],
            [url_button("Таблица", f"{START_PICK}_{final.id}")],
            off_button(KIND_MFINAL),
        )
        out[fan.player_key] = Notice(KIND_MFINAL, fan.player_key, final.id, body, buttons)
    return out


async def due_notices(session: AsyncSession, *, now: datetime, overtakes: Iterable[Overtake] = ()) -> list[Notice]:
    """Что пора отправить с учётом тишины и дневного бюджета. Ничего не пишет.

    ``overtakes`` — события ``scan_league_ranks`` этого прохода."""
    now = _utc(now)
    if in_quiet_hours(now):
        return []
    cache: dict = {}
    out = await _result_notices(session, now=now, cache=cache)
    # «Перенесли матч» — событийные, вне дневного бюджета (как итоги): об отмене хода сказать обязательно.
    out += await _moved_notices(session, now=now)
    # Исправление уже разосланного итога — тоже вне бюджета и без срока свежести: в тихие часы ждёт до 09:00.
    out += await _rescore_notices(session)

    since, until = day_bounds(now)
    spent = set((await session.execute(_SENT_TODAY, {"since": since, "until": until})).scalars().all())
    candidates: dict[int, list[Notice]] = {}
    for source in (
        await _mfinal_candidates(session, now=now, cache=cache),
        await _nomove_candidates(session, now=now),
    ):
        for player_key, notice in source.items():
            candidates.setdefault(player_key, []).append(notice)
    overtakes = list(overtakes)
    if overtakes:
        allowed = set(
            (await session.execute(_PREFS_OF, {"keys": list({o.player_key for o in overtakes})})).scalars().all()
        )
        for o in overtakes:
            if o.player_key in allowed:
                candidates.setdefault(o.player_key, []).append(await _overtook_notice(session, o, now=now))
    for player_key, notices in candidates.items():
        if player_key in spent:
            continue
        out.append(min(notices, key=lambda n: PRIORITY[n.kind]))
    return out


# ---------- «матч перенесли» (событие, не скан) ----------

# Повторный перенос того же матча — сбрасываем доставку: об этом переносе тоже надо сказать.
_QUEUE_MOVED = text("""
    INSERT INTO hockey_notices (player_key, match_id, kind) VALUES (:player_key, :match_id, :kind)
    ON CONFLICT (player_key, match_id, kind) DO UPDATE SET sent_at = NULL, failed = false
    """)

# Строки уже «заняты» при вставке; постоянный сбой отправки — failed, временный оставляет строку в очереди.
_DUE_MOVED = text("""
    SELECT n.player_key, n.match_id, n.kind, m.home_team, m.away_team, m.starts_at
    FROM hockey_notices AS n
    JOIN game_matches AS m ON m.id = n.match_id
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = n.player_key
    WHERE n.kind IN ('moved', 'mvfree') AND n.sent_at IS NULL AND NOT n.failed
      AND COALESCE(pr.remind, true) AND pr.bot_blocked_at IS NULL
    ORDER BY n.match_id, n.player_key
    """)


async def queue_moved(
    session: AsyncSession, *, match_id: int, voided: list, released: list[int], starts_at: datetime
) -> None:
    """Поставить письма о переносе: ``voided`` — строки (player_key, doubled) аннулированных ходов,
    ``released`` — кому козырь вернулся. Пишется в той же транзакции, что и сам перенос."""
    for r in voided:
        kind = KIND_MOVED
        await session.execute(_QUEUE_MOVED, {"player_key": r.player_key, "match_id": match_id, "kind": kind})
    for player_key in released:
        await session.execute(_QUEUE_MOVED, {"player_key": player_key, "match_id": match_id, "kind": KIND_MOVED_FREE})


async def _moved_notices(session: AsyncSession, *, now: datetime) -> list[Notice]:
    out: list[Notice] = []
    for r in (await session.execute(_DUE_MOVED)).all():
        when = f"{_day_word(r.starts_at, now)} в {_hhmm(r.starts_at)}"
        if r.kind == KIND_MOVED:
            body = (
                f"{html.escape(club_name(r.home_team))} — {html.escape(club_name(r.away_team))} перенесли: теперь {when}. "
                "Твой ход сделан позже нового закрытия, поэтому сброшен — сделай его заново. "
                "Если на нём стоял козырь, он снова свободен."
            )
        else:
            body = (
                f"{html.escape(club_name(r.home_team))} — {html.escape(club_name(r.away_team))} перенесли на другую неделю, "
                f"и там твой козырь уже стоит на другом матче, поэтому с этого он снят. Матч теперь {when}."
            )
        buttons = _rows(
            list(pick_buttons(r.match_id, r.home_team, r.away_team)),
            [url_button("Открыть матч", f"{START_PICK}_{r.match_id}")],
        )
        out.append(Notice(r.kind, r.player_key, r.match_id, body, buttons, preclaimed=True))
    return out


# ---------- «мы ошиблись с итогом» (событие правки итога) ----------

# Кому уходит исправление: игрокам, которым итог (kind='result') уже отправлен, с теми же правилами, что у самого
# итога (главный выключатель, блок бота, тип «итоги ходов»). Старый счёт и очки фиксируются в момент правки
# в payload: потом по базе уже не узнать, что именно было в сообщении клиенту. Один раз на игрока и матч
# (ключ таблицы); если до отправки итог поправили ещё раз, старый счёт остаётся первым, новый читается из матча.
_RESCORE_AUDIENCE = f"""
    FROM hockey_notices AS n
    JOIN hockey_players AS pl ON pl.player_key = n.player_key
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = n.player_key
    JOIN hockey_picks AS p ON p.player_key = n.player_key AND p.match_id = n.match_id
    WHERE n.match_id = :match_id AND n.kind = 'result' AND n.sent_at IS NOT NULL
      AND COALESCE(pr.remind, true) AND pr.bot_blocked_at IS NULL AND COALESCE(pr.notify_result, true)
"""

_RESCORE_QUEUE = text(f"""
    INSERT INTO hockey_notices (player_key, match_id, kind, payload)
    SELECT n.player_key, n.match_id, 'rescore',
           jsonb_build_object('old_home', CAST(:old_home AS INT), 'old_away', CAST(:old_away AS INT),
                              'old_points', COALESCE(p.points, 0) * CASE WHEN p.doubled THEN 2 ELSE 1 END)
    {_RESCORE_AUDIENCE}
    ON CONFLICT (player_key, match_id, kind) DO NOTHING
    """)

# Итог вернули к тому, что клиент уже видел (А→Б→А до отправки): исправлять нечего.
_RESCORE_DROP_SAME = text("""
    DELETE FROM hockey_notices
    WHERE match_id = :match_id AND kind = 'rescore' AND sent_at IS NULL AND NOT failed
      AND (payload->>'old_home')::int = :new_home AND (payload->>'old_away')::int = :new_away
    """)

_RESCORE_COUNT_AUDIENCE = text(f"SELECT COUNT(*) {_RESCORE_AUDIENCE}")

_RESCORE_PENDING = text("""
    SELECT COUNT(*) FROM hockey_notices WHERE match_id = :match_id AND kind = 'rescore' AND sent_at IS NULL AND NOT failed
    """)


async def queue_rescore(session: AsyncSession, match_id: int, *, old: tuple[int, int], new: tuple[int, int]) -> int:
    """Итог поправили с ``old`` на ``new``: поставить исправление тем, кто получил старый. Вызывать ДО пересчёта очков.

    Тот же счёт — ничего. Возвращает, сколько игроков теперь ждут исправления."""
    # Сначала вставка (для уже ждущих строк это no-op: в них записан счёт, который видел клиент), потом чистка строк,
    # где «что видел клиент» совпало с новым счётом (А→Б→А до отправки).
    if old != new:
        await session.execute(_RESCORE_QUEUE, {"match_id": match_id, "old_home": old[0], "old_away": old[1]})
    await session.execute(_RESCORE_DROP_SAME, {"match_id": match_id, "new_home": new[0], "new_away": new[1]})
    return await pending_rescores(session, match_id)


async def rescore_audience(session: AsyncSession, match_id: int) -> int:
    """Сколько игроков получили итог и получат исправление, если счёт поменять."""
    return int((await session.execute(_RESCORE_COUNT_AUDIENCE, {"match_id": match_id})).scalar_one())


async def pending_rescores(session: AsyncSession, match_id: int) -> int:
    return int((await session.execute(_RESCORE_PENDING, {"match_id": match_id})).scalar_one())


_DUE_RESCORE = text("""
    SELECT n.player_key, n.match_id, n.payload, m.home_team, m.away_team, m.home_score, m.away_score,
           p.points, p.doubled
    FROM hockey_notices AS n
    JOIN game_matches AS m ON m.id = n.match_id AND m.status = 'final' AND m.home_score IS NOT NULL
    JOIN hockey_picks AS p ON p.player_key = n.player_key AND p.match_id = n.match_id
         AND p.points IS NOT NULL AND p.scored_at >= m.finalized_at
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = n.player_key
    WHERE n.kind = 'rescore' AND n.sent_at IS NULL AND NOT n.failed
      AND COALESCE(pr.remind, true) AND pr.bot_blocked_at IS NULL AND COALESCE(pr.notify_result, true)
    ORDER BY n.match_id, n.player_key
    """)


def rescore_text(
    *, home: str, away: str, score: tuple[int, int], old_score: tuple[int, int], old_points: int, new_points: int
) -> str:
    body = (
        f"Мы ошиблись с итогом: {html.escape(club_name(home))} — {html.escape(club_name(away))} "
        f"закончился {score[0]}:{score[1]}, а не {old_score[0]}:{old_score[1]}."
    )
    if old_points != new_points:
        body += f" Твои очки за матч: +{new_points}."
    return body


async def _rescore_notices(session: AsyncSession) -> list[Notice]:
    out: list[Notice] = []
    for r in (await session.execute(_DUE_RESCORE)).all():
        payload = r.payload or {}
        old_score = (int(payload.get("old_home", -1)), int(payload.get("old_away", -1)))
        if old_score == (r.home_score, r.away_score):
            continue  # итог вернули к тому, что клиент видел
        body = rescore_text(
            home=r.home_team,
            away=r.away_team,
            score=(r.home_score, r.away_score),
            old_score=old_score,
            old_points=int(payload.get("old_points", 0)),
            new_points=int(r.points) * (2 if r.doubled else 1),
        )
        buttons = _rows([url_button("Таблица", f"{START_PICK}_{r.match_id}")], off_button(KIND_RESULT))
        out.append(Notice(KIND_RESCORE, r.player_key, r.match_id, body, buttons, preclaimed=True))
    return out


_CLAIM = text("""
    INSERT INTO hockey_notices (player_key, match_id, kind) VALUES (:player_key, :match_id, :kind)
    ON CONFLICT DO NOTHING
    RETURNING player_key
    """)

_DONE = text("""
    UPDATE hockey_notices
    SET sent_at = CASE WHEN CAST(:ok AS BOOLEAN) THEN CAST(:now AS TIMESTAMPTZ) END, failed = NOT CAST(:ok AS BOOLEAN)
    WHERE player_key = :player_key AND match_id = :match_id AND kind = :kind
    """)


async def claim(session: AsyncSession, notice: Notice) -> bool:
    """Занять все матчи сообщения. Занят хоть один — сообщение уже уходило (или идёт)."""
    claimed = False
    for match_id in notice.match_ids:
        params = {"player_key": notice.player_key, "match_id": match_id, "kind": notice.kind}
        if (await session.execute(_CLAIM, params)).first() is not None:
            claimed = True
    return claimed


async def mark_done(session: AsyncSession, notice: Notice, *, ok: bool, now: datetime) -> None:
    for match_id in notice.match_ids:
        params = {"player_key": notice.player_key, "match_id": match_id, "kind": notice.kind}
        await session.execute(_DONE, {**params, "ok": ok, "now": _utc(now)})


_RELEASE = text("""
    DELETE FROM hockey_notices
    WHERE player_key = :player_key AND match_id = :match_id AND kind = :kind AND sent_at IS NULL AND NOT failed
    """)

_RETRIES: dict[tuple, int] = {}


def _attempt(key: tuple) -> bool:
    """Учесть попытку после временного сбоя. True — попытки ещё есть, False — лимит исчерпан."""
    _RETRIES[key] = _RETRIES.get(key, 0) + 1
    if _RETRIES[key] >= MAX_ATTEMPTS:
        _RETRIES.pop(key, None)
        return False
    return True


async def release(session: AsyncSession, notice: Notice) -> None:
    """Вернуть сообщение в очередь после временного сбоя: строку-«занятие» убираем, и скан найдёт повод снова."""
    if notice.preclaimed:
        return  # строка поставлена событием: sent_at IS NULL и не failed — и так в очереди
    for match_id in notice.match_ids:
        await session.execute(_RELEASE, {"player_key": notice.player_key, "match_id": match_id, "kind": notice.kind})


# ---------- чистка старых строк ----------

# Строки hockey_notices нужны, пока матч «живой» для сообщений (защита от повтора). Старше этого срока
# отправленные и окончательно упавшие строки только раздувают таблицу и индексы.
NOTICES_KEEP = timedelta(days=60)
NOTICES_CLEANUP_EVERY = timedelta(hours=6)
NOTICES_CLEANUP_BATCH = 2000
NOTICES_CLEANUP_MAX_BATCHES = 10

# Неотправленные строки очереди (sent_at IS NULL и не failed) не трогаем; повторно поставленная строка
# («moved» снова в очереди) имеет свежий sent_at/NULL, поэтому под условие не попадает.
_DELETE_OLD_NOTICES = text("""
    DELETE FROM hockey_notices
    WHERE (player_key, match_id, kind) IN (
        SELECT player_key, match_id, kind FROM hockey_notices
        WHERE COALESCE(sent_at, created_at) < :cutoff AND (sent_at IS NOT NULL OR failed)
        LIMIT :batch
    )
    """)

_last_cleanup: datetime | None = None


async def cleanup_old_notices(session_factory, *, now: datetime, force: bool = False) -> int:
    """Удалить старые строки порциями, не чаще раза в ``NOTICES_CLEANUP_EVERY``. Возвращает число удалённых.

    Каждая порция — своя короткая транзакция; за проход не больше ``NOTICES_CLEANUP_MAX_BATCHES`` порций,
    остаток уйдёт в следующий раз."""
    global _last_cleanup
    now = _utc(now)
    if not force and _last_cleanup is not None and now - _last_cleanup < NOTICES_CLEANUP_EVERY:
        return 0
    _last_cleanup = now
    total = 0
    await cleanup_journal(session_factory, now=now)
    for _ in range(NOTICES_CLEANUP_MAX_BATCHES):
        async with session_factory() as session:
            result = await session.execute(
                _DELETE_OLD_NOTICES, {"cutoff": now - NOTICES_KEEP, "batch": NOTICES_CLEANUP_BATCH}
            )
            await session.commit()
        deleted = getattr(result, "rowcount", 0) or 0
        total += deleted
        if deleted < NOTICES_CLEANUP_BATCH:
            break
    return total


def _outcome(value: "bool | str") -> str:
    if value is True:
        return SENT
    if value is False or value is None:
        return FAILED
    return value


async def _journal_refusal(session_factory, notice: Notice, reason: str, *, now: datetime) -> None:
    """Отказ допуска у прежнего повода — в журнал решений, не только в лог (ошибка журнала ничего не ломает)."""
    phase = UNKNOWN_PHASE
    try:
        async with session_factory() as session:
            facts = await load_one(session, notice.player_key, as_of=now)
        if facts is not None:
            phase = facts.phase(now).value
    except Exception:  # noqa: BLE001
        logger.warning("kto-kogo refusal journal: phase failed", exc_info=True)
    await write_journal(
        session_factory,
        tick_at=_utc(now),
        player_key=notice.player_key,
        phase=phase,
        kind=notice.kind,
        decision="skip",
        reason=reason,
    )


async def deliver(session_factory, *, now: datetime, send: Sender) -> dict[str, int]:
    """Сверить места в лигах, занять — закоммитить — отправить — отметить. Каждое сообщение — своя транзакция."""
    counts = {"sent": 0, "failed": 0, "blocked": 0}
    async with session_factory() as session:
        overtakes = await scan_league_ranks(session, now=now)
        await session.commit()
        notices = await due_notices(session, now=now, overtakes=overtakes)
    for notice in notices:
        # Единая точка допуска (kk_notify_gate): тихие часы, бюджет, блокировка и «не присылать» перечитываются
        # прямо перед отправкой, под замком игрока вместе с занятием строки. Неизвестный повод или сбой проверки —
        # не пишем, строку не занимаем.
        async with session_factory() as session:
            await lock_player(session, notice.player_key)
            admission = await admit(session, kind=notice.kind, player_key=notice.player_key, now=now)
            claimed = True
            if admission.allowed and not notice.preclaimed:
                claimed = await claim(session, notice)
                await session.commit()
        if not admission.allowed:
            logger.info("kto-kogo notice %s/%s not admitted: %s", notice.kind, notice.player_key, admission.reason)
            counts["refused"] = counts.get("refused", 0) + 1
            await _journal_refusal(session_factory, notice, admission.reason, now=now)
            continue
        if not claimed:
            continue
        try:
            outcome = _outcome(await send(notice.player_key, notice.text, notice.buttons))
        except Exception:  # noqa: BLE001 — сбой одного сообщения не роняет остальные
            logger.warning("kto-kogo notice %s/%s failed", notice.kind, notice.match_id, exc_info=True)
            outcome = FAILED
        if outcome == GONE:
            outcome = BLOCKED
        key = (notice.kind, notice.player_key, notice.match_ids)
        if outcome == RETRY and not _attempt(key):
            outcome = FAILED
        async with session_factory() as session:
            if outcome == RETRY:
                await release(session, notice)
            else:
                _RETRIES.pop(key, None)
                await mark_done(session, notice, ok=outcome == SENT, now=now)
                if outcome == BLOCKED:
                    await mark_blocked(session, notice.player_key, now=now)
            await session.commit()
        name = {SENT: "sent", BLOCKED: "blocked", RETRY: "retry"}.get(outcome, "failed")
        counts[name] = counts.get(name, 0) + 1  # ``retry`` появляется в ответе только когда был
    return counts


# ---------- ход и «Следующий ход» из чата ----------


@dataclass(frozen=True)
class ChatPick:
    status: str  # ok | closed | missing
    match_id: int
    home: str = ""
    away: str = ""
    side: str | None = None


_MATCH_TEAMS = text("SELECT home_team, away_team FROM game_matches WHERE id = :id")


async def chat_pick(
    session: AsyncSession, *, player_key: int, display_name: str, match_id: int, side: str, now: datetime
) -> ChatPick:
    """Ход по кнопке: тот же ``make_pick``, что у Mini App. После старта матча — ``closed``, ход не пишется."""
    teams = (await session.execute(_MATCH_TEAMS, {"id": match_id})).one_or_none()
    if teams is None:
        return ChatPick("missing", match_id)
    full = {"h": "home", "a": "away"}[side]
    try:
        await make_pick(
            session, player_key=player_key, display_name=display_name, match_id=match_id, side=full, now=now
        )
    except PicksClosed:
        return ChatPick("closed", match_id, club_name(teams.home_team), club_name(teams.away_team))
    except LookupError:
        return ChatPick("missing", match_id)
    await clear_blocked(session, player_key)
    return ChatPick("ok", match_id, club_name(teams.home_team), club_name(teams.away_team), full)


async def next_move(session: AsyncSession, *, player_key: int, now: datetime) -> Notice | None:
    """«Следующий ход»: ближайший матч «своей» команды (иначе любой), где у игрока ещё нет хода."""
    club = await fan_club(session, player_key, now=now)
    nxt = await _next_for(session, player_key, now=now, club=club) or (
        await _next_for(session, player_key, now=now, club=None) if club else None
    )
    if nxt is None:
        return None
    body = (
        f"<b>{html.escape(club_name(nxt['home_team']))} — {html.escape(club_name(nxt['away_team']))}</b> "
        f"{_day_word(nxt['starts_at'], now)} в {_hhmm(nxt['starts_at'])}. КТО КОГО? 🏒"
    )
    return Notice(
        "next",
        player_key,
        nxt["match_id"],
        body,
        _rows([url_button("Сыграть", f"{START_PICK}_{nxt['match_id']}")]),
    )


def picked_buttons(match_id: int, home: str, away: str, side: str) -> list[list[dict]]:
    """После хода: выбранная сторона отмечена, сменить можно до старта."""
    mark = "✓ "
    return [
        [
            {"text": (mark if side == "home" else "") + club_name(home), "callback_data": f"{CB_PICK}:{match_id}:h"},
            {"text": (mark if side == "away" else "") + club_name(away), "callback_data": f"{CB_PICK}:{match_id}:a"},
        ]
    ]


# ---------- «лига продлена» ----------

_DUE_LEAGUE_NOTICES = text("""
    SELECT n.league_id, n.player_key, l.name, l.invite_code, l.starts_at, l.ends_at,
           COALESCE(pr.notify_league, true) AS wants, pr.bot_blocked_at
    FROM hockey_league_notices AS n
    JOIN hockey_leagues AS l ON l.id = n.league_id
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = n.player_key
    WHERE n.claimed_at IS NULL AND n.kind = 'extended'
    ORDER BY n.created_at, n.league_id, n.player_key
    """)

_CLAIM_LEAGUE_NOTICE = text("""
    UPDATE hockey_league_notices SET claimed_at = :now
    WHERE league_id = :league_id AND player_key = :player_key AND kind = 'extended' AND claimed_at IS NULL
    RETURNING player_key
    """)

_RELEASE_LEAGUE_NOTICE = text("""
    UPDATE hockey_league_notices SET claimed_at = NULL
    WHERE league_id = :league_id AND player_key = :player_key AND kind = 'extended' AND sent_at IS NULL
    """)

_DONE_LEAGUE_NOTICE = text("""
    UPDATE hockey_league_notices
    SET sent_at = CASE WHEN CAST(:ok AS BOOLEAN) THEN CAST(:now AS TIMESTAMPTZ) END, failed = :failed
    WHERE league_id = :league_id AND player_key = :player_key AND kind = 'extended'
    """)


def league_extended_text(name: str, starts_at: datetime, ends_at: datetime) -> str:
    def day(v: datetime) -> str:
        d = _local(v)
        return f"{d.day} {MONTHS_GEN[d.month - 1]}"

    return (
        f"<b>Лига «{html.escape(name)}» продлена.</b> Те же люди, новый круг: с {day(starts_at)} по "
        f"{day(_local(ends_at) - timedelta(minutes=1))}. Выйти можно в один тап."
    )


def league_extended_buttons(league_id: int, invite_code: str) -> list[list[dict]]:
    return _rows(
        [url_button("Открыть лигу", f"{START_LEAGUE}_{invite_code}")],
        [{"text": "Выйти из лиги", "callback_data": f"{CB_LEAVE}:{league_id}"}],
    )


async def deliver_league_notices(session_factory, *, now: datetime, send: Sender) -> dict[str, int]:
    """Письма «лига продлена». Ответ на действие владельца лиги, а не игровая рассылка, поэтому: вне дневного бюджета
    и не зависят от согласия ``remind`` (так было всегда). Допуск (kk_notify_gate) не пускает к тем, кто отключил
    именно этот тип (``notify_league``) или заблокировал бота; ночью письма ждут утра."""
    counts = {"sent": 0, "failed": 0, "blocked": 0, "skipped": 0}
    if in_quiet_hours(now):
        return counts
    async with session_factory() as session:
        due = list((await session.execute(_DUE_LEAGUE_NOTICES)).all())
    for r in due:
        params = {"league_id": r.league_id, "player_key": r.player_key}
        # Под замком игрока: занять письмо и пройти допуск (он перечитывает блокировку и «не присылать» заново,
        # r.* — из выборки и мог устареть). Отказ тоже «съедает» письмо, как и раньше.
        async with session_factory() as session:
            await lock_player(session, r.player_key)
            if (await session.execute(_CLAIM_LEAGUE_NOTICE, {**params, "now": _utc(now)})).first() is None:
                continue
            admission = await admit(session, kind="league", player_key=r.player_key, now=now)
            await session.commit()
        if not admission.allowed:
            counts["skipped"] += 1
            await _journal_refusal(
                session_factory, Notice("league", r.player_key, 0, "", []), admission.reason, now=now
            )
            continue
        try:
            outcome = _outcome(
                await send(
                    r.player_key,
                    league_extended_text(r.name, r.starts_at, r.ends_at),
                    league_extended_buttons(r.league_id, r.invite_code),
                )
            )
        except Exception:  # noqa: BLE001
            logger.warning("kto-kogo league notice %s failed", r.league_id, exc_info=True)
            outcome = FAILED
        if outcome == GONE:
            outcome = BLOCKED
        key = ("league", r.league_id, r.player_key)
        if outcome == RETRY and not _attempt(key):
            outcome = FAILED
        async with session_factory() as session:
            if outcome == RETRY:
                await session.execute(
                    _RELEASE_LEAGUE_NOTICE, params
                )  # claimed_at снова NULL — уйдёт в следующий проход
            else:
                _RETRIES.pop(key, None)
                await session.execute(
                    _DONE_LEAGUE_NOTICE,
                    {**params, "ok": outcome == SENT, "failed": outcome != SENT, "now": _utc(now)},
                )
                if outcome == BLOCKED:
                    await mark_blocked(session, r.player_key, now=now)
            await session.commit()
        name = {SENT: "sent", BLOCKED: "blocked", RETRY: "retry"}.get(outcome, "failed")
        counts[name] = counts.get(name, 0) + 1
    return counts


# ---------- «капитан выдаёт тебе экипировку» (TASK-432) ----------

# Очередь — в самих выдачах: свежие, не себе, лига идёт. Действительна ли выдача, проверяем перед отправкой.
_DUE_OUTFIT_NOTICES = text("""
    SELECT o.league_id, o.day, o.to_key, l.name AS league_name
    FROM hockey_league_outfits AS o
    JOIN hockey_leagues AS l ON l.id = o.league_id
    WHERE o.notice_claimed_at IS NULL AND o.to_key <> o.captain_key AND o.updated_at >= :since AND l.ends_at > :now
    ORDER BY o.updated_at, o.league_id
    """)

_CLAIM_OUTFIT_NOTICE = text("""
    UPDATE hockey_league_outfits SET notice_claimed_at = :now
    WHERE league_id = :league_id AND day = :day AND to_key = :to_key AND notice_claimed_at IS NULL
    RETURNING to_key
    """)

_RELEASE_OUTFIT_NOTICE = text("""
    UPDATE hockey_league_outfits SET notice_claimed_at = NULL
    WHERE league_id = :league_id AND day = :day AND to_key = :to_key AND notice_sent_at IS NULL
    """)

_DONE_OUTFIT_NOTICE = text("""
    UPDATE hockey_league_outfits
    SET notice_sent_at = CASE WHEN CAST(:ok AS BOOLEAN) THEN CAST(:now AS TIMESTAMPTZ) END, notice_failed = :failed
    WHERE league_id = :league_id AND day = :day AND to_key = :to_key
    """)

OUTFIT_NOTICE_WINDOW = timedelta(days=2)


def outfit_text(*, captain: str, league_name: str, item: str) -> str:
    """Получателю: кто, где и что. Настоящее время — пол не нужен."""
    from src.application.hockey_league_captain import OUTFIT_WORDS

    full = OUTFIT_WORDS[item][0]
    return (
        f"<b>{html.escape(captain)} выдаёт тебе экипировку</b> в лиге «{html.escape(league_name)}»: "
        f"{full} — до следующего вечера. Видят все в «КТО КОГО».\nСтань капитаном — и выдавать будешь ты."
    )


async def deliver_outfit_notices(session_factory, *, now: datetime, send: Sender) -> dict[str, int]:
    """Сообщения «капитан выдаёт тебе экипировку». Как письма лиги: ответ на действие друга — вне дневного бюджета
    и согласия, ночью ждут утра, «Не присылать такое» и блокировка — через допуск. Выдача уже не действует (вечер
    сменился, капитан другой, лига выключена) — сообщение не шлём, строку закрываем."""
    from src.application.hockey_league_captain import captain_enabled, evening_state
    from src.application.hockey_leagues import _LEAGUE_BY_ID, _league

    counts = {"sent": 0, "failed": 0, "blocked": 0, "skipped": 0}
    if in_quiet_hours(now):
        return counts
    async with session_factory() as session:
        params = {"since": _utc(now) - OUTFIT_NOTICE_WINDOW, "now": _utc(now)}
        due = list((await session.execute(_DUE_OUTFIT_NOTICES, params)).all())
    for r in due:
        key_params = {"league_id": r.league_id, "day": r.day, "to_key": r.to_key}
        async with session_factory() as session:
            await lock_player(session, r.to_key)
            if (await session.execute(_CLAIM_OUTFIT_NOTICE, {**key_params, "now": _utc(now)})).first() is None:
                continue
            league = _league((await session.execute(_LEAGUE_BY_ID, {"league_id": r.league_id})).one())
            state = await evening_state(session, league, r.day, now=now)
            award = state.award
            stale = not captain_enabled(league.id) or not state.current or award is None or award.to_key != r.to_key
            admission = None if stale else await admit(session, kind=KIND_OUTFIT, player_key=r.to_key, now=now)
            await session.commit()
        if stale or not admission.allowed:  # type: ignore[union-attr]
            counts["skipped"] += 1
            if admission is not None:
                await _journal_refusal(
                    session_factory, Notice(KIND_OUTFIT, r.to_key, 0, "", []), admission.reason, now=now
                )
            continue
        text_ = outfit_text(captain=award.captain_name, league_name=r.league_name, item=award.item)  # type: ignore[union-attr]
        buttons = _rows([evening_button(r.league_id, r.day)], off_button(KIND_OUTFIT))
        try:
            outcome = _outcome(await send(r.to_key, text_, buttons))
        except Exception:  # noqa: BLE001
            logger.warning("kto-kogo outfit notice %s/%s failed", r.league_id, r.day, exc_info=True)
            outcome = FAILED
        if outcome == GONE:
            outcome = BLOCKED
        retry_key = (KIND_OUTFIT, r.league_id, r.day, r.to_key)
        if outcome == RETRY and not _attempt(retry_key):
            outcome = FAILED
        async with session_factory() as session:
            if outcome == RETRY:
                await session.execute(_RELEASE_OUTFIT_NOTICE, key_params)
            else:
                _RETRIES.pop(retry_key, None)
                done = {**key_params, "ok": outcome == SENT, "failed": outcome != SENT, "now": _utc(now)}
                await session.execute(_DONE_OUTFIT_NOTICE, done)
                if outcome == BLOCKED:
                    await mark_blocked(session, r.to_key, now=now)
            await session.commit()
        name = {SENT: "sent", BLOCKED: "blocked", RETRY: "retry"}.get(outcome, "failed")
        counts[name] = counts.get(name, 0) + 1
    return counts


# Telegram режет рассылку ботом на ~30 сообщений/с; держимся с запасом.
_THROTTLE_SEC = 1 / 25
# Дольше этого просьбу подождать (RetryAfter) не ждём: сообщение вернётся в очередь на следующий проход.
_RETRY_AFTER_CAP_SEC = 30
_GONE_PHRASES = ("chat not found", "user is deactivated")
_last_send = 0.0
_bot = None
_bot_token = ""


async def _client_bot():
    """Один ``Bot`` (и его HTTP-сессия) на процесс, а не на каждое сообщение; закрывается ``close_client_bot``."""
    global _bot, _bot_token
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from src.shared.config import Settings

    token = (Settings().telegram_bot_token_client or "").strip()  # type: ignore[call-arg]
    if not token:
        return None
    if _bot is None or _bot_token != token:
        await close_client_bot()
        _bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        _bot_token = token
    return _bot


async def close_client_bot() -> None:
    global _bot, _bot_token
    bot, _bot, _bot_token = _bot, None, ""
    if bot is not None:
        await bot.session.close()


async def _throttle() -> None:
    global _last_send
    wait = _last_send + _THROTTLE_SEC - time.monotonic()
    if wait > 0:
        await asyncio.sleep(wait)
    _last_send = time.monotonic()


async def send_via_client_bot_gone(
    chat_id: int, text_body: str, buttons: list[list[dict]], *, photo: str | None = None
) -> str:
    """Тот же отправитель, но «чат не найден» и «аккаунт удалён» отдаёт как ``gone`` (трактуется как блокировка)."""
    return await send_via_client_bot(chat_id, text_body, buttons, detect_gone=True, photo=photo)


# Картинка уже лежит у Telegram: шлём её ``file_id``, а не грузим файл заново каждому (пятничная рассылка — сотни
# одинаковых постеров). Ключ — путь и время изменения файла: заменили постер — загрузится заново.
_PHOTO_IDS: dict[tuple[str, float], str] = {}


async def _send_photo(bot: Any, chat_id: int, photo: str, caption: str, markup: Any) -> None:
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.types import FSInputFile

    try:
        key = (photo, os.path.getmtime(photo))
    except OSError:
        key = (photo, 0.0)
    cached = _PHOTO_IDS.get(key)
    if cached:
        try:
            await bot.send_photo(chat_id=chat_id, photo=cached, caption=caption, reply_markup=markup)
            return
        except TelegramBadRequest as exc:
            if "file" not in str(exc).lower():
                raise
            _PHOTO_IDS.pop(key, None)  # file_id устарел (другой бот, чистка у Telegram) — загрузим файл
    sent = await bot.send_photo(chat_id=chat_id, photo=FSInputFile(photo), caption=caption, reply_markup=markup)
    sizes = getattr(sent, "photo", None) or []
    if sizes:
        _PHOTO_IDS[key] = sizes[-1].file_id


async def send_via_client_bot(
    chat_id: int,
    text_body: str,
    buttons: list[list[dict]],
    *,
    detect_gone: bool = False,
    bot: Any = None,
    photo: str | None = None,
) -> str:
    """Личное сообщение клиентским ботом: ``ok``, ``blocked`` (запретил писать), ``retry`` (429, сеть, 5xx —
    повторим позже) или ``failed`` (BadRequest и прочее постоянное).

    ``bot`` — свой экземпляр у другого цикла (прогрев, TASK-428): общий ``_bot`` закрывает цикл матчей в конце
    прохода, и чужая отправка в этот момент упала бы на закрытой сессии. ``photo`` — путь к картинке: тогда уходит
    фото с текстом в подписи (sendPhoto)."""
    from aiogram.exceptions import (
        TelegramBadRequest,
        TelegramForbiddenError,
        TelegramNetworkError,
        TelegramRetryAfter,
        TelegramServerError,
    )
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    bot = bot if bot is not None else await _client_bot()
    if bot is None:
        return FAILED
    markup = (
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(**b) for b in row] for row in buttons])
        if buttons
        else None
    )
    for attempt in (1, 2):
        await _throttle()
        try:
            if photo:
                await _send_photo(bot, int(chat_id), photo, text_body, markup)
            else:
                await bot.send_message(chat_id=int(chat_id), text=text_body, reply_markup=markup)
            return SENT
        except TelegramForbiddenError:
            logger.info("kto-kogo notice to %s: bot blocked", chat_id)
            return BLOCKED
        except TelegramRetryAfter as exc:
            if attempt == 2 or exc.retry_after > _RETRY_AFTER_CAP_SEC:
                logger.info("kto-kogo notice to %s: 429, retry later (%ss)", chat_id, exc.retry_after)
                return RETRY
            await asyncio.sleep(exc.retry_after)
        except (TimeoutError, TelegramNetworkError, TelegramServerError):
            logger.info("kto-kogo notice to %s: temporary error, retry later", chat_id, exc_info=True)
            return RETRY
        except TelegramBadRequest as exc:
            if detect_gone and any(p in str(exc).lower() for p in _GONE_PHRASES):
                logger.info("kto-kogo notice to %s: chat gone", chat_id)
                return GONE
            logger.info("kto-kogo notice to %s not delivered", chat_id, exc_info=True)
            return FAILED
        except Exception:  # noqa: BLE001 — прочее постоянное: не повторяем
            logger.info("kto-kogo notice to %s not delivered", chat_id, exc_info=True)
            return FAILED
    return RETRY


__all__ = [
    "BLOCKED",
    "GONE",
    "CB_LEAVE",
    "CB_NEXT",
    "CB_OFF",
    "CB_PICK",
    "ChatPick",
    "KIND_MFINAL",
    "KIND_MOVED",
    "KIND_MOVED_FREE",
    "KIND_NOMOVE",
    "KIND_OVERTOOK",
    "KIND_RESULT",
    "Notice",
    "Overtake",
    "START_EVENING",
    "START_LEAGUE",
    "START_MONTH",
    "START_OFF",
    "START_PICK",
    "TYPE_CODES",
    "chat_pick",
    "claim",
    "close_client_bot",
    "clear_blocked",
    "cleanup_old_notices",
    "deliver",
    "cap_line",
    "deliver_league_notices",
    "deliver_outfit_notices",
    "due_notices",
    "fan_club",
    "get_prefs",
    "in_quiet_hours",
    "mark_blocked",
    "mark_done",
    "next_move",
    "picked_buttons",
    "queue_moved",
    "release",
    "remind_on",
    "result_text",
    "scan_league_ranks",
    "send_via_client_bot",
    "send_via_client_bot_gone",
    "set_consent",
    "set_fav_club",
    "set_remind",
    "set_type",
]
