"""Матчи как события сайта (TASK-347): лента города, список «Хоккей», страница матча, .ics.

Данные те же, что у Mini App: таблица ``hockey_matches``, клубы Экстралиги по ``EXTRALIGA_CLUBS`` и
матчи Динамо (дома и в гостях) по ``HOCKEY_MATCHES_ENABLED``. Всё за флагом ``SITE_MATCHES_ENABLED``.
Здесь нет игрока, поэтому нет и его хода: сайт показывает матч, а ход и напоминание живут в Telegram.

Матч виден на сайте, только если обе команды известны (клубы Экстралиги, Динамо и соперники КХЛ из
``hockey_teams``) и его арена нашлась в нашем каталоге. Исключение — выезд Динамо: арены в каталоге у него
нет (чужую, минскую, не подставляем), страница честно ведёт в протокол вместо «Как добраться».

Две разные идеи, чтобы не путать: «матч в городе» (``in_city``) — он физически проходит там, это блок города
и секция «В Минске»; «матчи клуба» (фильтр ``club``) — все игры команды, дома и в гостях.
Отменённый матч и матч, пропавший из календаря две синхронизации подряд, скрыт из лент, списка и sitemap;
его страница остаётся с честной подписью и ``noindex``.

Единственный предикат видимости — ``_SCOPE`` + ``visible``: им пользуются лента, список, страница,
.ics, sitemap и колокольчик, поэтому клуб вне ``EXTRALIGA_CLUBS`` не протекает ни в один из них.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.extraliga import CLUBS, LEAGUE_EXTRALIGA, enabled_clubs, match_page_url
from src.application.hockey_matches import DINAMO, STATUS_CANCELLED, STATUS_FINAL
from src.application.hockey_teams import TEAMS, slug_for, team_card
from src.ingestion.hockey_sources import HCDINAMO_BASE, MINSK_TZ
from src.shared.config import Settings
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params

SITE_PATH = "/hockey"
MATCH_PREFIX = "/m"
LEAGUE_KHL = "khl"
# Название лиги — наше, не из источника: у hockey.by оно может нести имя титульного спонсора.
LEAGUE_LABELS = {LEAGUE_KHL: "КХЛ", LEAGUE_EXTRALIGA: "Экстралига"}
DINAMO_ARENA = "Минск-Арена"
DINAMO_CITY = "Минск"

# Идёт: от старта до трёх с половиной часов (овертайм, буллиты, задержка старта). Дальше ждём итог,
# через 12 часов без итога — «итог уточняем».
LIVE_WINDOW = timedelta(hours=3, minutes=30)
WAIT_WINDOW = timedelta(hours=12)
# Только что сыгранный матч ещё держится в ленте: счёт виден сразу.
BEHIND = timedelta(hours=3)
FEED_AHEAD = timedelta(days=7)
# Город без матчей на неделе: ближайший в будущем ищем в пределах сезона.
NEXT_IN_CITY_AHEAD = timedelta(days=200)
LIST_AHEAD = timedelta(days=30)
SITEMAP_AHEAD = timedelta(days=45)
SITEMAP_BACK = timedelta(days=30)
MISSED_HIDE = 2
CITY_LIMIT = 6
OTHERS_LIMIT = 3
# Сеанс, который идёт или начинается вместе с матчем (с этого момента до конца дня), опровергает «катания нет».
ICE_CLASH_BEFORE = timedelta(hours=2)
# Массовое катание «перед матчем» должно кончиться не позже чем за час до игры.
ICE_BEFORE_GAP = timedelta(hours=1)

PHASE_BEFORE = "before"
PHASE_LIVE = "live"
PHASE_AFTER = "after"
PHASE_WAIT = "wait"
PHASE_REVIEW = "review"

WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
WEEKDAYS_FULL = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
WEEKDAYS_UPPER = ("ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА", "ВОСКРЕСЕНЬЕ")
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
_CLUB_BY_NAME = {club.name: club for club in CLUBS.values()}

_COLUMNS = """
    id, source, source_match_id, league, home_team, away_team, starts_at, status, missed_runs,
    previous_starts_at, updated_at, finalized_at,
    home_score, away_score, decided_in, arena, city, tickets_url, details
