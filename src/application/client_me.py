"""Сборка ответа вкладки «Я» из уже существующих источников (TASK-368). Без HTTP."""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from collections.abc import Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_public_use_cases import public_arena_session_days
from src.application.booking_use_cases import _SQL_SLOT_END_TS, _SQL_SLOT_START_TS
from src.application.booking_use_cases import (
    client_latest_booking_primary_candidate,
    client_upcoming_booking_primary_candidate,
)
from src.application.client_account import get_home_arena_id
from src.application.client_trainer_edge_use_cases import get_primary_edge, trainer_display_hints_by_ids
from src.application.client_profile_use_cases import list_accessible_profiles, resolve_acting_client_id
from src.application.client_stats_use_cases import get_client_activity_snapshot
from src.application.client_use_cases import get_client_id_by_telegram_id
from src.application.hockey_hub import HOME_AHEAD
from src.application.hockey_notices import get_prefs
from src.application.hockey_screens import fan_profile
from src.application.hockey_teams import display_name, team_card
from src.application.pass_product_use_cases import list_client_pass_instances
from src.infrastructure.db.models import CLIENT_PROFILE_ROLE_SELF, ICE_WATCH_KIND_SESSIONS
from src.ingestion.hockey_sources import MINSK_TZ
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
from src.application.style_b import b_photo_url
from src.shared.public_display import format_clock
from src.shared.ru_text import plural_ru

_KK_HREF = "/webapp/kto-kogo"
_INK_LIGHT = "#FFFFFF"
_INK_DARK = "#0D1B26"
_CONTRAST = 4.5

_DISPLAY_NAME = text("SELECT display_name FROM hockey_players WHERE player_key = :player_key")

_CITY = text("""
    SELECT c.name
    FROM client_sessions s
    JOIN cities c ON c.id = s.city_id
    WHERE s.telegram_id = :telegram_id
    """)

_NEXT_MATCH = text("""
    SELECT m.home_team, m.away_team, m.starts_at
    FROM kk_matches AS m
    WHERE m.status = 'scheduled'
      AND m.starts_at > :now
      AND m.starts_at <= :until
      AND (m.home_team = :club OR m.away_team = :club)
    ORDER BY m.starts_at, m.id
    LIMIT 1
    """)

_ARENA = text(f"""
    SELECT a.name, COALESCE(p.timezone, 'Europe/Minsk') AS tz,
           (
               SELECT m.variants
               FROM media m
               WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
               ORDER BY m.sort_order, m.id
               LIMIT 1
           ) AS photo_variants
    FROM arenas a
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    WHERE a.id = :arena_id
      AND {PUBLIC_ARENA_VISIBLE_SQL}
    """)

_SUBSCRIBED = text("""
    SELECT 1
    FROM client_ice_watches
    WHERE client_id = :client_id
      AND arena_id = :arena_id
      AND active
      AND watch_kind = :kind
    LIMIT 1
    """)

_BOOKINGS = text(f"""
    SELECT
        EXISTS (
            SELECT 1 FROM bookings b
            WHERE b.client_id = :cid AND NOT b.is_sandbox
        ) AS ever,
        (
            SELECT {_SQL_SLOT_START_TS}
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.client_id = :cid
              AND s.status IN ('available', 'booked')
              AND b.status IN ('pending', 'confirmed')
              AND {_SQL_SLOT_END_TS} > CURRENT_TIMESTAMP
            ORDER BY s.slot_date, s.start_time, b.id
            LIMIT 1
        ) AS next_at
    """)

# Тот же набор, что GET /client/passes (active и used_up). Остаток — только не истёкшие active.
_PASSES = text("""
    SELECT
        COUNT(*) FILTER (WHERE status IN ('active', 'used_up'))::int AS listed,
        COALESCE(SUM(sessions_remaining) FILTER (
            WHERE status = 'active'
              AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
        ), 0)::int AS lessons_left
    FROM pass_instances
    WHERE client_id = :cid
    """)

