"""Бот «Кто кого»: четыре повода написать игроку и ход прямо из чата (TASK-334 S6, PDEC-031).

Поводы, по убыванию важности:

* ``result`` — итог хода: очки и место. Единственный, что не считается в дневной бюджет;
  если за один проход итогов несколько, уходит одно сообщение-сводка.
* ``mfinal`` — финал месяца: «корона решится сегодня» (клуб игрока, последний матч месяца, 12:00 по Минску).
* ``overtook`` — тебя обошли в лиге.
* ``nomove`` — нет хода за 3 часа до матча «своей» команды.

Бюджет: не больше одного сообщения в день (сутки по Минску) на игрока, кроме итогов. Из повода, что
мог бы уйти в один проход, выбирается более важный; остальные в тот же день не уходят. Часы тишины
23:00–09:00 по Минску: ничего не шлём, итог откладывается до утра.

«Своя» команда — «болею за» из настроек, иначе клуб, за который игрок чаще всего ходил за последние
30 дней; без ходов поводов про команду нет. Включает сам игрок (``remind``), каждый тип отключается
отдельно; заблокировавшему бота больше не пишем, пока он снова не зайдёт.

Сообщение сначала «занимается» строкой в ``hockey_notices`` и только потом уходит: второй цикл
или повтор тика не пришлёт его дважды. Сбой отправки не повторяем.

Ход из чата — тот же ``hockey_game.make_pick``, что у Mini App: срок закрытия и запись одни и те же.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_game import (
    DEFAULT_PLAYER_NAME,
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
from src.ingestion.hockey_sources import MINSK_TZ

logger = logging.getLogger(__name__)

KIND_NOMOVE = "nomove"
KIND_RESULT = "result"
KIND_OVERTOOK = "overtook"
KIND_MFINAL = "mfinal"
KIND_BEFORE = "before"  # прежнее «за час»: больше не шлём, записи остались в таблице
# Приоритет внутри дневного бюджета (меньше — важнее).
PRIORITY = {KIND_MFINAL: 0, KIND_OVERTOOK: 1, KIND_NOMOVE: 2}
# Короткие коды типов в callback_data (лимит Telegram — 64 байта).
TYPE_CODES = {"nm": KIND_NOMOVE, "rs": KIND_RESULT, "ot": KIND_OVERTOOK, "mf": KIND_MFINAL}
CODE_OF = {v: k for k, v in TYPE_CODES.items()}
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
    KIND_MFINAL: "финал месяца",
}

NOMOVE_AHEAD = timedelta(hours=3)
# Напоминать о матче, который начнётся вот-вот, незачем: ход закрывается за минуту до старта.
NOMOVE_MIN_LEFT = timedelta(minutes=15)
FAN_WINDOW = timedelta(days=30)
# Итог шлём, пока он свежий; ночной итог, отложенный до 09:00, остаётся свежим и утром.
RESULT_FRESH = timedelta(hours=6)
RESULT_FRESH_AFTER_NIGHT = timedelta(hours=16)
QUIET_FROM, QUIET_TO = 23, 9
MFINAL_FROM_HOUR = 12
# В «корону решится сегодня» зовём тех, у кого она ещё в досягаемости.
MFINAL_TOP = 3

# Параметры ссылок в Mini App (glide-deeplink.js).
START_PICK = "kkn"
START_MONTH = "kkmo"
START_OFF = "kkoff"
START_LEAGUE = "kkl"

# callback_data кнопок в чате.
CB_PICK = "kk:p"  # kk:p:<матч>:<h|a>
CB_NEXT = "kk:n"
CB_OFF = "kk:off"  # kk:off:<тип>
CB_LEAVE = "kk:lv"  # kk:lv:<лига>

SENT = "ok"
BLOCKED = "blocked"
FAILED = "failed"

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


def in_quiet_hours(now: datetime) -> bool:
    hour = _local(now).hour
    return hour >= QUIET_FROM or hour < QUIET_TO


def day_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Сутки по Минску, в которые попадает ``now``, — в UTC."""
    start = _local(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


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

_MARK_BLOCKED = text("""
    UPDATE hockey_player_prefs SET bot_blocked_at = :now, updated_at = now() WHERE player_key = :player_key
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
    """Включить или отключить один тип сообщений. ``kind`` — один из ``TYPE_COLUMN`` или ``league``."""
    column = "notify_league" if kind == "league" else TYPE_COLUMN[kind]
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
    SELECT p.player_key, m.id AS match_id, m.home_team, m.away_team, m.starts_at,
           m.home_score AS final_home, m.away_score AS final_away,
           p.side, p.home_score, p.away_score, p.doubled, p.points
    FROM hockey_picks AS p
    JOIN hockey_players AS pl ON pl.player_key = p.player_key
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = p.player_key
    JOIN game_matches AS m ON m.id = p.match_id AND m.status = 'final' AND m.finalized_at > :fresh
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
    WHERE sent_at >= :since AND sent_at < :until AND kind <> 'result'
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
    from src.application.place_links import telegram_open_link
    from src.shared.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    return telegram_open_link(
        client_bot_username=settings.client_bot_username,
        mini_app_short_name=settings.client_mini_app_short_name,
        main_mini_app=settings.client_bot_main_mini_app,
        start_param=start_param,
    )


def url_button(label: str, start_param: str) -> dict | None:
    url = _link(start_param)
    return {"text": label, "url": url} if url else None


def pick_buttons(match_id: int, home: str, away: str) -> list[dict]:
    """Ход в один тап: за хозяев или за гостей. Ту же запись делает Mini App."""
    return [
        {"text": home, "callback_data": f"{CB_PICK}:{match_id}:h"},
        {"text": away, "callback_data": f"{CB_PICK}:{match_id}:a"},
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
    return {0: "сегодня", 1: "завтра"}.get(days, _local(starts_at).strftime("%d.%m"))


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
        f"<b>{html.escape(home)} — {html.escape(away)}</b> {_day_word(starts_at, now)} в {_hhmm(starts_at)}. "
        "Хода ещё нет — тапни прямо здесь."
    )


def result_text(
    *,
    home: str,
    away: str,
    final_home: int,
    final_away: int,
    points: int,
    doubled: bool,
    place: str | None,
) -> str:
    """``points`` — базовые очки хода; ``place`` — готовая строка про место, если есть где его назвать."""
    total = points * (2 if doubled else 1)
    x2 = " с ×2" if doubled else ""
    if points == POINTS_EXACT:
        verdict = f"В точку: +{total}{x2}."
    elif points:
        verdict = f"+{total} {_points_word(total)}{x2}."
    else:
        verdict = "В этот раз мимо."
    out = f"<b>{html.escape(home)} — {html.escape(away)} {final_home}:{final_away}.</b> {verdict}"
    return out + ("\n" + place if place else "")


def summary_text(lines: list[str]) -> str:
    return "<b>Итоги твоих ходов</b>\n" + "\n".join(lines)


def _slice_title(club: str | None, period: Period) -> str:
    return f"{club or 'общая таблица'} · {period.title}"


async def _rows_cached(session: AsyncSession, cache: dict, club: str | None, period: Period):
    key = (club, period.key)
    if key not in cache:
        cache[key] = await slice_rows(session, scope=club_scope(club), period=period)
    return cache[key]


async def best_place_line(
    session: AsyncSession, *, player_key: int, home: str, away: str, starts_at: datetime, cache: dict
) -> str | None:
    """Лучшее место игрока среди срезов матча (команды и «все», месяц и сезон), где есть с кем сравнивать."""
    month = month_period(_local(starts_at).date())
    season = season_period(starts_at)
    best: tuple[float, int, int, str] | None = None
    for club in (home, away, None):
        for period in (month, season):
            rows = await _rows_cached(session, cache, club, period)
            mine = next((r for r in rows if r.player_key == player_key), None)
            if mine is None or not crown_eligible(rows):
                continue
            key = (mine.rank / len(rows), -len(rows), mine.rank, _slice_title(club, period))
            if best is None or key < best:
                best = key
    if best is None:
        return None
    _, neg_size, rank, title = best
    return f"Твоё место: {_ordinal(rank)} из {-neg_size} · {title}."


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
    SELECT id, name, invite_code, owner_key, scope, clubs, term_kind, starts_at, ends_at FROM hockey_leagues
    WHERE starts_at <= :now AND ends_at > :now
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
            f"\n{html.escape(nxt.home_team)} — {html.escape(nxt.away_team)}, "
            f"{_day_word(nxt.starts_at, now)} в {_hhmm(nxt.starts_at)} — шанс вернуть."
        )
        if not (await session.execute(_HAS_PICK, {"match_id": nxt.match_id, "player_key": o.player_key})).first():
            rows.append(list(pick_buttons(nxt.match_id, nxt.home_team, nxt.away_team)))
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
    for r in (await session.execute(_DUE_RESULT, {"fresh": _utc(fresh)})).all():
        by_player.setdefault(r.player_key, []).append(r)
    out: list[Notice] = []
    for player_key, rows in by_player.items():
        texts: list[str] = []
        for r in rows:
            place = await best_place_line(
                session, player_key=player_key, home=r.home_team, away=r.away_team, starts_at=r.starts_at, cache=cache
            )
            texts.append(
                result_text(
                    home=r.home_team,
                    away=r.away_team,
                    final_home=r.final_home,
                    final_away=r.final_away,
                    points=r.points,
                    doubled=bool(r.doubled),
                    place=place,
                )
            )
        if len(rows) == 1:
            body = texts[0]
        else:
            body = summary_text([t.replace("\n", " ") for t in texts])
        buttons = _rows(
            [
                {"text": "Следующий ход", "callback_data": CB_NEXT},
                url_button("Таблица", f"{START_PICK}_{rows[-1].match_id}"),
            ],
            off_button(KIND_RESULT),
        )
        out.append(
            Notice(KIND_RESULT, player_key, rows[0].match_id, body, buttons, also=tuple(r.match_id for r in rows[1:]))
        )
    return out


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
        buttons = _rows(list(pick_buttons(r.match_id, r.home_team, r.away_team)), off_button(KIND_NOMOVE))
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
            f"<b>Корона {MONTHS_GEN[local.month - 1]} решится сегодня:</b> "
            f"{html.escape(final.home_team)} — {html.escape(final.away_team)}, {_hhmm(final.starts_at)}, "
            "последний матч месяца. "
        )
        if mine.rank == 1:
            second = rivals[0] if rivals else None
            gap = mine.points - second.points if second else 0
            body += f"Ты на 1-м месте" + (
                f", {html.escape(second.display_name)} в {gap} {_points_word(gap)} позади." if second and gap else "."
            )
        else:
            leader = rows[0]
            gap = leader.points - mine.points
            body += (
                f"Ты на {_ordinal(mine.rank)} месте, до короны {gap} {_points_word(gap)}."
                if gap
                else f"Ты на {_ordinal(mine.rank)} месте — в очках вровень с первым."
            )
        has_pick = (await session.execute(_HAS_PICK, {"match_id": final.id, "player_key": fan.player_key})).first()
        buttons = _rows(
            [] if has_pick else list(pick_buttons(final.id, final.home_team, final.away_team)),
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


def _outcome(value: "bool | str") -> str:
    if value is True:
        return SENT
    if value is False or value is None:
        return FAILED
    return value


async def deliver(session_factory, *, now: datetime, send: Sender) -> dict[str, int]:
    """Сверить места в лигах, занять — закоммитить — отправить — отметить. Каждое сообщение — своя транзакция."""
    counts = {"sent": 0, "failed": 0, "blocked": 0}
    async with session_factory() as session:
        overtakes = await scan_league_ranks(session, now=now)
        await session.commit()
        notices = await due_notices(session, now=now, overtakes=overtakes)
    for notice in notices:
        async with session_factory() as session:
            if not await claim(session, notice):
                continue
            await session.commit()
        try:
            outcome = _outcome(await send(notice.player_key, notice.text, notice.buttons))
        except Exception:  # noqa: BLE001 — сбой одного сообщения не роняет остальные
            logger.warning("kto-kogo notice %s/%s failed", notice.kind, notice.match_id, exc_info=True)
            outcome = FAILED
        async with session_factory() as session:
            await mark_done(session, notice, ok=outcome == SENT, now=now)
            if outcome == BLOCKED:
                await mark_blocked(session, notice.player_key, now=now)
            await session.commit()
        counts[{SENT: "sent", BLOCKED: "blocked"}.get(outcome, "failed")] += 1
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
        return ChatPick("closed", match_id, teams.home_team, teams.away_team)
    except LookupError:
        return ChatPick("missing", match_id)
    await clear_blocked(session, player_key)
    return ChatPick("ok", match_id, teams.home_team, teams.away_team, full)


async def next_move(session: AsyncSession, *, player_key: int, now: datetime) -> Notice | None:
    """«Следующий ход»: ближайший матч «своей» команды (иначе любой), где у игрока ещё нет хода."""
    club = await fan_club(session, player_key, now=now)
    nxt = await _next_for(session, player_key, now=now, club=club) or (
        await _next_for(session, player_key, now=now, club=None) if club else None
    )
    if nxt is None:
        return None
    body = (
        f"<b>{html.escape(nxt['home_team'])} — {html.escape(nxt['away_team'])}</b> "
        f"{_day_word(nxt['starts_at'], now)} в {_hhmm(nxt['starts_at'])}. Твой ход?"
    )
    return Notice(
        "next",
        player_key,
        nxt["match_id"],
        body,
        _rows(list(pick_buttons(nxt["match_id"], nxt["home_team"], nxt["away_team"]))),
    )


def picked_buttons(match_id: int, home: str, away: str, side: str) -> list[list[dict]]:
    """После хода: выбранная сторона отмечена, сменить можно до старта."""
    mark = "✓ "
    return [
        [
            {"text": (mark if side == "home" else "") + home, "callback_data": f"{CB_PICK}:{match_id}:h"},
            {"text": (mark if side == "away" else "") + away, "callback_data": f"{CB_PICK}:{match_id}:a"},
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
        f"<b>Лига «{html.escape(name)}» продлена.</b> Те же люди, новый срок: {day(starts_at)} — "
        f"{day(_local(ends_at) - timedelta(minutes=1))}. Выйти можно в один тап."
    )


def league_extended_buttons(league_id: int, invite_code: str) -> list[list[dict]]:
    return _rows(
        [url_button("Открыть лигу", f"{START_LEAGUE}_{invite_code}")],
        [{"text": "Выйти из лиги", "callback_data": f"{CB_LEAVE}:{league_id}"}],
    )


async def deliver_league_notices(session_factory, *, now: datetime, send: Sender) -> dict[str, int]:
    """Письма «лига продлена». Ответ на действие владельца, поэтому вне дневного бюджета и без главного
    выключателя; не шлём тем, кто отключил этот тип или заблокировал бота. Ночью ждут утра."""
    counts = {"sent": 0, "failed": 0, "blocked": 0, "skipped": 0}
    if in_quiet_hours(now):
        return counts
    async with session_factory() as session:
        due = list((await session.execute(_DUE_LEAGUE_NOTICES)).all())
    for r in due:
        params = {"league_id": r.league_id, "player_key": r.player_key}
        async with session_factory() as session:
            if (await session.execute(_CLAIM_LEAGUE_NOTICE, {**params, "now": _utc(now)})).first() is None:
                continue
            await session.commit()
        if not r.wants or r.bot_blocked_at is not None:
            counts["skipped"] += 1
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
        async with session_factory() as session:
            await session.execute(
                _DONE_LEAGUE_NOTICE,
                {**params, "ok": outcome == SENT, "failed": outcome != SENT, "now": _utc(now)},
            )
            if outcome == BLOCKED:
                await mark_blocked(session, r.player_key, now=now)
            await session.commit()
        counts[{SENT: "sent", BLOCKED: "blocked"}.get(outcome, "failed")] += 1
    return counts


async def send_via_client_bot(chat_id: int, text_body: str, buttons: list[list[dict]]) -> str:
    """Личное сообщение клиентским ботом: ``ok``, ``blocked`` (запретил писать) или ``failed``."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.exceptions import TelegramForbiddenError
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from src.shared.config import Settings

    token = (Settings().telegram_bot_token_client or "").strip()  # type: ignore[call-arg]
    if not token:
        return FAILED
    markup = (
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(**b) for b in row] for row in buttons])
        if buttons
        else None
    )
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await bot.send_message(chat_id=int(chat_id), text=text_body, reply_markup=markup)
        return SENT
    except TelegramForbiddenError:
        logger.info("kto-kogo notice to %s: bot blocked", chat_id)
        return BLOCKED
    except Exception:  # noqa: BLE001 — BadRequest/сеть: не повторяем
        logger.info("kto-kogo notice to %s not delivered", chat_id, exc_info=True)
        return FAILED
    finally:
        await bot.session.close()


__all__ = [
    "BLOCKED",
    "CB_LEAVE",
    "CB_NEXT",
    "CB_OFF",
    "CB_PICK",
    "ChatPick",
    "KIND_MFINAL",
    "KIND_NOMOVE",
    "KIND_OVERTOOK",
    "KIND_RESULT",
    "Notice",
    "Overtake",
    "START_LEAGUE",
    "START_MONTH",
    "START_OFF",
    "START_PICK",
    "TYPE_CODES",
    "chat_pick",
    "claim",
    "clear_blocked",
    "deliver",
    "deliver_league_notices",
    "due_notices",
    "fan_club",
    "get_prefs",
    "in_quiet_hours",
    "mark_blocked",
    "mark_done",
    "next_move",
    "picked_buttons",
    "remind_on",
    "result_text",
    "scan_league_ranks",
    "send_via_client_bot",
    "set_fav_club",
    "set_remind",
    "set_type",
]