"""
# Клубы вне списка и неизвестные команды сюда не попадают. Статус и пропажу из календаря решает ``hidden``.
_SCOPE = """
    home_team = ANY(:known) AND away_team = ANY(:known)
    AND ((league = 'extraliga' AND (home_team = ANY(:clubs) OR away_team = ANY(:clubs)))
         OR (league = 'khl' AND :dinamo AND (home_team = :dinamo_name OR away_team = :dinamo_name)))
"""
_RANGE = text(f"""
    SELECT {_COLUMNS} FROM hockey_matches
    WHERE {_SCOPE} AND status <> 'cancelled' AND missed_runs < :missed
      AND starts_at >= :since AND starts_at < :until
    ORDER BY starts_at, id
    """)
_ONE = text(f"SELECT {_COLUMNS} FROM hockey_matches WHERE id = :id AND {_SCOPE}")
_REGIONS = text("SELECT name, region FROM cities WHERE region IS NOT NULL AND name = ANY(:names)")
_NEXT_HOME = text("""
    SELECT id, away_team, starts_at FROM hockey_matches
    WHERE home_team = :home AND status = 'scheduled' AND missed_runs = 0 AND league = :league
      AND starts_at > :after AND id <> :id
    ORDER BY starts_at, id LIMIT 1
    """)
_PICKS = text("""
    SELECT COUNT(*) AS total,
           COUNT(*) FILTER (WHERE side = 'home') AS home,
           COUNT(*) FILTER (WHERE points IS NOT NULL AND points > 0) AS right_
    FROM hockey_picks WHERE match_id = :id
    """)
_ARENAS = text(f"""
    SELECT a.id, a.name, a.address, a.latitude, a.longitude, c.name AS city_name, p.slug
    FROM arenas a
    JOIN cities c ON c.id = a.city_id
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    WHERE {PUBLIC_ARENA_VISIBLE_SQL} AND COALESCE(a.venue_type, 'ice') IN ('ice', 'outdoor')
    ORDER BY a.id
    """)
# Массовое катание арены в день матча: что было до игры.
_ICE_BEFORE = text("""
    SELECT starts_at_local, ends_at_local, price_adult_minor, price_minor, currency_code
    FROM ice_sessions
    WHERE arena_id = :aid AND status = 'active' AND kind = 'public_skate'
      AND local_date = :day AND ends_at_utc <= :before
      AND (valid_until IS NULL OR valid_until >= :now)
    ORDER BY ends_at_utc DESC, id DESC
    LIMIT 1
    """)
_ICE_DAY = text("""
    SELECT starts_at_utc FROM ice_sessions
    WHERE arena_id = :aid AND status = 'active' AND kind = 'public_skate'
      AND local_date = :day AND (valid_until IS NULL OR valid_until >= :now)
    """)


def _norm(value: str | None) -> str:
    return (value or "").strip().lower().replace("ё", "е")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def local(value: datetime) -> datetime:
    """Время матча по Минску: клубы Экстралиги и Динамо играют по одному часовому поясу."""
    return _utc(value).astimezone(MINSK_TZ)


# ── Видимость ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Scope:
    clubs: list[str]
    dinamo: bool

    @property
    def empty(self) -> bool:
        return not self.clubs and not self.dinamo


def site_enabled(settings: Settings | None = None) -> bool:
    return bool((settings or Settings()).site_matches_enabled)  # type: ignore[call-arg]


def scope_of(settings: Settings | None = None) -> Scope:
    cfg = settings or Settings()  # type: ignore[call-arg]
    if not cfg.site_matches_enabled:
        return Scope(clubs=[], dinamo=False)
    clubs = sorted(enabled_clubs(cfg.extraliga_clubs)) if cfg.extraliga_enabled else []
    return Scope(clubs=clubs, dinamo=bool(cfg.hockey_matches_enabled))


def _params(scope: Scope) -> dict[str, Any]:
    return {
        "clubs": scope.clubs,
        "dinamo": scope.dinamo,
        "dinamo_name": DINAMO,
        "known": sorted(TEAMS),
        "missed": MISSED_HIDE,
    }


def in_scope(row: Any, scope: Scope) -> bool:
    """Тот же предикат, что ``_SCOPE``, для строки, уже выбранной из базы (колокольчик). Менять парой с ``_SCOPE``."""
    if row.home_team not in TEAMS or row.away_team not in TEAMS:
        return False
    if row.league == LEAGUE_EXTRALIGA:
        return row.home_team in scope.clubs or row.away_team in scope.clubs
    return bool(row.league == LEAGUE_KHL and scope.dinamo and DINAMO in (row.home_team, row.away_team))


def hidden(row: Any) -> bool:
    """Отменён или пропал из календаря: из лент скрыт, страница остаётся."""
    return row.status == STATUS_CANCELLED or int(getattr(row, "missed_runs", 0) or 0) >= MISSED_HIDE


# ── Арены каталога ───────────────────────────────────────────────────


async def arena_index(session: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    """Публичные арены каталога по городам: один запрос на страницу, дальше сопоставление в памяти."""
    index: dict[str, list[dict[str, Any]]] = {}
    for row in (await session.execute(_ARENAS, public_scope_params())).mappings().all():
        index.setdefault(_norm(row["city_name"]), []).append(dict(row))
    return index


def place_of(row: Any) -> tuple[str | None, str | None]:
    """(арена, город) матча по данным источника. У Динамо дома — Минск-Арена, на выезде места мы не знаем."""
    if row.league == LEAGUE_KHL:
        return (DINAMO_ARENA, DINAMO_CITY) if row.home_team == DINAMO else (None, None)
    club = _CLUB_BY_NAME.get(row.home_team)
    return row.arena, (row.city or (club.city if club else None))


def is_away_trip(row: Any) -> bool:
    """Выезд Динамо: КХЛ, хозяин — соперник. Места матча в нашей базе нет."""
    return row.league == LEAGUE_KHL and row.home_team != DINAMO


def resolve_arena(row: Any, index: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    """Арена матча в каталоге. Экстралига: первое слово названия с hockey.by внутри названия арены города.
    Чужой каток города за арену матча не выдаём — нет совпадения, нет арены."""
    arena_name, city = place_of(row)
    candidates = index.get(_norm(city), [])
    if row.league == LEAGUE_KHL:
        if row.home_team != DINAMO:
            return None
        found = [a for a in candidates if a.get("slug") == "minsk-arena" or _norm(a["name"]) in ("минск арена", "минск-арена")]
        return found[0] if found else None
    words = _norm((arena_name or "").replace("-", " ")).split()
    if not words:
        return None
    return next((a for a in candidates if words[0] in _norm(a["name"])), None)


def arena_path(arena: dict[str, Any] | None) -> str | None:
    if not arena or not arena.get("slug"):
        return None
    from src.application.ice_city_day import city_slug

    return f"/p/{city_slug(str(arena['city_name']))}/{arena['slug']}"


# ── Адрес и подписи ──────────────────────────────────────────────────


def match_slug(row: Any) -> str:
    """``123-yunost-shakhter``: id решает, остальное — для людей и поиска. Даты в адресе нет: перенос его не меняет."""
    return f"{int(row.id)}-{slug_for(row.home_team)}-{slug_for(row.away_team)}"


def match_path(row: Any) -> str:
    return f"{MATCH_PREFIX}/{match_slug(row)}"


def parse_match_ref(ref: str) -> int | None:
    head = (ref or "").split("-", 1)[0]
    return int(head) if head.isdigit() and 0 < int(head) < 2**31 else None


def when_text(starts_at: datetime, *, with_year: bool = False) -> str:
    """«13 ноября 19:00» (с годом — «13 ноября 2026, 19:00»)."""
    loc = local(starts_at)
    if with_year:
        return f"{loc.day} {MONTHS_GEN[loc.month - 1]} {loc.year}, {loc:%H:%M}"
    return f"{loc.day} {MONTHS_GEN[loc.month - 1]} {loc:%H:%M}"


def day_word(day: date, today: date) -> str:
    """«Сегодня» / «Завтра» / «пт, 13 ноября»."""
    diff = (day - today).days
    if diff == 0:
        return "Сегодня"
    if diff == 1:
        return "Завтра"
    return f"{WEEKDAYS_SHORT[day.weekday()]}, {day.day} {MONTHS_GEN[day.month - 1]}"


def day_heading(day: date, today: date) -> str:
    """Заголовок дня в списке: «ПЯТНИЦА, 13 НОЯБРЯ»; сегодня и завтра — со словом."""
    base = f"{WEEKDAYS_UPPER[day.weekday()]}, {day.day} {MONTHS_GEN[day.month - 1].upper()}"
    diff = (day - today).days
    if diff == 0:
        return f"СЕГОДНЯ · {base}"
    if diff == 1:
        return f"ЗАВТРА · {base}"
    return base


def phase_of(row: Any, now: datetime) -> str:
    starts = _utc(row.starts_at)
    if row.status == STATUS_FINAL and row.home_score is not None and row.away_score is not None:
        return PHASE_AFTER
    if now < starts:
        return PHASE_BEFORE
    if now < starts + LIVE_WINDOW:
        return PHASE_LIVE
    if now < starts + WAIT_WINDOW:
        return PHASE_WAIT
    return PHASE_REVIEW


def score_text(result: dict[str, Any] | None) -> str:
    """«3:2 ОТ» / «3:2 Б» / «3:2». Победа по буллитам — +1 гол победителю, как в источнике."""
    if not result:
        return ""
    suffix = {"ot": " ОТ", "so": " Б"}.get(result.get("decided_in") or "", "")
    return f"{result['home_score']}:{result['away_score']}{suffix}"


def match_card(row: Any, *, now: datetime, arena: dict[str, Any] | None = None) -> dict[str, Any]:
    """Строка матча для ленты города, списка и блоков арены. Без запросов в базу."""
    arena_text, city = place_of(row)
    phase = phase_of(row, now)
    starts = _utc(row.starts_at)
    result = None
    if phase == PHASE_AFTER:
        result = {"home_score": row.home_score, "away_score": row.away_score, "decided_in": row.decided_in}
    arena_label = arena_text or (arena or {}).get("name")
    return {
        "id": int(row.id),
        "path": match_path(row),
        "league": row.league,
        "league_label": LEAGUE_LABELS.get(row.league, ""),
        "home": team_card(row.home_team),
        "away": team_card(row.away_team),
        "home_slug": slug_for(row.home_team),
        "away_slug": slug_for(row.away_team),
        "title": f"{row.home_team} — {row.away_team}",
        "starts_at": starts,
        "local": local(starts),
        "day": local(starts).date(),
        "time": f"{local(starts):%H:%M}",
        "phase": phase,
        "result": result,
        "arena": arena_label,
        "arena_id": int(arena["id"]) if arena else None,
        "away_trip": is_away_trip(row),
        "city": city,
        "where": " · ".join(bit for bit in (city, arena_label) if bit),
    }


# ── Выборки ──────────────────────────────────────────────────────────


async def visible_rows(
    session: AsyncSession,
    *,
    since: datetime,
    until: datetime,
    settings: Settings | None = None,
    index: dict[str, list[dict[str, Any]]] | None = None,
) -> list[tuple[Any, dict[str, Any] | None]]:
    """Матчи окна, которые можно показать: в области видимости и с ареной из каталога (выезд Динамо — без неё)."""
    scope = scope_of(settings)
    if scope.empty:
        return []
    rows = list((await session.execute(_RANGE, {**_params(scope), "since": since, "until": until})).all())
    if not rows:
        return []
    arenas = index if index is not None else await arena_index(session)
    out = []
    for row in rows:
        arena = resolve_arena(row, arenas)
        if arena is not None or is_away_trip(row):
            out.append((row, arena))
    return out


def _club_cities(city: str) -> set[str]:
    return {club.name for club in CLUBS.values() if _norm(club.city) == _norm(city)}


def in_city(row: Any, city: str) -> bool:
    """Матч «в городе»: он физически проходит там. Выезд местного клуба в другом городе — не в этом."""
    return _norm(place_of(row)[1]) == _norm(city)


def venue_label(card: dict[str, Any], club_slug: str | None = None) -> str | None:
    """Метка «где играет»: «Дома · Минск-Арена» / «Выезд · Гомель» — с точки зрения клуба из фильтра.

    Без фильтра метка только у выезда Динамо (там соперник — хозяин, а места мы не знаем): «Выезд».
    Места нет — метка без «· …», ничего не выдумываем.
    """
    if club_slug is None:
        return "Выезд" if card.get("away_trip") else None
    if card["home_slug"] == club_slug:
        return "Дома" + (f" · {card['arena']}" if card.get("arena") else "")
    return "Выезд" + (f" · {card['city']}" if card.get("city") else "")


def day_sticker(starts: datetime, now: datetime) -> str | None:
    diff = (local(starts).date() - local(now).date()).days
    return "сегодня" if diff == 0 else "завтра" if diff == 1 else None


async def city_feed(
    session: AsyncSession,
    *,
    city_name: str,
    city_id: int | None = None,
    now: datetime,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """«Хоккей в городе»: где посмотреть живьём. Только матчи, которые проходят в этом городе.

    На 7 дней вперёд — плитка и лента (``empty`` ложь). Матчей нет, но в городе они ещё будут — ``empty``
    истина и ближайший матч в ``next`` («В Минске до 10 ноября матчей нет»). Матчей в городе больше нет
    вообще — ``None``, блока нет. Никаких чужих выездов и «матчей рядом». Идущий и только что сыгранный
    держатся в ленте (``BEHIND``). ``city_id`` оставлен для совместимости вызовов.
    """
    del city_id
    pairs = await visible_rows(session, since=now - BEHIND, until=now + FEED_AHEAD, settings=settings)
    mine = [(r, a) for r, a in pairs if in_city(r, city_name)]
    today = local(now).date()
    if mine:
        cards = [match_card(r, now=now, arena=a) for r, a in mine]
        return {
            "matches": cards[:CITY_LIMIT],
            "city_count": len(cards),
            "week_count": len(cards),
            "empty": False,
            "next": None,
            "first": cards[0],
            "first_word": day_sticker(cards[0]["starts_at"], now),
            "today": today,
        }
    later = await visible_rows(session, since=now + FEED_AHEAD, until=now + NEXT_IN_CITY_AHEAD, settings=settings)
    for r, a in later:
        if in_city(r, city_name):
            nxt = match_card(r, now=now, arena=a)
            return {
                "matches": [],
                "city_count": 0,
                "week_count": 0,
                "empty": True,
                "next": nxt,
                "first": nxt,
                "first_word": None,
                "today": today,
            }
    return None


async def arena_matches(
    session: AsyncSession, *, arena_id: int, now: datetime, settings: Settings | None = None
) -> list[dict[str, Any]]:
    """Матчи, которые идут на этой арене в ближайшие 7 дней (блок «Матчи здесь» и строки расписания)."""
    pairs = await visible_rows(session, since=now - BEHIND, until=now + FEED_AHEAD, settings=settings)
    return [match_card(r, now=now, arena=a) for r, a in pairs if a is not None and int(a["id"]) == int(arena_id)]


async def matches_list(
    session: AsyncSession,
    *,
    now: datetime,
    city: str | None = None,
    club: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Список «Хоккей» по дням.

    Без города и клуба — одна лента по дням. С городом — две секции: «В <городе>» (матчи там) и «По Беларуси»
    (остальные, включая выезды Динамо). Клуб (slug) — все матчи команды, дома и в гостях, одним списком по
    времени, у каждого метка «Дома · …» / «Выезд · …».
    """
    pairs = [
        (r, a)
        for r, a in await visible_rows(session, since=now - BEHIND, until=now + LIST_AHEAD, settings=settings)
        if not (r.status == STATUS_FINAL and _utc(r.starts_at) < now - BEHIND)
    ]
    cards = [(match_card(r, now=now, arena=a), in_city(r, city) if city else False) for r, a in pairs]
    # Чипы клубов — из того, что сейчас в списке. Клуб города — первым, Динамо — следом.
    seen: dict[str, dict[str, Any]] = {}
    for card, _mine in cards:
        for side in ("home", "away"):
            name = card[side]["name"]
            if name != DINAMO and name not in _CLUB_BY_NAME:
                continue
            seen.setdefault(card[f"{side}_slug"], {"slug": card[f"{side}_slug"], "name": name, "logo": card[side]["logo"]})
    mine_clubs = _club_cities(city) if city else set()
    clubs = sorted(seen.values(), key=lambda c: (c["name"] not in mine_clubs, c["name"] != DINAMO, c["name"]))
    if club:
        cards = [(c, m) for c, m in cards if club in (c["home_slug"], c["away_slug"])]
    today = local(now).date()

    def by_days(items: list[tuple[dict[str, Any], bool]]) -> list[dict[str, Any]]:
        days: list[dict[str, Any]] = []
        for card, mine in items:
            if not days or days[-1]["day"] != card["day"]:
                days.append({"day": card["day"], "label": day_heading(card["day"], today), "items": []})
            days[-1]["items"].append({**card, "mine": mine, "venue": venue_label(card, club)})
        return days

    days = by_days(cards)
    sections: list[dict[str, Any]] = []
    if city and not club:
        from src.shared.city_locative import city_locative

        where = city_locative(city)
        sections = [
            {"key": "city", "title": f"В {where}" if where else city, "days": by_days([x for x in cards if x[1]])},
            {"key": "country", "title": "По Беларуси", "days": by_days([x for x in cards if not x[1]])},
        ]
        sections = [sec for sec in sections if sec["days"]]
    first = cards[0][0] if cards else None
    return {
        "days": days,
        "sections": sections,
        "clubs": clubs,
        "club": club,
        "city": city,
        "total": len(cards),
        "today": today,
        # Недели без матчей (пауза лиги): страница не пуста, а честно говорит, когда они снова будут.
        "first_day": first["day"] if first else None,
        "pause": bool(first and (first["day"] - today).days > 7),
    }


