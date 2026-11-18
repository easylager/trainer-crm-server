"""Лиги друзей «Кто кого»: создать, вступить по ссылке, таблица лиги, выйти, продлить (TASK-298, TASK-334).

Лига = название + набор команд (одна, несколько, вся Экстралига, Динамо, всё) + срок (до конца сезона,
месяц, 4 недели, плей-офф, свои даты). Таблица лиги — очки участников за матчи набора, начавшиеся в
сроке и после их вступления (владелец 2026-10-26): лига — соревнование с момента, когда вы в ней
встретились, без форы за прошлые недели. Поэтому в лиге и в общей таблице у человека могут быть
разные числа. Участник без очков стоит в таблице с нулём — друг, который только что вступил, виден сразу.
Короны лиги выдаёт ``hockey_races`` в конце срока (у сезонной лиги — ещё и за каждый месяц).
"""

from __future__ import annotations

import secrets
import unicodedata
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_game import DEFAULT_PLAYER_NAME, POINTS_EXACT, POINTS_WINNER
from src.application.hockey_slices import (
    DINAMO,
    MAX_YEAR,
    MIN_YEAR,
    Period,
    Scope,
    crown_eligible,
    league_rows,
    league_scope,
    month_period,
    season_period,
)
from src.application.hockey_slices_sql import SCOPE_SQL
from src.ingestion.hockey_sources import MINSK_TZ

NAME_MAX = 28
STAKE_MAX = 80
MAX_MEMBERS = 100
MAX_LEAGUES_PER_PLAYER = 20
# Список «мои лиги»: закончившиеся показываем ещё столько дней и не больше стольких лиг (таблица считается на каждую).
RECENTLY_ENDED_DAYS = 60
MY_LEAGUES_LIMIT = 40
MAX_CLUBS = 20
SCOPES = ("all", "extraliga", "dinamo", "clubs")
TERM_KINDS = ("season", "month", "weeks4", "playoff", "dates")
# Плей-офф по умолчанию — март-май сезона; точные даты календарь пока не отдаёт (решение в TASK-334).
PLAYOFF_FROM = (3, 1)
PLAYOFF_TO = (6, 1)
# Меньше матчей в сроке — предупреждаем при создании (пауза, вылет клуба).
FEW_MATCHES = 5
# Без похожих символов (0/O, 1/I/L): код читают с экрана и диктуют голосом.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8


class LeagueFull(Exception):
    """В лиге уже максимум участников."""


class TooManyLeagues(Exception):
    """Игрок уже в максимуме лиг."""


class AlreadyExtended(Exception):
    """Лига уже продлена, а продлевающий из продолжения вышел: показать ему чужую лигу нельзя."""


class InvalidTerms(ValueError):
    """Набор команд или срок лиги не годятся (текст — для человека)."""


@dataclass(frozen=True)
class Terms:
    scope: str
    clubs: tuple[str, ...]
    term_kind: str
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class League:
    id: int
    name: str
    invite_code: str
    owner_key: int
    scope: str = "dinamo"
    clubs: tuple[str, ...] = ()
    term_kind: str = "season"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    image_key: str | None = None  # картинка лиги в хранилище (TASK-361)
    stake_text: str | None = None  # «на что играем»

    @property
    def match_scope(self) -> Scope:
        return league_scope(self.scope, self.clubs)


@dataclass(frozen=True)
class LeagueSummary:
    id: int
    name: str
    invite_code: str
    is_owner: bool
    members: int
    my_rank: int | None  # None, если место не считали (with_rank=False)
    my_points: int | None
    scope: str = "dinamo"
    clubs: tuple[str, ...] = ()
    term_kind: str = "season"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    active: bool = True
    image_key: str | None = None
    stake_text: str | None = None