# Страница «Сохранённые»: тренеры с закладкой, катки колокольчика, активные напоминания о слотах.
_SAVED = text("""
    SELECT
        (
            SELECT COUNT(*)::int FROM client_trainer_edges
            WHERE client_id = :cid AND is_saved
        ) + (
            SELECT COUNT(*)::int FROM client_ice_watches
            WHERE client_id = :cid AND active
        ) + (
            SELECT COUNT(*)::int FROM client_trainer_edges
            WHERE client_id = :cid AND notify_when_slots
        ) AS n
    """)

_REQUESTS = text("""
    SELECT COUNT(*)::int
    FROM client_requests
    WHERE client_id = :cid AND status != 'archived'
    """)


def label_ink(color: str) -> str:
    """Белый, если контраст белого к цвету клуба ≥ 4.5, иначе чернила экрана."""
    return _INK_LIGHT if _contrast_white(color) >= _CONTRAST else _INK_DARK


def initial_of(name: str) -> str:
    """Первый буквенный символ в верхнем регистре. Букв нет — «?»."""
    for ch in name or "":
        if unicodedata.category(ch).startswith("L"):
            return ch.upper()
    return "?"


def _channel(value: int) -> float:
    c = value / 255
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _contrast_white(color: str) -> float:
    raw = color.lstrip("#")
    lum = (
        0.2126 * _channel(int(raw[0:2], 16))
        + 0.7152 * _channel(int(raw[2:4], 16))
        + 0.0722 * _channel(int(raw[4:6], 16))
    )
    lighter = 1.0 if 1.0 >= lum else lum
    darker = lum if 1.0 >= lum else 1.0
    return (lighter + 0.05) / (darker + 0.05)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MINSK_TZ).isoformat(timespec="seconds")


def _zero_null(value: int) -> int | None:
    return None if int(value) == 0 else int(value)


def _given_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip()
    return name or None


def _family(profiles: list[dict], *, account_name: str, acting: int | None) -> dict:
    """Люди «Семьи» из уже прочитанного списка. «Вы» первым, ровно один active."""
    self_rows = [row for row in profiles if row.get("role") == CLIENT_PROFILE_ROLE_SELF]
    others = [row for row in profiles if row.get("role") != CLIENT_PROFILE_ROLE_SELF]
    people: list[dict] = [
        {
            "profile_id": int(row["client_id"]),
            "name": account_name,
            "is_you": True,
            "active": False,
        }
        for row in self_rows
    ]
    if not people:
        people.append({"profile_id": None, "name": account_name, "is_you": True, "active": False})
    for row in others:
        people.append(
            {
                "profile_id": int(row["client_id"]),
                "name": _given_name(row.get("first_name")),
                "is_you": False,
                "active": False,
            }
        )
    active_at = next(
        (i for i, person in enumerate(people) if acting is not None and person["profile_id"] == acting),
        0,
    )
    people[active_at]["active"] = True
    return {"people": people}


def _profile_name(profiles: list[dict], *, acting: int | None, own: int | None) -> str | None:
    if acting is None or own is None or acting == own:
        return None
    match = next((p for p in profiles if int(p["client_id"]) == acting), None)
    if match is None:
        return None
    parts = [str(match.get("first_name") or "").strip(), str(match.get("last_name") or "").strip()]
    name = " ".join(part for part in parts if part)
    return name or None


async def _club(session: AsyncSession, club: str | None, *, now: datetime) -> dict | None:
    if not club:
        return None
    card = team_card(club)
    row = (
        await session.execute(
            _NEXT_MATCH,
            {"club": club, "now": now, "until": now + HOME_AHEAD},
        )
    ).one_or_none()
    nxt = None
    if row is not None:
        opponent = row.away_team if row.home_team == club else row.home_team
        nxt = {
            "starts_at": _iso(row.starts_at),
            "opponent": display_name(opponent),
            "href": _KK_HREF,
            "label": _match_label(row.starts_at, display_name(opponent), now),
        }
    return {
        "name": card["name"],
        "short": card["short"],
        "color": card["color"],
        "logo": card["logo"],
        "label_ink": label_ink(card["color"]),
        "next_match": nxt,
    }