# ── Страница матча ───────────────────────────────────────────────────


def yandex_link(arena: dict[str, Any]) -> str:
    if arena.get("latitude") is not None and arena.get("longitude") is not None:
        return f"https://yandex.by/maps/?pt={arena['longitude']},{arena['latitude']}&z=16&l=map"
    query = " ".join(str(arena.get(k) or "") for k in ("city_name", "address", "name") if arena.get(k))
    return f"https://yandex.by/maps/?text={quote(query)}"


def google_link(arena: dict[str, Any]) -> str:
    if arena.get("latitude") is not None and arena.get("longitude") is not None:
        return f"https://www.google.com/maps/search/?api=1&query={arena['latitude']},{arena['longitude']}"
    query = " ".join(str(arena.get(k) or "") for k in ("city_name", "address", "name") if arena.get(k))
    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"


def _price(slot: Any) -> str:
    from src.application.ice_city_day import format_price_minor

    minor = slot.price_adult_minor if slot.price_adult_minor is not None else slot.price_minor
    return format_price_minor(minor, str(slot.currency_code or "BYN")) if minor is not None else ""


async def ice_before(session: AsyncSession, arena: dict[str, Any], row: Any, *, now: datetime) -> dict[str, Any] | None:
    """Последнее массовое катание арены в день матча, которое кончается не позже чем за час до игры.
    Нет такого — блока нет (никаких «катание здесь же» без данных)."""
    slot = (
        await session.execute(
            _ICE_BEFORE,
            {
                "aid": int(arena["id"]),
                "day": local(row.starts_at).date(),
                "before": _utc(row.starts_at) - ICE_BEFORE_GAP,
                "now": now,
            },
        )
    ).first()
    if slot is None:
        return None
    return {"time": str(slot.starts_at_local)[:5], "until": str(slot.ends_at_local)[:5], "price": _price(slot)}