@dataclass(frozen=True)
class LeagueRow:
    rank: int
    player_key: int
    display_name: str
    points: int
    exact: int
    played: int
    correct: int = 0
    pid: str | None = None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def clean_name(name: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise ValueError("Назови лигу")
    if len(cleaned) > NAME_MAX:
        raise ValueError(f"Название до {NAME_MAX} символов")
    return cleaned


# Невидимые знаки формата (нулевая ширина, управление направлением письма) прячут текст и подменяют порядок букв:
# убираем. Соединители ZWJ/ZWNJ нужны составным символам и письмам вроде персидского — их оставляем.
_KEEP_INVISIBLE = frozenset("\u200c\u200d")


def clean_stake(value: str | None) -> str | None:
    """Строка «на что играем»: пробелы и переводы строк сжаты, невидимые знаки убраны. Пусто — ``None`` (строки нет)."""
    raw = "".join(
        ch
        for ch in (value or "")
        if ch.isspace() or ch in _KEEP_INVISIBLE or unicodedata.category(ch) not in ("Cc", "Cf", "Cs")
    )
    cleaned = " ".join(raw.split())
    if len(cleaned) > STAKE_MAX:
        raise ValueError(f"Строка до {STAKE_MAX} символов")
    return cleaned or None


def new_invite_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


def normalize_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


_PLAYER_UPSERT = text("""
    INSERT INTO hockey_players (player_key, display_name)
    VALUES (:player_key, :display_name)
    ON CONFLICT (player_key) DO NOTHING
    """)

# В квоту идут только действующие лиги: закончившаяся не мешает создать или продлить новую.
_COUNT_MY_LEAGUES = text("""
    SELECT COUNT(*) FROM hockey_league_members AS mb
    JOIN hockey_leagues AS l ON l.id = mb.league_id
    WHERE mb.player_key = :player_key AND l.ends_at > :now
    """)

_LEAGUE_COLUMNS = "id, name, invite_code, owner_key, scope, clubs, term_kind, starts_at, ends_at, image_key, stake_text"

_INSERT_LEAGUE = text(f"""
    INSERT INTO hockey_leagues (name, owner_key, invite_code, scope, clubs, term_kind, starts_at, ends_at,
                                extended_from, image_key, stake_text)
    VALUES (:name, :owner_key, :invite_code, :scope, :clubs, :term_kind, :starts_at, :ends_at, :extended_from,
            :image_key, :stake_text)
    RETURNING {_LEAGUE_COLUMNS}
    """)

_ADD_MEMBER = text("""
    INSERT INTO hockey_league_members (league_id, player_key)
    VALUES (:league_id, :player_key)
    ON CONFLICT DO NOTHING
    """)

# Архивная лига (вышел последний участник, короны остались) по коду не находится: ни превью, ни вступления.
_LEAGUE_BY_CODE = text(f"""
    SELECT {_LEAGUE_COLUMNS} FROM hockey_leagues AS l WHERE l.invite_code = :code
      AND EXISTS (SELECT 1 FROM hockey_league_members AS m WHERE m.league_id = l.id)
    """)

_LEAGUE_BY_ID = text(f"""
    SELECT {_LEAGUE_COLUMNS} FROM hockey_leagues WHERE id = :league_id
    """)

_LEAGUE_BY_ID_LOCK = text(f"""
    SELECT {_LEAGUE_COLUMNS} FROM hockey_leagues WHERE id = :league_id FOR UPDATE
    """)

_IS_MEMBER = text("""
    SELECT 1 FROM hockey_league_members WHERE league_id = :league_id AND player_key = :player_key
    """)

_MEMBER_COUNT = text("SELECT COUNT(*) FROM hockey_league_members WHERE league_id = :league_id")

_REMOVE_MEMBER = text("""
    DELETE FROM hockey_league_members WHERE league_id = :league_id AND player_key = :player_key
    """)

_NEXT_OWNER = text("""
    SELECT player_key FROM hockey_league_members
    WHERE league_id = :league_id ORDER BY joined_at, player_key LIMIT 1
    """)

_SET_OWNER = text("UPDATE hockey_leagues SET owner_key = :owner_key, updated_at = now() WHERE id = :league_id")

_DELETE_LEAGUE = text("DELETE FROM hockey_leagues WHERE id = :league_id")

# Короны ссылаются на лигу с ON DELETE CASCADE: лигу с коронами удалять нельзя, она уходит в архив.
_HAS_CROWNS = text("SELECT EXISTS (SELECT 1 FROM hockey_crowns WHERE league_id = :league_id)")

_UPDATE_TEXTS = text("""
    UPDATE hockey_leagues SET name = :name, stake_text = :stake_text, updated_at = now() WHERE id = :league_id
    """)

_SET_IMAGE = text("UPDATE hockey_leagues SET image_key = :image_key, updated_at = now() WHERE id = :league_id")

# Лиги игрока. Закончившиеся без границы копились бы вечно, а на каждую считается таблица, поэтому по
# умолчанию — только идущие и недавно закончившиеся (ends_at > :ends_after), не больше :limit: сперва идущие,
# среди равных — позже кончающиеся. Выдаём по-прежнему в порядке вступления.
_MY_LEAGUES = text("""
    SELECT t.id, t.name, t.invite_code, t.is_owner, t.scope, t.clubs, t.term_kind, t.starts_at, t.ends_at,
           t.image_key, t.stake_text,
           (SELECT COUNT(*) FROM hockey_league_members x WHERE x.league_id = t.id)::int AS members
    FROM (
        SELECT l.id, l.name, l.invite_code, (l.owner_key = :player_key) AS is_owner,
               l.scope, l.clubs, l.term_kind, l.starts_at, l.ends_at, l.image_key, l.stake_text, me.joined_at
        FROM hockey_leagues AS l
        JOIN hockey_league_members AS me ON me.league_id = l.id AND me.player_key = :player_key
        WHERE (CAST(:ids AS bigint[]) IS NULL OR l.id = ANY(CAST(:ids AS bigint[])))
          AND (CAST(:ends_after AS timestamptz) IS NULL OR l.ends_at > CAST(:ends_after AS timestamptz))
          AND (CAST(:starts_by AS timestamptz) IS NULL OR l.starts_at <= CAST(:starts_by AS timestamptz))
        ORDER BY (l.ends_at > :now) DESC, l.ends_at DESC, l.id DESC
        LIMIT :limit
    ) AS t
    ORDER BY t.joined_at, t.id
    """)

_PREVIEW_NAMES = text("""
    SELECT pl.display_name FROM hockey_league_members AS mb
    JOIN hockey_players AS pl ON pl.player_key = mb.player_key
    WHERE mb.league_id = :league_id ORDER BY mb.joined_at, mb.player_key LIMIT :limit
    """)

# Кто из друзей (участников моих лиг) за какую сторону. Счёт друзей не раскрываем — только сторону.
_FRIENDS_PICKS = text("""
    SELECT DISTINCT p.match_id, p.side, p.player_key, pl.display_name
    FROM hockey_picks AS p
    JOIN hockey_players AS pl ON pl.player_key = p.player_key
    WHERE p.match_id = ANY(:match_ids)
      AND p.player_key <> :player_key
      AND p.player_key IN (
          SELECT f.player_key FROM hockey_league_members AS f
          WHERE f.league_id IN (SELECT league_id FROM hockey_league_members WHERE player_key = :player_key)
      )
    ORDER BY p.match_id, p.side, pl.display_name, p.player_key
    """)


async def _ensure_player(session: AsyncSession, player_key: int, display_name: str) -> None:
    name = (display_name or "").strip()[:40] or DEFAULT_PLAYER_NAME
    await session.execute(_PLAYER_UPSERT, {"player_key": player_key, "display_name": name})


def _league(record) -> League:
    data = dict(record._mapping)
    data["clubs"] = tuple(data.get("clubs") or ())
    return League(**data)


def _known_clubs() -> frozenset[str]:
    from src.application.extraliga import CLUBS
    from src.application.hockey_teams import TEAMS

    return frozenset(TEAMS) | {club.name for club in CLUBS.values()}


def _minsk_midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=MINSK_TZ).astimezone(timezone.utc)