async def home_arena_payload(
    session: AsyncSession,
    *,
    arena_id: int | None,
    client_id: int | None,
    now: datetime | None = None,
    include_v2: bool = False,
) -> dict | None:
    """Блок «мой каток» в форме GET. ``None`` — каток не выбран, арены нет или она стала скрытой (выбор в prefs не трогаем)."""
    if arena_id is None:
        return None
    arena = (
        await session.execute(_ARENA, {"arena_id": arena_id, **public_scope_params()})
    ).one_or_none()
    if arena is None:
        return None
    try:
        tz = ZoneInfo(str(arena.tz or "Europe/Minsk"))
    except Exception:  # noqa: BLE001 — битый пояс в профиле не роняет экран
        tz = ZoneInfo("Europe/Minsk")
    moment = now.astimezone(tz) if now is not None else datetime.now(tz)
    today = moment.date()
    tomorrow = today + timedelta(days=1)
    days = await public_arena_session_days(
        session,
        int(arena_id),
        date_from=today,
        date_to=tomorrow,
        now=moment,
    )
    by_day = {str(day["local_date"]): list(day.get("sessions") or []) for day in days}
    today_sessions = by_day.get(today.isoformat(), [])
    left = len(today_sessions)
    tomorrow_first = None
    if left == 0:
        upcoming = by_day.get(tomorrow.isoformat()) or []
        if upcoming:
            tomorrow_first = format_clock(str(upcoming[0].get("starts_at_local") or ""))
    subscribed = False
    if client_id is not None:
        hit = (
            await session.execute(
                _SUBSCRIBED,
                {"client_id": client_id, "arena_id": arena_id, "kind": ICE_WATCH_KIND_SESSIONS},
            )
        ).first()
        subscribed = hit is not None
    out = {
        "id": int(arena_id),
        "name": arena.name,
        "href": f"/webapp/arena?id={int(arena_id)}",
        "sessions_left_today": left,
        "tomorrow_first": tomorrow_first,
        "subscribed": subscribed,
    }
    if include_v2:
        raw = arena.get("photo_variants")
        if isinstance(raw, str):
            raw = json.loads(raw)
        variants = raw if isinstance(raw, Mapping) else {}
        out["photo"] = {
            "thumb": b_photo_url(variants.get("thumb") or variants.get("card")),
            "card": b_photo_url(variants.get("card") or variants.get("thumb")),
        }
        out["today_times"] = [
            format_clock(str(s2.get("starts_at_local") or ""))
            for s2 in today_sessions[:5]
        ]
    return out


async def _bookings(session: AsyncSession, client_id: int) -> dict | None:
    row = (await session.execute(_BOOKINGS, {"cid": client_id})).one()
    if not row.ever and row.next_at is None:
        return None
    return {"next_starts_at": None if row.next_at is None else _iso(row.next_at)}


async def _passes(session: AsyncSession, client_id: int) -> dict | None:
    row = (await session.execute(_PASSES, {"cid": client_id})).one()
    if int(row.listed or 0) == 0:
        return None
    return {"lessons_left": int(row.lessons_left or 0)}


async def _saved(session: AsyncSession, client_id: int) -> dict | None:
    n = int((await session.execute(_SAVED, {"cid": client_id})).scalar_one() or 0)
    return None if n == 0 else {"count": n}


async def _requests(session: AsyncSession, client_id: int) -> dict | None:
    n = int((await session.execute(_REQUESTS, {"cid": client_id})).scalar_one() or 0)
    return None if n == 0 else {"count": n}