async def ice_clash_note(session: AsyncSession, arena_id: int, match: dict[str, Any], *, now: datetime) -> str:
    """Подпись строки матча в расписании арены.

    «Вечернего катания нет» — только когда это правда по нашему расписанию: в этот день у арены есть
    катание, а с момента «начало матча − 2 ч» до конца дня сеансов нет. Иначе строка нейтральная: о катании
    она ничего не утверждает, сеансы остаются на своих местах.
    """
    label = f"Матч {match['league_label']}" if match["league"] == LEAGUE_EXTRALIGA else f"Матч · {match['league_label']}"
    rows = (await session.execute(_ICE_DAY, {"aid": int(arena_id), "day": match["day"], "now": now})).all()
    if rows:
        edge = match["starts_at"] - ICE_CLASH_BEFORE
        if all(_utc(r.starts_at_utc) < edge for r in rows):
            return f"{label} · вечернего катания нет"
    return label


def _periods(details: dict) -> list[dict[str, Any]]:
    out = []
    for i, pair in enumerate(details.get("periods") or []):
        label = str(i + 1) if i < 3 else ("ОТ" if i == 3 else "Б")
        out.append({"label": label, "score": f"{pair[0]}:{pair[1]}"})
    shots = details.get("shots")
    if shots:
        out.append({"label": "Броски", "score": f"{shots[0]}:{shots[1]}"})
    return out