def _as_instant(value: datetime | date) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=MINSK_TZ)
    return datetime(value.year, value.month, value.day, tzinfo=MINSK_TZ)


def build_terms(
    *,
    scope: str,
    clubs: list[str] | tuple[str, ...] | None = None,
    term: str = "season",
    now: datetime,
    month: str | None = None,
    starts_at: datetime | date | None = None,
    ends_at: datetime | date | None = None,
) -> Terms:
    """Проверить набор команд и срок, посчитать окно дат. ``InvalidTerms`` — с текстом для человека.

    - ``season`` — до конца текущего сезона; ``month`` — календарный месяц по Минску (текущий или ``2026-12``);
    - ``weeks4`` — четыре недели с сегодняшнего дня; ``playoff`` — март-май сезона или свои даты;
    - ``dates`` — свои даты: старт не раньше сегодня, конец позже старта и не дальше конца сезона.
    """
    now = _utc(now)
    if scope not in SCOPES:
        raise InvalidTerms("Выбери, какие матчи считаем")
    names = tuple(dict.fromkeys(c.strip() for c in (clubs or ()) if c and c.strip()))
    if scope == "clubs":
        if not names:
            raise InvalidTerms("Выбери хотя бы одну команду")
        if len(names) > MAX_CLUBS:
            raise InvalidTerms(f"Не больше {MAX_CLUBS} команд")
        unknown = sorted(set(names) - _known_clubs())
        if unknown:
            raise InvalidTerms(f"Нет такой команды: {unknown[0]}")
    else:
        names = ()
    if term not in TERM_KINDS:
        raise InvalidTerms("Выбери, сколько идёт лига")
    season = season_period(now)
    today = _minsk_midnight(now.astimezone(MINSK_TZ).date())
    if term == "season":
        start, end = season.since, season.until
    elif term == "month":
        if month:
            period = _parse_month(month)
        else:
            period = month_period(now.astimezone(MINSK_TZ).date())
        start, end = period.since, period.until
    elif term == "weeks4":
        start, end = today, today + timedelta(days=28)
    elif term in ("playoff", "dates") and any(
        v is not None and not MIN_YEAR <= v.year <= MAX_YEAR for v in (starts_at, ends_at)
    ):
        raise InvalidTerms("Такие даты не подходят")
    elif term == "playoff":
        year = season.until.astimezone(MINSK_TZ).year
        start = _as_instant(starts_at) if starts_at else datetime(year, *PLAYOFF_FROM, tzinfo=MINSK_TZ)
        end = _as_instant(ends_at) if ends_at else datetime(year, *PLAYOFF_TO, tzinfo=MINSK_TZ)
        start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    else:
        if starts_at is None or ends_at is None:
            raise InvalidTerms("Укажи даты начала и конца")
        start, end = _as_instant(starts_at).astimezone(timezone.utc), _as_instant(ends_at).astimezone(timezone.utc)
        if start < today:
            raise InvalidTerms("Лига не может начаться в прошлом")
    if end <= start:
        raise InvalidTerms("Конец раньше начала")
    if end <= now:
        raise InvalidTerms("Эти даты уже прошли")
    if end > season.until and term in ("dates", "playoff"):
        raise InvalidTerms("Лига длится не дальше конца сезона")
    return Terms(scope=scope, clubs=names, term_kind=term, starts_at=start, ends_at=end)


# Сроки, где корона идёт каждый месяц: ``hockey_races._close_leagues`` награждает по месяцам только сезонную лигу;
# у остальных одна корона в конце срока.
MONTHLY_CROWN_TERMS = frozenset({"season"})


def term_options(*, now: datetime) -> dict:
    """Окна всех сроков для экрана «Новая лига»: даты и правило корон берём у сервера, не у клиента.

    Срок, который сейчас создать нельзя (плей-офф уже прошёл), в список не попадает.
    """
    now = _utc(now)
    items = []
    for term in TERM_KINDS:
        if term == "dates":
            continue
        try:
            terms = build_terms(scope="all", term=term, now=now)
        except InvalidTerms:
            continue
        items.append(
            {
                "term": term,
                "starts_at": terms.starts_at.isoformat(),
                "ends_at": terms.ends_at.isoformat(),
                "monthly_crowns": term in MONTHLY_CROWN_TERMS,
            }
        )
    return {"items": items, "season_ends_at": season_period(now).until.isoformat(), "max_clubs": MAX_CLUBS}


