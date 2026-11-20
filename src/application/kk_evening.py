"""«Кто кого»: табло вечера — итоги ходов одним сообщением на игрока и игровой день (PDEC-038, TASK-434).

Вечер — матчи с ходом игрока, начавшиеся в одни сутки по Минску (``game_day``). Правила доставки (владелец,
2026-11-20, закреплены в TASK-434):

* итог матча готов — ``final`` + ``RESULT_SEND_DELAY``, не на ручной проверке (``hold_until``);
* готова часть вечера, табло нет — новое сообщение-табло; табло есть — правка (без звука);
* готов весь вечер — финальная правка табло (если было) и новое «Итог вечера»; всё готово сразу (один матч,
  утро после тихих часов) — только «Итог вечера»;
* матч с ходом начался больше ``STUCK_AFTER`` назад без итога — вечер закрываем без него («итог позже»);
  его итог потом — коротким отдельным сообщением (``late``), как и любой итог уже закрытого вечера.

Здесь — только решение «что отправить» и тексты. Отправка, занятие строк и повторы — в ``hockey_notices.deliver``.
"""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_game import PICK_CLOSES_BEFORE, POINTS_EXACT
from src.application.hockey_league_evening import day_bounds, game_day
from src.application.hockey_slices import Row, club_scope, league_rows, season_period, slice_rows
from src.application.hockey_teams import display_name as club_name
from src.ingestion.hockey_sources import MINSK_TZ

# Матч с ходом без итога дольше этого после начала — вечер закрываем без него (TASK-434, решение 1).
STUCK_AFTER = timedelta(hours=4)
# Сколько открытых чужих матчей перечислять в строке «Ещё сегодня без твоего хода».
OPEN_OTHERS_MAX = 3
# Строка «В других матчах вечера» — только если по матчу набралось столько ходов: на паре ходов доли пустые.
OTHERS_MIN_PICKS = 3
LEAGUES_MAX = 3

ACTION_BOARD = "board"  # новое табло или правка существующего
ACTION_FINAL = "final"  # «Итог вечера» (и финальная правка табло, если оно было)
ACTION_LATE = "late"  # итог матча уже закрытого вечера — коротким отдельным сообщением

_QUIPS_PATH = Path(__file__).resolve().parents[1] / "shared" / "kk_quips_ru.json"


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _hhmm(value: datetime) -> str:
    return _utc(value).astimezone(MINSK_TZ).strftime("%H:%M")


# ---------- фразы ----------


@lru_cache(maxsize=1)
def quips() -> dict[str, list[str]]:
    data = json.loads(_QUIPS_PATH.read_text(encoding="utf-8"))
    return {k: list(v) for k, v in data.items() if not k.startswith("_")}