def _goals(details: dict, home: str, away: str) -> list[dict[str, Any]]:
    """Голы с бегущим счётом. Берём только факты: минута, команда, счёт, автор."""
    out: list[dict[str, Any]] = []
    h = a = 0
    for goal in details.get("goals") or []:
        side = goal.get("side")
        if side == "home":
            h += 1
        elif side == "away":
            a += 1
        else:
            continue
        minute = str(goal.get("minute") or "")
        try:
            over = int(minute.split(":")[0]) >= 60
        except ValueError:
            over = False
        out.append(
            {
                "minute": minute,
                "team": home if side == "home" else away,
                "score": f"{h}:{a}",
                "scorer": goal.get("scorer") or "",
                "over": over,
            }
        )
    return out


def tickets_of(row: Any) -> dict[str, Any] | None:
    """Билеты — ссылка hockey.by как есть. ``direct`` — ссылка на этот матч, а не на раздел билетов."""
    if row.league == LEAGUE_EXTRALIGA:
        url = (row.tickets_url or "").strip()
        return {"url": url, "direct": True} if url else None
    from src.application.hockey_event import tickets_url

    raw = (row.source_match_id or "").strip()
    return {"url": tickets_url(row.source_match_id), "direct": raw.isdigit()}


def protocol_url(row: Any) -> str | None:
    raw = (row.source_match_id or "").strip()
    if row.league == LEAGUE_EXTRALIGA and raw:
        return match_page_url(raw)
    if row.league == LEAGUE_KHL and raw.isdigit():
        return f"{HCDINAMO_BASE}/matches/{raw}/"
    return None