def _parse_month(raw: str) -> Period:
    try:
        year, mon = (int(x) for x in raw.split("-"))
        if not MIN_YEAR <= year <= MAX_YEAR:
            raise ValueError(raw)
        return month_period(date(year, mon, 1))
    except (ValueError, TypeError):
        raise InvalidTerms("Месяц в формате 2026-12") from None


DEFAULT_SCOPE = "dinamo"

_COUNT_MATCHES = text("""
    SELECT COUNT(*)::int FROM game_matches AS m
    WHERE m.status <> 'cancelled' AND m.starts_at >= GREATEST(CAST(:since AS timestamptz), CAST(:now AS timestamptz)) AND m.starts_at < :until
      AND (CAST(:clubs AS text[]) IS NULL
           OR m.home_team = ANY(CAST(:clubs AS text[])) OR m.away_team = ANY(CAST(:clubs AS text[])))
      AND (CAST(:mleague AS text) IS NULL OR m.league = CAST(:mleague AS text))
    """)


async def matches_in_terms(session: AsyncSession, terms: Terms, *, now: datetime) -> int:
    """Сколько матчей ещё впереди в сроке лиги (для предупреждения «матчей мало»)."""
    scope = league_scope(terms.scope, terms.clubs)
    params = {"since": terms.starts_at, "until": terms.ends_at, "now": _utc(now), **scope.params}
    return int((await session.execute(_COUNT_MATCHES, params)).scalar_one())


async def _check_league_quota(session: AsyncSession, player_key: int, *, now: datetime | None = None) -> None:
    count = (
        await session.execute(
            _COUNT_MY_LEAGUES, {"player_key": player_key, "now": _utc(now or datetime.now(timezone.utc))}
        )
    ).scalar_one()
    if count >= MAX_LEAGUES_PER_PLAYER:
        raise TooManyLeagues(player_key)


async def _insert_league(
    session: AsyncSession,
    *,
    owner_key: int,
    name: str,
    terms: Terms,
    extended_from: int | None = None,
    image_key: str | None = None,
    stake_text: str | None = None,
) -> League:
    for _ in range(5):
        try:
            async with session.begin_nested():
                row = (
                    await session.execute(
                        _INSERT_LEAGUE,
                        {
                            "name": name,
                            "owner_key": owner_key,
                            "invite_code": new_invite_code(),
                            "scope": terms.scope,
                            "clubs": list(terms.clubs),
                            "term_kind": terms.term_kind,
                            "starts_at": terms.starts_at,
                            "ends_at": terms.ends_at,
                            "extended_from": extended_from,
                            "image_key": image_key,
                            "stake_text": stake_text,
                        },
                    )
                ).one()
        except IntegrityError:
            continue
        return _league(row)
    raise RuntimeError("не удалось выдать код приглашения")


async def create_league(
    session: AsyncSession,
    *,
    owner_key: int,
    owner_name: str,
    name: str,
    terms: Terms | None = None,
    now: datetime | None = None,
    stake_text: str | None = None,
) -> League:
    """Новая лига; создатель — первый участник. Без ``terms`` — «Динамо-Минск, до конца сезона».

    ``stake_text`` — «на что играем» (необязательно); картинку владелец добавляет отдельным запросом."""
    now = _utc(now or datetime.now(timezone.utc))
    name = clean_name(name)
    stake = clean_stake(stake_text)
    terms = terms or build_terms(scope=DEFAULT_SCOPE, term="season", now=now)
    await _ensure_player(session, owner_key, owner_name)
    await _check_league_quota(session, owner_key, now=now)
    league = await _insert_league(session, owner_key=owner_key, name=name, terms=terms, stake_text=stake)
    await session.execute(_ADD_MEMBER, {"league_id": league.id, "player_key": owner_key})
    return league


_EXTENSION_OF = text(f"SELECT {_LEAGUE_COLUMNS} FROM hockey_leagues WHERE extended_from = :league_id")
_MEMBERS_OF = text("SELECT player_key FROM hockey_league_members WHERE league_id = :league_id ORDER BY joined_at")
_ADD_MEMBER_AT = text("""
    INSERT INTO hockey_league_members (league_id, player_key, joined_at)
    VALUES (:league_id, :player_key, :joined_at) ON CONFLICT DO NOTHING
    """)


_QUEUE_EXTENDED_NOTICE = text("""
    INSERT INTO hockey_league_notices (league_id, player_key, kind) VALUES (:league_id, :player_key, 'extended')
    ON CONFLICT DO NOTHING
    """)


def _next_terms(league: League, *, now: datetime) -> Terms:
    """Тот же набор команд и тот же вид срока — на следующий период после закончившегося."""
    start, end = _utc(league.starts_at), _utc(league.ends_at)  # type: ignore[arg-type]
    after = max(end, _utc(now))
    if league.term_kind == "season":
        return build_terms(scope=league.scope, clubs=league.clubs, term="season", now=after, starts_at=None)
    if league.term_kind == "month":
        nxt = after.astimezone(MINSK_TZ).date()
        return build_terms(
            scope=league.scope,
            clubs=league.clubs,
            term="month",
            now=now,
            month=f"{nxt.year}-{nxt.month:02d}",
        )
    if league.term_kind == "weeks4":
        return build_terms(scope=league.scope, clubs=league.clubs, term="weeks4", now=now)
    length = end - start
    base = _minsk_midnight(after.astimezone(MINSK_TZ).date())
    return build_terms(
        scope=league.scope,
        clubs=league.clubs,
        term="dates",
        now=now,
        starts_at=base,
        ends_at=base + length,
    )