def _seed(player_key: int, kind: str, salt: str) -> int:
    digest = hashlib.sha256(f"{player_key}:{kind}:{salt}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def quip_index(player_key: int, day: date, kind: str, size: int) -> int:
    """Номер фразы на вечер: у каждого игрока свой старт и свой шаг по дням. Шаг от 1 до ``size - 1`` — соседние
    вечера по построению получают разные фразы (без хранения, что выпало вчера)."""
    if size <= 1:
        return 0
    start = _seed(player_key, kind, "start") % size
    step = 1 + _seed(player_key, kind, "step") % (size - 1)
    return (start + step * day.toordinal()) % size


def pick_quip(kind: str, *, player_key: int, day: date, n: int) -> str | None:
    """Случайная для игрока фраза ситуации; два вечера подряд одна и та же не выпадает.

    Фраз с ``{n}`` в вечер одного матча не берём: «Ноль из 1» звучит как ошибка."""
    pool = [q for q in quips().get(kind, []) if n > 1 or "{n}" not in q]
    if not pool:
        return None
    return pool[quip_index(player_key, day, kind, len(pool))].replace("{n}", str(n))


# ---------- данные вечера ----------


@dataclass(frozen=True)
class EveningPick:
    match_id: int
    home_team: str
    away_team: str
    starts_at: datetime
    league: str | None
    status: str
    final_home: int | None
    final_away: int | None
    side: str | None
    home_score: int | None
    away_score: int | None
    doubled: bool
    points: int | None
    ready: bool  # итог готов к рассылке: final + задержка, не на проверке
    noticed: bool  # итог этого матча игроку уже ушёл (строка hockey_notices kind=result)
    # Для строки «Трибуны» у вечера из одного матча: сколько ходили за хозяев/гостей и угадали тот же счёт.
    home_picks: int = 0
    away_picks: int = 0
    same_exact: int = 0

    @property
    def total(self) -> int:
        return (self.points or 0) * (2 if self.doubled else 1)

    def as_match(self) -> dict:
        return {
            "match_id": self.match_id,
            "starts_at": self.starts_at,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "league": self.league,
        }


@dataclass(frozen=True)
class Board:
    message_id: int | None
    closed: bool


@dataclass(frozen=True)
class Step:
    """Что сделать с вечером игрока за этот проход."""

    action: str
    player_key: int
    day: date
    anchor_match_id: int  # якорь «Итога вечера» в hockey_notices (kind=evening)
    claim: tuple[int, ...]  # итоги матчей, которые занимает этот шаг (kind=result)
    picks: tuple[EveningPick, ...] = field(default=())
    board: Board | None = None


_EVENING_PICKS = text("""
    SELECT m.id AS match_id, m.home_team, m.away_team, m.starts_at, m.league, m.status,
           m.home_score AS final_home, m.away_score AS final_away,
           p.side, p.home_score, p.away_score, p.doubled, p.points,
           (m.status = 'final' AND p.points IS NOT NULL AND m.finalized_at <= :ready
            AND (m.result_probe->>'hold_until' IS NULL
                 OR CAST(m.result_probe->>'hold_until' AS TIMESTAMPTZ) <= :now)) AS ready,
           EXISTS (SELECT 1 FROM hockey_notices AS n
                   WHERE n.player_key = p.player_key AND n.match_id = m.id AND n.kind = 'result') AS noticed,
           (SELECT COUNT(*) FROM hockey_picks x WHERE x.match_id = m.id AND x.side = 'home')::int AS home_picks,
           (SELECT COUNT(*) FROM hockey_picks x WHERE x.match_id = m.id AND x.side = 'away')::int AS away_picks,
           (SELECT COUNT(*) FROM hockey_picks x
            WHERE x.match_id = m.id AND x.player_key <> p.player_key
              AND x.home_score = p.home_score AND x.away_score = p.away_score)::int AS same_exact
    FROM hockey_picks AS p
    JOIN game_matches AS m ON m.id = p.match_id
    WHERE p.player_key = :player_key AND m.starts_at >= :since AND m.starts_at < :until AND m.status <> 'cancelled'
    ORDER BY m.starts_at, m.id
    """)

_BOARD = text("SELECT message_id, closed_at FROM hockey_evening_boards WHERE player_key = :player_key AND day = :day")

_SAVE_BOARD = text("""
    INSERT INTO hockey_evening_boards (player_key, day, message_id) VALUES (:player_key, :day, :message_id)
    ON CONFLICT (player_key, day) DO UPDATE SET message_id = EXCLUDED.message_id, updated_at = now()
    """)

_CLOSE_BOARD = text("""
    INSERT INTO hockey_evening_boards (player_key, day, closed_at) VALUES (:player_key, :day, :now)
    ON CONFLICT (player_key, day) DO UPDATE SET closed_at = EXCLUDED.closed_at, updated_at = now()
    """)

# Открытые табло последних двух суток: вечер может закрыться и без нового итога — по зависшему матчу.
_OPEN_BOARDS = text("""
    SELECT player_key, day FROM hockey_evening_boards
    WHERE closed_at IS NULL AND message_id IS NOT NULL AND day >= :since_day
    """)


async def evening_picks(session: AsyncSession, *, player_key: int, day: date, now: datetime) -> list[EveningPick]:
    from src.application.hockey_notices import RESULT_SEND_DELAY

    since, until = day_bounds(day)
    params = {
        "player_key": player_key,
        "since": since,
        "until": until,
        "ready": _utc(now) - RESULT_SEND_DELAY,
        "now": _utc(now),
    }
    return [EveningPick(**r._mapping) for r in (await session.execute(_EVENING_PICKS, params)).all()]


async def load_board(session: AsyncSession, *, player_key: int, day: date) -> Board | None:
    r = (await session.execute(_BOARD, {"player_key": player_key, "day": day})).one_or_none()
    return None if r is None else Board(message_id=r.message_id, closed=r.closed_at is not None)


async def save_board(session: AsyncSession, *, player_key: int, day: date, message_id: int | None) -> None:
    await session.execute(_SAVE_BOARD, {"player_key": player_key, "day": day, "message_id": message_id})


async def close_board(session: AsyncSession, *, player_key: int, day: date, now: datetime) -> None:
    await session.execute(_CLOSE_BOARD, {"player_key": player_key, "day": day, "now": _utc(now)})


async def open_board_days(session: AsyncSession, *, now: datetime) -> list[tuple[int, date]]:
    since_day = game_day(now) - timedelta(days=1)
    return [(r.player_key, r.day) for r in (await session.execute(_OPEN_BOARDS, {"since_day": since_day})).all()]


def is_stuck(p: EveningPick, now: datetime) -> bool:
    return not p.ready and _utc(now) - _utc(p.starts_at) > STUCK_AFTER


def decide(
    *, player_key: int, day: date, picks: list[EveningPick], board: Board | None, now: datetime
) -> Step | None:
    """Чистое решение по вечеру: что отправить этим проходом. ``None`` — ничего.

    Занимаем только готовые, ещё не разосланные итоги. Закрыть вечер можно, когда у каждого хода итог готов
    или матч завис дольше ``STUCK_AFTER``."""
    if not picks:
        return None
    fresh = tuple(p.match_id for p in picks if p.ready and not p.noticed)
    anchor = min(p.match_id for p in picks)
    if board is not None and board.closed:
        if not fresh:
            return None
        return Step(ACTION_LATE, player_key, day, anchor, fresh, tuple(picks), board)
    done = all(p.ready or is_stuck(p, now) for p in picks)
    any_ready = any(p.ready for p in picks)
    if done and any_ready:
        if not fresh and (board is None or board.message_id is None):
            return None  # нечего сообщать: итоги уже ушли иначе (старые итоги до табло)
        return Step(ACTION_FINAL, player_key, day, anchor, fresh, tuple(picks), board)
    if not fresh:
        return None
    return Step(ACTION_BOARD, player_key, day, anchor, fresh, tuple(picks), board)


# ---------- тексты ----------


def _name(team: str) -> str:
    return html.escape(club_name(team))


def _your(p: EveningPick) -> str:
    if p.home_score is not None and p.away_score is not None:
        return f"{p.home_score}:{p.away_score}"
    if p.side == "home":
        return _name(p.home_team)
    if p.side == "away":
        return _name(p.away_team)
    return "—"


def _gain(p: EveningPick) -> str:
    trump = " с козырем" if p.doubled else ""
    if p.points == POINTS_EXACT:
        return f"в точку! <b>+{p.total}</b>{trump}"
    if p.points:
        return f"<b>+{p.total}</b>{trump}"
    return "0"


def match_line(p: EveningPick, now: datetime) -> str:
    """Строка табло: итог с очками, либо ожидание («в 19:55», «идёт», «итог позже»)."""
    if p.ready:
        mark = "🎯" if p.points else "❌"
        return (
            f"{mark} <b>{_name(p.home_team)} — {_name(p.away_team)} {p.final_home}:{p.final_away}</b>"
            f" · твой {_your(p)} · {_gain(p)}"
        )
    if is_stuck(p, now):
        state = "итог позже"
    elif _utc(p.starts_at) > _utc(now):
        state = f"в {_hhmm(p.starts_at)}"
    else:
        state = "идёт"
    return f"⏳ {_name(p.home_team)} — {_name(p.away_team)} · твой {_your(p)} · {state}"


def _day_title(day: date) -> str:
    from src.application.hockey_notices import MONTHS_GEN

    return f"{day.day} {MONTHS_GEN[day.month - 1].upper()}"


@dataclass(frozen=True)
class OpenMatch:
    match_id: int
    home_team: str
    away_team: str
    starts_at: datetime


def board_text(
    *, day: date, picks: list[EveningPick], now: datetime, open_matches: list[OpenMatch], fan: OpenMatch | None
) -> str:
    done = [p for p in picks if p.ready]
    lines = [match_line(p, now) for p in picks]
    if fan is not None:
        lines.append(
            f"⏳ {_name(fan.home_team)} — {_name(fan.away_team)} · хода нет, ещё открыт до "
            f"{_hhmm(_utc(fan.starts_at) - PICK_CLOSES_BEFORE)}"
        )
    total = sum(p.total for p in done)
    finished = len(done) == len(picks)
    out = (
        f"🏒 <b>ВЕЧЕР {_day_title(day)}</b> · {len(done)} из {len(picks)} {_matches_word(len(picks))}\n\n"
        + "\n".join(lines)
        + f"\n\n{'За вечер' if finished else 'За вечер пока'}: <b>{_signed(total)}</b>"
    )
    others = [m for m in open_matches if fan is None or m.match_id != fan.match_id][:OPEN_OTHERS_MAX]
    if others and not finished:
        listed = "; ".join(f"{_name(m.home_team)} — {_name(m.away_team)}, {_hhmm(m.starts_at)}" for m in others)
        out += f"\n\nЕщё сегодня без твоего хода: {listed}"
    return out


def _matches_word(n: int) -> str:
    return "твоего матча" if n % 10 == 1 and n % 100 != 11 else "твоих матчей"


def _signed(n: int) -> str:
    return f"+{n}" if n > 0 else str(n)


_EXACT_WORDS = {1: "одно", 2: "два", 3: "три", 4: "четыре"}


def _exact_clause(n: int) -> str:
    return f"{_EXACT_WORDS.get(n, str(n))} «в точку»" if n else ""


@dataclass(frozen=True)
class PlaceChange:
    title: str
    before: int | None
    after: int
    size: int
    passed: tuple[str, ...] = ()  # кто был выше, а теперь ниже (только в лигах — там все свои)


def place_line(c: PlaceChange) -> str:
    if c.before is None:
        return f"{c.title}: <b>{c.after}-е</b> из {c.size}, ты в таблице"
    if c.after < c.before:
        line = f"{c.title}: <b>{c.before}-е → {c.after}-е ↑</b> из {c.size}"
        if c.passed:
            names = [html.escape(n) for n in c.passed[:2]]
            rest = len(c.passed) - len(names)
            who = " и ".join(names) if not rest else f"{', '.join(names)} и ещё {rest}"
            line += f", позади: {who}"
        return line
    if c.after > c.before:
        return f"{c.title}: <b>{c.before}-е → {c.after}-е ↓</b> из {c.size}"
    return f"{c.title}: <b>{c.after}-е</b> из {c.size}, держишься"


def _change(title: str, before: list[Row], after: list[Row], player_key: int, *, names: bool) -> PlaceChange | None:
    mine_after = next((r for r in after if r.player_key == player_key), None)
    if mine_after is None:
        return None
    mine_before = next((r for r in before if r.player_key == player_key), None)
    passed: tuple[str, ...] = ()
    if names and mine_before is not None:
        before_rank = {r.player_key: r.rank for r in before}
        after_rank = {r.player_key: r.rank for r in after}
        passed = tuple(
            r.display_name
            for r in before
            if r.player_key != player_key
            and before_rank[r.player_key] < mine_before.rank
            and after_rank.get(r.player_key, 10**6) > mine_after.rank
        )
    return PlaceChange(title, mine_before.rank if mine_before else None, mine_after.rank, len(after), passed)


def _points_of(rows: list[Row], player_key: int) -> int | None:
    return next((r.points for r in rows if r.player_key == player_key), None)


async def place_changes(
    session: AsyncSession, *, player_key: int, day: date, fan: str | None, now: datetime
) -> tuple[list[PlaceChange], int]:
    """Места «до вечера → после»: общая таблица сезона, срез своей команды и лиги, где очки вечера что-то
    изменили. Срез считается по матчам с началом в окне, поэтому «до» — окно, кончающееся началом вечера.
    Второе значение — число строк про лиги (они идут после общих)."""
    from src.application.hockey_leagues import _LEAGUE_COLUMNS, _league, player_leagues

    start, end = day_bounds(day)
    season = season_period(start)
    out: list[PlaceChange] = []
    slices: list[tuple[str, str | None]] = [("Общая таблица", None)]
    if fan:
        slices.append((f"Таблица «{club_name(fan)}»", fan))
    for title, club in slices:
        before_p, after_p = replace(season, until=max(season.since, start)), replace(season, until=end)
        before = await slice_rows(session, scope=club_scope(club), period=before_p)
        after = await slice_rows(session, scope=club_scope(club), period=after_p)
        if club is not None and _points_of(before, player_key) == _points_of(after, player_key):
            continue  # своя команда сегодня не играла в ходах игрока
        found = _change(title, before, after, player_key, names=False)
        if found is None:
            continue
        if club is not None and out and (out[0].before, out[0].after, out[0].size) == (
            found.before,
            found.after,
            found.size,
        ):
            continue  # срез своей команды повторяет общую таблицу — вторая строка ничего не добавляет
        out.append(found)
    general = len(out)
    summaries = await player_leagues(session, player_key=player_key, now=now, with_rank=False)
    if summaries:
        ids = [s.id for s in summaries]
        records = (
            await session.execute(
                text(f"SELECT {_LEAGUE_COLUMNS} FROM hockey_leagues WHERE id = ANY(:ids) ORDER BY id"), {"ids": ids}
            )
        ).all()
        for league in (_league(r) for r in records):
            since = _utc(league.starts_at)
            if since >= end:
                continue
            until_end = min(end, _utc(league.ends_at))
            before = await league_rows(
                session, league_id=league.id, scope=league.match_scope, since=since, until=max(since, start)
            )
            after = await league_rows(session, league_id=league.id, scope=league.match_scope, since=since, until=until_end)
            if _points_of(before, player_key) == _points_of(after, player_key):
                continue
            found = _change(f"Лига «{league.name}»", before, after, player_key, names=True)
            if found is not None:
                out.append(found)
            if len(out) - general >= LEAGUES_MAX:
                break
    return out, len(out) - general


_OTHER_MATCHES = text("""
    SELECT m.id, m.home_team, m.away_team, m.home_score, m.away_score,
           COUNT(x.player_key)::int AS picks,
           COUNT(*) FILTER (WHERE x.points = :exact)::int AS exact,
           COUNT(*) FILTER (WHERE x.points >= :winner)::int AS winner
    FROM game_matches AS m
    JOIN hockey_picks AS x ON x.match_id = m.id AND x.points IS NOT NULL
    WHERE m.status = 'final' AND m.starts_at >= :since AND m.starts_at < :until
      AND NOT EXISTS (SELECT 1 FROM hockey_picks AS p WHERE p.match_id = m.id AND p.player_key = :player_key)
    GROUP BY m.id, m.home_team, m.away_team, m.home_score, m.away_score, m.starts_at
    HAVING COUNT(x.player_key) >= :min_picks
    ORDER BY COUNT(x.player_key) DESC, m.starts_at
    LIMIT 1
    """)


async def other_match_line(session: AsyncSession, *, player_key: int, day: date) -> str | None:
    from src.application.hockey_game import POINTS_WINNER

    since, until = day_bounds(day)
    params = {
        "since": since,
        "until": until,
        "player_key": player_key,
        "exact": POINTS_EXACT,
        "winner": POINTS_WINNER,
        "min_picks": OTHERS_MIN_PICKS,
    }
    r = (await session.execute(_OTHER_MATCHES, params)).one_or_none()
    if r is None:
        return None
    head = f"{_name(r.home_team)} — {_name(r.away_team)} {r.home_score}:{r.away_score}"
    if r.exact:
        tail = f"точный счёт угадали {r.exact} из {r.picks}"
    elif r.winner:
        tail = f"победителя угадали {r.winner} из {r.picks}"
    else:
        tail = f"победителя не угадал никто из {r.picks}"
    return f"В других матчах вечера: {head}, {tail}"


def quip_kind(picks: list[EveningPick], changes: list[PlaceChange]) -> str:
    done = [p for p in picks if p.ready]
    hits = [p for p in done if p.points]
    if len(done) > 1 and len(hits) == len(done):
        return "perfect"
    if any(c.title.startswith("Лига") and c.after == 1 and c.before not in (None, 1) for c in changes):
        return "league_top"
    if any(p.points == POINTS_EXACT for p in done):
        return "exact"
    if not hits:
        return "zero"
    if len(done) == 1:
        return "hit"  # один матч, победитель угадан: «половина в цель» тут не про то
    general = changes[0] if changes and changes[0].title == "Общая таблица" else None
    if general and general.before is not None and general.after < general.before:
        return "climbed"
    if general and general.before is not None and general.after > general.before:
        return "dropped"
    return "mixed"


def final_header(picks: list[EveningPick], *, with_lines: bool, now: datetime) -> str:
    """Шапка «Итога вечера». Один матч — его строка; несколько — сумма, попадания и «в точку»."""
    done = [p for p in picks if p.ready]
    if len(picks) == 1 and done:
        p = done[0]
        return (
            f"<b>{_name(p.home_team)} — {_name(p.away_team)} {p.final_home}:{p.final_away}</b>"
            f" · твой {_your(p)} · {_gain(p)}"
        )
    total = sum(p.total for p in done)
    hits = sum(1 for p in done if p.points)
    exact = sum(1 for p in done if p.points == POINTS_EXACT)
    tail = ", ".join(x for x in (f"{hits} из {len(done)}", _exact_clause(exact)) if x)
    head = f"<b>Вечер закрыт: {_signed(total)}</b> · {tail}"
    if with_lines:
        head += "\n\n" + "\n".join(match_line(p, now) for p in picks)
    return head


def late_text(p: EveningPick) -> str:
    """Итог матча уже закрытого вечера: одна строка, без мест — места были в «Итоге вечера»."""
    return f"Итог позже, чем вечер: {match_line(p, datetime.now(timezone.utc))}"


__all__ = [
    "ACTION_BOARD",
    "ACTION_FINAL",
    "ACTION_LATE",
    "Board",
    "EveningPick",
    "OpenMatch",
    "PlaceChange",
    "STUCK_AFTER",
    "Step",
    "board_text",
    "close_board",
    "decide",
    "evening_picks",
    "final_header",
    "is_stuck",
    "late_text",
    "load_board",
    "match_line",
    "open_board_days",
    "other_match_line",
    "pick_quip",
    "place_changes",
    "place_line",
    "quip_kind",
    "quips",
    "save_board",
]