async def _game(session: AsyncSession, row: Any, card: dict[str, Any], *, now: datetime, cfg: Settings) -> dict[str, Any]:
    """Блок «Кто кого». На Динамо — игра. На Экстралиге — игра за флагом, пока ветка игры не влита:
    без флага строка «скоро откроем» (так же, как в Mini App). Доли — агрегат, без имён и только от 10 ходов."""
    if row.league == LEAGUE_EXTRALIGA and not cfg.site_matches_game_extraliga:
        return {"kind": "soon", "match_id": card["id"]}
    nxt = (
        await session.execute(
            _NEXT_HOME,
            {"home": row.home_team, "league": row.league, "after": max(now, _utc(row.starts_at)), "id": row.id},
        )
    ).one_or_none()
    picks = (await session.execute(_PICKS, {"id": row.id})).one()
    total = int(picks.total or 0)
    return {
        "kind": "game",
        "phase": card["phase"],
        "match_id": card["id"],
        "next": {"id": int(nxt.id), "away": nxt.away_team, "starts_at": _utc(nxt.starts_at)} if nxt else None,
        "total": total,
        # Людьми, без процентов; от 10 ходов — меньше выборка выдаёт отдельных людей.
        "home_n": int(picks.home or 0) if total >= 10 else None,
        "away_n": total - int(picks.home or 0) if total >= 10 else None,
        "right": int(picks.right_ or 0),
    }