async def extend_league(
    session: AsyncSession,
    *,
    league_id: int,
    player_key: int,
    now: datetime,
    terms: Terms | None = None,
) -> tuple[League, bool]:
    """«Продлить»: новая лига с теми же людьми. Только владелец; у лиги одно продолжение — повтор вернёт его.

    Возвращает (лига, создана_ли_сейчас). Старая лига остаётся (короны за ней), участники новой —
    те, у кого не исчерпана квота лиг. Входят сразу; выйти можно как из любой лиги.
    """
    league = await _member_league(session, league_id, player_key)
    if league.owner_key != player_key:
        raise PermissionError(league_id)
    existing = (await session.execute(_EXTENSION_OF, {"league_id": league_id})).one_or_none()
    if existing is not None:
        if not (await session.execute(_IS_MEMBER, {"league_id": existing.id, "player_key": player_key})).first():
            raise AlreadyExtended(league_id)
        return _league(existing), False
    # Сам владелец обязан попасть в продолжение: без места в квоте лигу не создаём (иначе она осиротеет).
    await _check_league_quota(session, player_key, now=now)
    terms = terms or _next_terms(league, now=now)
    # Лицо лиги переходит в продолжение: то же название, та же картинка (файл общий, см. ``release_image``), та же строка.
    fresh = await _insert_league(
        session,
        owner_key=player_key,
        name=league.name,
        terms=terms,
        extended_from=league.id,
        image_key=league.image_key,
        stake_text=league.stake_text,
    )
    joined = max(_utc(now), terms.starts_at) if terms.starts_at > _utc(now) else _utc(now)
    for key in (await session.execute(_MEMBERS_OF, {"league_id": league_id})).scalars().all():
        try:
            await _check_league_quota(session, key, now=now)
        except TooManyLeagues:
            continue
        await session.execute(_ADD_MEMBER_AT, {"league_id": fresh.id, "player_key": key, "joined_at": joined})
        if key != player_key:
            # Каждому участнику, кроме нажавшего «Продлить»: «лига продлена, выйти в один тап» (бот, TASK-334 S6).
            await session.execute(_QUEUE_EXTENDED_NOTICE, {"league_id": fresh.id, "player_key": key})
    return fresh, True


async def league_by_code(session: AsyncSession, code: str) -> League | None:
    record = (await session.execute(_LEAGUE_BY_CODE, {"code": normalize_code(code)})).one_or_none()
    return None if record is None else _league(record)


async def join_league(session: AsyncSession, *, player_key: int, display_name: str, code: str) -> tuple[League, bool]:
    """Вступить по коду. Возвращает (лига, добавлен_ли_сейчас): повторный переход по ссылке ничего не меняет."""
    found = await league_by_code(session, code)
    if found is None:
        raise LookupError(code)
    # Лочим строку лиги: двое одновременно не превысят лимит участников.
    record = (await session.execute(_LEAGUE_BY_ID_LOCK, {"league_id": found.id})).one_or_none()
    if record is None:  # лигу удалили между поиском по коду и блокировкой
        raise LookupError(code)
    league = _league(record)
    if not (await session.execute(_MEMBER_COUNT, {"league_id": league.id})).scalar_one():
        raise LookupError(code)  # лига ушла в архив между поиском и блокировкой: не воскрешаем
    await _ensure_player(session, player_key, display_name)
    if (await session.execute(_IS_MEMBER, {"league_id": league.id, "player_key": player_key})).first():
        return league, False
    if (await session.execute(_MEMBER_COUNT, {"league_id": league.id})).scalar_one() >= MAX_MEMBERS:
        raise LeagueFull(league.id)
    await _check_league_quota(session, player_key)
    await session.execute(_ADD_MEMBER, {"league_id": league.id, "player_key": player_key})
    return league, True


async def join_by_code(session: AsyncSession, *, player_key: int, display_name: str, code: str) -> League:
    league, _ = await join_league(session, player_key=player_key, display_name=display_name, code=code)
    return league


async def _member_league(session: AsyncSession, league_id: int, player_key: int, *, lock: bool = True) -> League:
    stmt = _LEAGUE_BY_ID_LOCK if lock else _LEAGUE_BY_ID
    record = (await session.execute(stmt, {"league_id": league_id})).one_or_none()
    if record is None:
        raise LookupError(league_id)
    if not (await session.execute(_IS_MEMBER, {"league_id": league_id, "player_key": player_key})).first():
        raise PermissionError(league_id)
    return _league(record)


async def member_league(session: AsyncSession, *, league_id: int, player_key: int) -> League:
    """Лига для её участника: ``LookupError`` — нет такой, ``PermissionError`` — не участник."""
    return await _member_league(session, league_id, player_key, lock=False)


async def leave_league(session: AsyncSession, *, league_id: int, player_key: int) -> str:
    """Выйти. Ушёл владелец — лига переходит к самому раннему участнику; ушёл последний — лиги нет
    (``deleted``), а если у неё есть короны — она уходит в архив без участников (``archived``)."""
    league = await _member_league(session, league_id, player_key)
    await session.execute(_REMOVE_MEMBER, {"league_id": league_id, "player_key": player_key})
    next_owner = (await session.execute(_NEXT_OWNER, {"league_id": league_id})).scalar_one_or_none()
    if next_owner is None:
        if (await session.execute(_HAS_CROWNS, {"league_id": league_id})).scalar_one():
            # Архив: строка лиги остаётся без участников (владелец прежний), короны и их названия живы.
            return "archived"
        await session.execute(_DELETE_LEAGUE, {"league_id": league_id})
        return "deleted"
    if league.owner_key == player_key:
        await session.execute(_SET_OWNER, {"league_id": league_id, "owner_key": next_owner})
        return "owner_moved"
    return "left"