async def _my_trainer(session: AsyncSession, *, account_key: int, acting: int) -> dict | None:
    """«Мой тренер» для строки в «Я»: только чтение, упрощённое зеркало «Главной».

    Порядок как в хабе (hub_booking_primary_ids + resolve_primary_trainer_strict):
    предстоящая запись (кандидат сортируется DESC: берётся самая дальняя из предстоящих,
    как и в хабе), иначе последняя запись, иначе явный primary edge.
    Осознанное расхождение с «Главной»: НЕ учитываются session_tid (временный выбор
    тренера по приглашению из bot-session), ever_booked-пол и «сохранённые».
    Имя — из trainer_display_hints_by_ids, как у хаба; тренера нет в выдаче → None.
    """
    tid, _ = await client_upcoming_booking_primary_candidate(session, account_key, acting_client_id=acting)
    if tid is None:
        tid, _ = await client_latest_booking_primary_candidate(session, account_key, acting_client_id=acting)
    if tid is None:
        edge = await get_primary_edge(acting, session)
        tid = int(edge["trainer_id"]) if edge and edge.get("trainer_id") else None
    if tid is None:
        return None
    hint = (await trainer_display_hints_by_ids(session, [int(tid)])).get(int(tid))
    name = ((hint or {}).get("trainer_display_name") or "").strip()
    # Пустой профиль хинты подменяют заглушкой «Тренер»; строки «Мой тренер — Тренер» не нужно.
    # Цена: тренер, буквально назвавшийся «Тренер», строку не получит.
    if not name or name == "Тренер":
        return None
    return {"name": name, "href": f"/webapp/catalog?trainer_id={int(tid)}"}


_JOINED = text("SELECT created_at FROM clients WHERE id = :cid")

# TASK-449: «Сохранённое» строкой «2 катка · 1 тренер» — подписки на катки + сохранённые тренеры.
_SAVED_V2 = text("""
    SELECT
        (SELECT COUNT(*)::int FROM client_ice_watches WHERE client_id = :cid AND active) AS arenas,
        (SELECT COUNT(*)::int FROM client_trainer_edges WHERE client_id = :cid AND is_saved) AS trainers
    """)

_MONTHS_SHORT_GEN = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
_WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def _match_label(starts_at: datetime, opponent: str, now: datetime) -> str:
    """«Сегодня 19:00 · Барыс» / «Завтра 19:00 · …» / «сб, 28 · 19:00 · …» — по Минску."""
    local = _aware_minsk(starts_at)
    today = _aware_minsk(now).date()
    hhmm = f"{local.hour:02d}:{local.minute:02d}"
    if local.date() == today:
        day = "Сегодня"
    elif local.date() == today + timedelta(days=1):
        day = "Завтра"
    else:
        day = f"{_WEEKDAYS_SHORT[local.weekday()]}, {local.day}"
    return f"{day} {hhmm} · {opponent}"


def _aware_minsk(value: datetime) -> datetime:
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(MINSK_TZ)


def _joined_label(created_at: datetime | None, now: datetime) -> str | None:
    """«в Glide с октября» / «с октября 2025», если аккаунт старше года."""
    if created_at is None:
        return None
    local = _aware_minsk(created_at)
    month = _MONTHS_SHORT_GEN[local.month - 1]
    if (now - created_at).days >= 360:
        return f"в Glide с {month} {local.year}"
    return f"в Glide с {month}"


def _expires_label(expires_at: datetime | None) -> str | None:
    if expires_at is None:
        return None
    local = _aware_minsk(expires_at)
    return f"до {local.day} {_MONTHS_SHORT_GEN[local.month - 1]}"


async def _pass_detail(session: AsyncSession, client_id: int) -> dict | None:
    """Активный абонемент для карточки «Я» v2: остаток, тренер, срок, куда записаться."""
    items = await list_client_pass_instances(session, client_id)
    active = None
    for it in items:
        if it.get("status") != "active" or it.get("is_expired"):
            continue
        if int(it.get("sessions_remaining") or 0) <= 0:
            continue
        active = it
        break
    if active is None:
        return None
    tid = int(active["trainer_id"])
    hint = (await trainer_display_hints_by_ids(session, [tid])).get(tid) or {}
    expires = active.get("expires_at")
    if isinstance(expires, str):
        try:
            expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        except ValueError:
            expires = None
    return {
        "left": int(active["sessions_remaining"]),
        "total": int(active.get("sessions_total") or 0),
        "trainer_id": tid,
        "trainer_name": str(active.get("trainer_name") or ""),
        "trainer_photo_key": hint.get("photo_list_key") or hint.get("photo_key"),
        "expires_label": _expires_label(expires),
        "book_href": f"catalog?trainer_id={tid}",
    }