_LIVE = text("SELECT live_home_score, live_away_score, live_at FROM hockey_matches WHERE id = :id")


async def live_score(session: AsyncSession, match_id: int) -> dict[str, Any] | None:
    """Промежуточный счёт идущего матча, который пишет поток игры (``set_live_score``). Пусто — ``None``:
    страница честно ведёт в протокол, ничего не выдумывая."""
    row = (await session.execute(_LIVE, {"id": int(match_id)})).one_or_none()
    if row is None or row.live_home_score is None or row.live_away_score is None or row.live_at is None:
        return None
    return {"score": f"{row.live_home_score}:{row.live_away_score}", "at": f"{local(row.live_at):%H:%M}"}


def club_links(card: dict[str, Any]) -> list[dict[str, str]]:
    """Команды матча, у которых есть свой список «все матчи» (Динамо и клубы Экстралиги)."""
    out = []
    for side in ("home", "away"):
        name = card[side]["name"]
        if name == DINAMO or name in _CLUB_BY_NAME:
            out.append({"slug": card[f"{side}_slug"], "name": name})
    return out


async def match_page_data(
    session: AsyncSession, match_id: int, *, now: datetime, settings: Settings | None = None
) -> dict[str, Any] | None:
    """Всё для страницы матча. ``None`` — матча нет, клуб не включён или арены нет в каталоге."""
    from src.application.extraliga_preview import match_preview

    cfg = settings or Settings()  # type: ignore[call-arg]
    scope = scope_of(cfg)
    if scope.empty:
        return None
    row = (await session.execute(_ONE, {**_params(scope), "id": int(match_id)})).one_or_none()
    if row is None:
        return None
    index = await arena_index(session)
    arena = resolve_arena(row, index)
    away = is_away_trip(row)
    if arena is None and not away:
        return None
    card = match_card(row, now=now, arena=arena)
    after = card["phase"] == PHASE_AFTER
    gone = hidden(row)
    details = dict(row.details or {}) if after else {}
    day_start = datetime.combine(card["day"], datetime.min.time(), tzinfo=MINSK_TZ)
    others = [
        match_card(r, now=now, arena=a)
        for r, a in await visible_rows(
            session, since=_utc(day_start), until=_utc(day_start + timedelta(days=1)), settings=cfg, index=index
        )
        if r.id != row.id
    ][:OTHERS_LIMIT]
    preview = None if gone or (after and details) else await match_preview(session, int(row.id))
    return {
        "row": row,
        "match": card,
        "gone": gone,
        "arena": arena,
        "away_trip": away,
        "arena_path": arena_path(arena),
        "arena_name": (card["arena"] or arena["name"]) if arena else "",
        "city": arena["city_name"] if arena else None,
        "club_links": club_links(card),
        "ice_before": (
            await ice_before(session, arena, row, now=now)
            if arena is not None and card["phase"] == PHASE_BEFORE and not gone
            else None
        ),
        "preview": preview,
        "periods": _periods(details) if details else [],
        "goals": _goals(details, row.home_team, row.away_team) if details else [],
        "tickets": tickets_of(row) if card["phase"] == PHASE_BEFORE and not gone and not away else None,
        "protocol_url": protocol_url(row),
        "live": await live_score(session, row.id) if card["phase"] == PHASE_LIVE and not gone else None,
        "others": [] if gone else others,
        "game": None if gone else await _game(session, row, card, now=now, cfg=cfg),
    }