_UNSET: object = object()


async def update_league(
    session: AsyncSession,
    *,
    league_id: int,
    player_key: int,
    name: str | object = _UNSET,
    stake_text: str | None | object = _UNSET,
) -> League:
    """Поменять название и/или строку «на что играем» — только владелец. Не переданное остаётся как было;
    пустая строка «на что играем» убирает её."""
    league = await _member_league(session, league_id, player_key)
    if league.owner_key != player_key:
        raise PermissionError(league_id)
    if name is _UNSET and stake_text is _UNSET:
        raise ValueError("Нечего менять")
    new_name = league.name if name is _UNSET else clean_name(name)  # type: ignore[arg-type]
    new_stake = league.stake_text if stake_text is _UNSET else clean_stake(stake_text)  # type: ignore[arg-type]
    await session.execute(_UPDATE_TEXTS, {"league_id": league_id, "name": new_name, "stake_text": new_stake})
    return replace(league, name=new_name, stake_text=new_stake)


async def rename_league(session: AsyncSession, *, league_id: int, player_key: int, name: str) -> League:
    return await update_league(session, league_id=league_id, player_key=player_key, name=name)


async def owned_league(session: AsyncSession, *, league_id: int, player_key: int) -> League:
    """Лига, которую игрок вправе менять: ``LookupError`` — нет такой, ``PermissionError`` — не участник или не владелец."""
    league = await _member_league(session, league_id, player_key, lock=False)
    if league.owner_key != player_key:
        raise PermissionError(league_id)
    return league


async def set_league_image(
    session: AsyncSession, *, league_id: int, player_key: int, image_key: str | None
) -> tuple[League, str | None]:
    """Поставить картинку лиги (``None`` — убрать). Только владелец. Возвращает (лига, прежний ключ):
    файл прежней картинки убирает вызывающий после commit (``release_image``)."""
    league = await _member_league(session, league_id, player_key)
    if league.owner_key != player_key:
        raise PermissionError(league_id)
    await session.execute(_SET_IMAGE, {"league_id": league_id, "image_key": image_key})
    return replace(league, image_key=image_key), league.image_key


_IMAGE_KEY_OF = text("SELECT image_key FROM hockey_leagues WHERE id = :league_id")


async def league_image_key(session: AsyncSession, league_id: int) -> str | None:
    return (await session.execute(_IMAGE_KEY_OF, {"league_id": league_id})).scalar_one_or_none()


async def league_table(
    session: AsyncSession, *, league_id: int, player_key: int, now: datetime, period: Period | None = None
) -> list[LeagueRow]:
    """Таблица лиги — только для участника: весь срок лиги или (``period``) его часть, например месяц."""
    league = await _member_league(session, league_id, player_key, lock=False)
    return await league_table_rows(session, league, period=period)


async def league_table_rows(session: AsyncSession, league: League, *, period: Period | None = None) -> list[LeagueRow]:
    since, until = _utc(league.starts_at), _utc(league.ends_at)  # type: ignore[arg-type]
    if period is not None:
        since, until = max(since, period.since), min(until, period.until)
    rows = await league_rows(session, league_id=league.id, scope=league.match_scope, since=since, until=until)
    return [LeagueRow(**r.__dict__) for r in rows]


# ---------- звания в таблице лиги (владелец 2026-10-20) ----------
# Одно на человека: шутим над ходом, а не над человеком. Всё — из готовых ходов.
# Если подходит несколько — берём самое яркое по этому порядку.
TITLE_ORDER = ("cap", "scarf", "vanga", "streak", "optimist")
VANGA_MIN = 2
STREAK_MIN = 3
OPTIMIST_MARGIN = 2
OPTIMIST_MIN_PICKS = 2

# Матчи — те же, что считает таблица лиги (её набор команд), а не только Динамо.
_TITLE_PICKS = text(f"""
    SELECT p.player_key, m.id AS match_id, m.starts_at, m.status, m.home_team, m.away_team, p.side, p.points,
           p.home_score AS pick_home, p.away_score AS pick_away
    FROM hockey_picks AS p
    JOIN game_matches AS m ON m.id = p.match_id
    WHERE p.player_key IN (SELECT player_key FROM hockey_league_members WHERE league_id = :league_id)
      AND m.starts_at >= :since
      {SCOPE_SQL}
    ORDER BY m.starts_at, m.id
    """)


def _dinamo_side(home_team: str) -> str:
    from src.application.hockey_matches import DINAMO

    return "home" if home_team == DINAMO else "away"


def _plural(n: int, one: str, few: str, many: str) -> str:
    m10, m100 = n % 10, n % 100
    if m10 == 1 and m100 != 11:
        return one
    if 2 <= m10 <= 4 and not 12 <= m100 <= 14:
        return few
    return many