async def _saved_v2(session: AsyncSession, client_id: int) -> dict | None:
    row = (await session.execute(_SAVED_V2, {"cid": client_id})).one()
    arenas, trainers = int(row.arenas or 0), int(row.trainers or 0)
    if not arenas and not trainers:
        return None
    parts = []
    if arenas:
        parts.append(f"{arenas} {plural_ru(arenas, 'каток', 'катка', 'катков')}")
    if trainers:
        parts.append(f"{trainers} {plural_ru(trainers, 'тренер', 'тренера', 'тренеров')}")
    return {"arenas": arenas, "trainers": trainers, "line": " · ".join(parts)}


async def client_me(
    session: AsyncSession,
    *,
    account_key: int,
    profile_id: int | None,
    telegram_name: str,
    now: datetime | None = None,
    include_v2: bool = False,
    include_companies: bool = False,
    include_badges: bool = False,
) -> dict:
    """Один экран «Я». Запросы идут по очереди: одна сессия не держит их параллельно."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    stored = (await session.execute(_DISPLAY_NAME, {"player_key": account_key})).scalar_one_or_none()
    name = telegram_name if stored is None else str(stored)
    city = (await session.execute(_CITY, {"telegram_id": account_key})).scalar_one_or_none()
    club_name = (await get_prefs(session, account_key))["fav_club"]
    club = await _club(session, club_name, now=moment)

    acting = await resolve_acting_client_id(session, account_key, profile_id)
    own = acting if profile_id is None else await get_client_id_by_telegram_id(session, account_key)

    arena_id = await get_home_arena_id(session, account_key)
    home = await home_arena_payload(session, arena_id=arena_id, client_id=own, now=moment, include_v2=include_v2)

    snap = await get_client_activity_snapshot(session, client_id=acting)
    fan = await fan_profile(session, player_key=account_key, now=moment)
    overall = fan.get("overall") or None
    played = int(overall["played"]) if overall else 0
    if overall is None or played == 0:
        kk_points = None
        kk_place = None
    else:
        kk_points = int(overall["points"])
        kk_place = int(overall["rank"])

    if acting is None:
        bookings = passes = saved = requests = trainer = None
    else:
        bookings = await _bookings(session, acting)
        passes = await _passes(session, acting)
        saved = await _saved(session, acting)
        requests = await _requests(session, acting)
        trainer = await _my_trainer(session, account_key=account_key, acting=acting)

    profiles = await list_accessible_profiles(session, account_key)
    out = {
        "name": name,
        "initial": initial_of(name),
        "city": None if city is None else str(city),
        "club": club,
        "home_arena": home,
        "stats": {
            "trainings": _zero_null(snap["completed_total"]),
            "streak_weeks": _zero_null(snap["streak_weeks"]),
            "kk_points": kk_points,
            "kk_place": kk_place,
        },
        "rows": {
            "bookings": bookings,
            "passes": passes,
            "saved": saved,
            "family": _family(profiles, account_name=name, acting=acting),
            "requests": requests,
            "trainer": trainer,
        },
        "profile_name": _profile_name(profiles, acting=acting, own=own),
    }
    # «Я» v2 (TASK-449, redesign_s4): карточки абонемента/сохранённого/«в Glide с…».
    if include_v2:
        out["joined_label"] = None
        joined = (await session.execute(_JOINED, {"cid": own})).scalar_one_or_none() if own else None
        if isinstance(joined, datetime):
            out["joined_label"] = _joined_label(joined, moment)
        out["pass"] = await _pass_detail(session, acting) if acting else None
        saved_v2 = await _saved_v2(session, acting) if acting else None
        if saved_v2 and saved:
            saved["line"] = saved_v2["line"]
        out["saved_detail"] = saved_v2
    # TASK-450 (5.3): «Мои компании» — открытые, где я организатор или «иду/может» (s5).
    if include_companies:
        from src.application.ice_company.mine import my_open_companies

        out["companies"] = await my_open_companies(session, account_key, moment, limit=5)
    # TASK-451 (5.4): значки волны 1 — те же (tg, профиль) ключи, что у отметок.
    if include_badges:
        from src.application import ice_badges as ib

        badge_pid = acting if acting is not None and own is not None and acting != own else None
        out["badges"] = await ib.badges_payload(
            session, account_key, badge_pid, moment.astimezone(MINSK_TZ).date()
        )
    return out