# ── .ics ─────────────────────────────────────────────────────────────

MATCH_DURATION = timedelta(hours=3)


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Строки .ics длиннее 75 октетов переносятся по октетам UTF-8, не по символам (RFC 5545 §3.1)."""
    if len(line.encode("utf-8")) <= 75:
        return line
    parts: list[str] = []
    current = b""
    limit = 75
    for ch in line:
        encoded = ch.encode("utf-8")
        if len(current) + len(encoded) > limit:
            parts.append(current.decode("utf-8"))
            current = b""
            limit = 74
        current += encoded
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def build_ics(*, row: Any, url: str, arena_name: str, address: str | None, now: datetime) -> str:
    """Календарное событие матча: время в UTC (``Z``), календарь сам покажет местное."""
    starts = _utc(row.starts_at)
    stamp = _utc(now).strftime("%Y%m%dT%H%M%SZ")
    uid = hashlib.sha1(f"glide-match-{int(row.id)}".encode()).hexdigest()[:20] + "@glideclub.by"
    where = ", ".join(bit for bit in (arena_name, address) if bit)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Glide//Hockey matches//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{starts.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{(starts + MATCH_DURATION).strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{_ics_escape(f'{row.home_team} — {row.away_team}')}",
        f"LOCATION:{_ics_escape(where)}",
        f"DESCRIPTION:{_ics_escape(f'Страница матча: {url}')}",
        f"URL:{url}",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        "DESCRIPTION:Матч через 3 часа",
        "TRIGGER:-PT3H",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


# ── Sitemap ──────────────────────────────────────────────────────────


async def sitemap_rows(
    session: AsyncSession, *, now: datetime, settings: Settings | None = None
) -> list[tuple[str, datetime]]:
    """Предстоящие матчи на 45 дней вперёд и сыгранные за последние 30: (путь, lastmod).

    lastmod — по ``updated_at`` записи (не по времени матча), и не позже «сейчас».
    """
    pairs = await visible_rows(session, since=now - SITEMAP_BACK, until=now + SITEMAP_AHEAD, settings=settings)
    return [(match_path(r), min(_utc(r.updated_at), now)) for r, _a in pairs]


__all__ = [
    "MATCH_PREFIX",
    "SITE_PATH",
    "arena_matches",
    "build_ics",
    "city_feed",
    "match_card",
    "match_page_data",
    "match_path",
    "matches_list",
    "parse_match_ref",
    "site_enabled",
]