def pick_titles(
    picks: list[dict], *, fans: Mapping[int, str] | None = None, caps: Collection[int] = ()
) -> dict[int, dict[str, str]]:
    """Звания участников лиги по их ходам за сезон (чистая функция, ходы — по времени матча).

    ``fans`` — «своя» команда игрока (как у бота: «болею за», иначе клуб, за который чаще всего ходил).
    ``caps`` — кто сейчас в кепке дня (``hockey_league_evening.current_cap``).

    - cap «Кепка дня» — хуже всех угадывал в последний сыгранный игровой день лиги (TASK-431, правило —
      в ``hockey_league_evening``); носится до следующего сыгранного дня;
    - scarf «В чужом шарфе» — ход против своей команды на её ближайший матч, на который есть ход;
      нет своей команды — нет шарфа;
    - vanga «Ванга» — единственный лидер лиги по точным счетам, от VANGA_MIN точных;
    - streak «Чуйка» — победитель угадан STREAK_MIN+ сыгранных матчей подряд;
    - optimist «Вечный оптимист» — в среднем ставит Динамо +OPTIMIST_MARGIN и больше (только матчи Динамо).
    """
    found: dict[int, dict[str, dict[str, str]]] = {}

    def give(player: int, key: str, label: str, detail: str = "") -> None:
        found.setdefault(player, {})[key] = {"id": key, "label": label, "detail": detail}

    for player in caps:
        give(player, "cap", "Кепка дня")

    scored = [p for p in picks if p["status"] == "final" and p["points"] is not None]

    nearest: dict[int, dict] = {}
    for p in picks:
        club = (fans or {}).get(p["player_key"])
        if p["status"] == "scheduled" and club in (p["home_team"], p["away_team"]):
            nearest.setdefault(p["player_key"], p)
    for player, p in nearest.items():
        if p["side"] and (p["home_team"] if p["side"] == "home" else p["away_team"]) != fans[player]:
            give(player, "scarf", "В чужом шарфе")

    exact: dict[int, int] = {}
    for p in scored:
        if p["points"] == POINTS_EXACT:
            exact[p["player_key"]] = exact.get(p["player_key"], 0) + 1
    if exact:
        best = max(exact.values())
        leaders = [k for k, v in exact.items() if v == best]
        if len(leaders) == 1 and best >= VANGA_MIN:
            give(leaders[0], "vanga", "Ванга", f"{best} {_plural(best, 'точный', 'точных', 'точных')}")

    by_player: dict[int, list[dict]] = {}
    for p in scored:
        by_player.setdefault(p["player_key"], []).append(p)
    for player, rows in by_player.items():
        run = 0
        for p in reversed(rows):
            if p["points"] < POINTS_WINNER:
                break
            run += 1
        if run >= STREAK_MIN:
            give(player, "streak", "Чуйка", f"{run} подряд")

    margins: dict[int, list[int]] = {}
    for p in picks:
        if p.get("pick_home") is None or p.get("pick_away") is None or DINAMO not in (p["home_team"], p["away_team"]):
            continue
        dinamo_home = _dinamo_side(p["home_team"]) == "home"
        ours, theirs = (p["pick_home"], p["pick_away"]) if dinamo_home else (p["pick_away"], p["pick_home"])
        margins.setdefault(p["player_key"], []).append(ours - theirs)
    for player, values in margins.items():
        if len(values) >= OPTIMIST_MIN_PICKS and sum(values) / len(values) >= OPTIMIST_MARGIN:
            give(player, "optimist", "Вечный оптимист")

    return {player: next(titles[k] for k in TITLE_ORDER if k in titles) for player, titles in found.items()}


async def league_titles(session: AsyncSession, *, league_id: int, now: datetime) -> dict[int, dict[str, str]]:
    from src.application.hockey_league_evening import current_cap

    now = _utc(now)
    league = _league((await session.execute(_LEAGUE_BY_ID, {"league_id": league_id})).one())
    params = {"league_id": league_id, "since": league.starts_at, **league.match_scope.params}
    picks = [dict(r._mapping) for r in (await session.execute(_TITLE_PICKS, params)).all()]
    if not picks:
        return {}
    caps = await current_cap(session, league, now=now)
    from src.application.hockey_notices import _FAN_CLUB, FAN_WINDOW

    fans_sql = text(f"""
        SELECT pl.player_key, {_FAN_CLUB} AS club
        FROM hockey_league_members AS lm
        JOIN hockey_players AS pl ON pl.player_key = lm.player_key
        LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = pl.player_key
        WHERE lm.league_id = :league_id
        """)
    params = {"league_id": league_id, "now": now, "fan_since": now - FAN_WINDOW}
    fans = {r.player_key: r.club for r in (await session.execute(fans_sql, params)).all() if r.club}
    return pick_titles(picks, fans=fans, caps=caps)


_RECENT = object()


async def player_leagues(
    session: AsyncSession,
    *,
    player_key: int,
    now: datetime,
    league_ids: list[int] | None = None,
    ends_after: datetime | None | object = _RECENT,
    starts_by: datetime | None = None,
    limit: int = MY_LEAGUES_LIMIT,
    with_rank: bool = True,
) -> list[LeagueSummary]:
    """Лиги игрока в порядке вступления; место и очки — по таблице лиги.

    По умолчанию — идущие и закончившиеся не раньше ``RECENTLY_ENDED_DAYS`` назад, не больше ``limit``.
    ``league_ids`` — только эти лиги (границы срока тогда не нужны: ``ends_after=None``); ``ends_after`` — лиги,
    кончающиеся позже этого момента; ``starts_by`` — начавшиеся не позже. Таблица считается на каждую вернувшуюся
    лигу, поэтому берите узкий срез; ``with_rank=False`` таблиц не считает (``my_rank``/``my_points`` — ``None``).
    """
    now_utc = _utc(now)
    if ends_after is _RECENT:
        ends_after = now_utc - timedelta(days=RECENTLY_ENDED_DAYS)
    params = {
        "player_key": player_key,
        "now": now_utc,
        "ids": None if league_ids is None else list(league_ids),
        "ends_after": None if ends_after is None else _utc(ends_after),  # type: ignore[arg-type]
        "starts_by": None if starts_by is None else _utc(starts_by),
        "limit": limit,
    }
    out: list[LeagueSummary] = []
    for record in (await session.execute(_MY_LEAGUES, params)).all():
        league = League(
            id=record.id,
            name=record.name,
            invite_code=record.invite_code,
            owner_key=0,
            scope=record.scope,
            clubs=tuple(record.clubs or ()),
            term_kind=record.term_kind,
            starts_at=record.starts_at,
            ends_at=record.ends_at,
            image_key=record.image_key,
            stake_text=record.stake_text,
        )
        rank = points = None
        if with_rank:
            rows = await league_table_rows(session, league)
            mine = next(r for r in rows if r.player_key == player_key)
            rank, points = mine.rank, mine.points
        out.append(
            LeagueSummary(
                id=record.id,
                name=record.name,
                invite_code=record.invite_code,
                is_owner=bool(record.is_owner),
                members=record.members,
                my_rank=rank,  # type: ignore[arg-type]
                my_points=points,  # type: ignore[arg-type]
                scope=record.scope,
                clubs=league.clubs,
                term_kind=record.term_kind,
                starts_at=record.starts_at,
                ends_at=record.ends_at,
                active=_utc(record.ends_at) > now_utc,
                image_key=record.image_key,
                stake_text=record.stake_text,
            )
        )
    return out


async def league_preview(session: AsyncSession, code: str, *, names: int = 6) -> dict | None:
    """Для приглашения: название, сколько людей и первые имена, лицо лиги. Без таблицы и без ключей игроков."""
    league = await league_by_code(session, code)
    if league is None:
        return None
    members = (await session.execute(_MEMBER_COUNT, {"league_id": league.id})).scalar_one()
    shown = (await session.execute(_PREVIEW_NAMES, {"league_id": league.id, "limit": names})).scalars().all()
    return {
        "name": league.name,
        "invite_code": league.invite_code,
        "members": int(members),
        "names": list(shown),
        "image_key": league.image_key,
        "stake_text": league.stake_text,
    }


async def friends_picks(
    session: AsyncSession, *, player_key: int, match_ids: list[int]
) -> dict[int, dict[str, list[str]]]:
    """Друзья на половинках карточки матча: имена за каждую сторону, без их счёта и без меня."""
    out: dict[int, dict[str, list[str]]] = {mid: {"home": [], "away": []} for mid in match_ids}
    if not match_ids:
        return out
    params = {"player_key": player_key, "match_ids": list(match_ids)}
    for r in (await session.execute(_FRIENDS_PICKS, params)).all():
        out[r.match_id][r.side].append(r.display_name)
    return out


# Счета друзей открываются со стартом матча (TASK-335): до начала — только сторона (friends_picks).
_FRIENDS_MOVES = text("""
    SELECT DISTINCT p.match_id, p.player_key, pl.display_name, p.side, p.home_score, p.away_score,
           p.doubled, p.points
    FROM hockey_picks AS p
    JOIN hockey_players AS pl ON pl.player_key = p.player_key
    JOIN game_matches AS m ON m.id = p.match_id
    WHERE p.match_id = ANY(:match_ids)
      AND p.player_key <> :player_key
      AND (m.status <> 'scheduled' OR m.starts_at <= :now)
      AND p.player_key IN (
          SELECT f.player_key FROM hockey_league_members AS f
          WHERE f.league_id IN (SELECT league_id FROM hockey_league_members WHERE player_key = :player_key)
      )
    ORDER BY p.match_id, pl.display_name, p.player_key
    """)


async def friends_moves(
    session: AsyncSession, *, player_key: int, match_ids: list[int], now: datetime
) -> dict[int, list[dict]]:
    """Ходы друзей на начавшиеся матчи: сторона, счёт, ×2 и очки (уже с ×2), когда посчитаны."""
    out: dict[int, list[dict]] = {mid: [] for mid in match_ids}
    if not match_ids:
        return out
    params = {"player_key": player_key, "match_ids": list(match_ids), "now": _utc(now)}
    for r in (await session.execute(_FRIENDS_MOVES, params)).all():
        out[r.match_id].append(
            {
                "display_name": r.display_name,
                "side": r.side,
                "home_score": r.home_score,
                "away_score": r.away_score,
                "doubled": bool(r.doubled),
                "points": None if r.points is None else r.points * (2 if r.doubled else 1),
            }
        )
    return out


__all__ = [
    "InvalidTerms",
    "MONTHLY_CROWN_TERMS",
    "term_options",
    "FEW_MATCHES",
    "Terms",
    "build_terms",
    "extend_league",
    "league_table_rows",
    "matches_in_terms",
    "League",
    "LeagueFull",
    "LeagueRow",
    "LeagueSummary",
    "MAX_LEAGUES_PER_PLAYER",
    "MAX_MEMBERS",
    "TooManyLeagues",
    "STAKE_MAX",
    "clean_name",
    "clean_stake",
    "create_league",
    "league_image_key",
    "owned_league",
    "set_league_image",
    "update_league",
    "friends_moves",
    "friends_picks",
    "AlreadyExtended",
    "join_by_code",
    "join_league",
    "league_by_code",
    "league_preview",
    "league_table",
    "leave_league",
    "member_league",
    "new_invite_code",
    "normalize_code",
    "player_leagues",
    "rename_league",
]
