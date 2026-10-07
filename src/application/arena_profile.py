"""
Arena catalog profile (TASK-048): slug, amenities, season, district helpers.

``arenas`` stays the trainer-workplace dictionary (name, address, coords, ``is_confirmed``).
Vitrine fields live on ``arena_profiles`` (1:1). ``status`` (draft|published|archived) is
publication of the Ice Discovery card — not the same as ``arenas.is_confirmed`` (moderation
of trainer-created workplaces, TASK-046).
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.arena_schedule_mode import (
    SCHEDULE_MODE_AUTO,
    SCHEDULE_MODE_SEASON_CLOSED,
    normalize_schedule_mode,
    validate_schedule_mode_patch,
)

ARENA_PROFILE_STATUS_DRAFT = "draft"
ARENA_PROFILE_STATUS_PUBLISHED = "published"
ARENA_PROFILE_STATUS_ARCHIVED = "archived"
ARENA_PROFILE_STATUSES = (
    ARENA_PROFILE_STATUS_DRAFT,
    ARENA_PROFILE_STATUS_PUBLISHED,
    ARENA_PROFILE_STATUS_ARCHIVED,
)

# Canonical amenity keys (prototype chips + accessibility). Values are bool.
# Three states, not two: key absent = unknown, False = known absent, True = present.
# The Minsk loader relies on that (an unknown amenity stays unset, never False).
VENUE_AMENITY_KEYS = frozenset(
    {
        "skate_rental",  # прокат
        "skate_sharpening",  # заточка
        "parking",  # парковка
        "locker_rooms",  # раздевалки
        "cafe",  # кафе
        "accessibility",  # доступность
    }
)

# TASK-146: магазин описывается тем же полем, но другим набором ключей. Прокат и
# заточка — те же самые услуги, что «на катке есть прокат», поэтому ключи общие:
# фильтр «где заточить коньки» найдёт и мастерскую, и каток с заточкой.
# Розница и ремонт бывают только у магазина — катку их не поставить.
SHOP_AMENITY_KEYS = frozenset(
    {
        "retail",  # розница
        "skate_sharpening",
        "skate_rental",
        "repair",  # ремонт коньков, клюшек, формы
        "skate_molding",  # формовка (термоформовка ботинка)
        "blade_profiling",  # профилирование лезвия
        "foot_scan",  # 3D-скан стопы для подбора коньков
        # Специализация: заточка хоккейных и фигурных — физически разные работы,
        # и «хоккейный магазин» фигуристу почти бесполезен. Поэтому явно, а не тегом.
        "discipline_hockey",
        "discipline_figure",
        "discipline_roller",
        "parking",
        "accessibility",
    }
)

#: Услуги магазина в порядке показа (плитки и строка ленты).
SHOP_SERVICE_KEYS: tuple[str, ...] = (
    "retail",
    "skate_sharpening",
    "skate_molding",
    "blade_profiling",
    "foot_scan",
    "skate_rental",
    "repair",
)
#: Специализации — отдельной строкой тегов, не плитками.
SHOP_DISCIPLINE_KEYS: tuple[str, ...] = ("discipline_hockey", "discipline_figure", "discipline_roller")

AMENITY_KEYS = VENUE_AMENITY_KEYS | SHOP_AMENITY_KEYS

AMENITY_LABELS_RU = {
    "skate_rental": "Прокат",
    "skate_sharpening": "Заточка",
    "parking": "Парковка",
    "locker_rooms": "Раздевалки",
    "cafe": "Кафе",
    "accessibility": "Доступность",
    "retail": "Розница",
    "repair": "Ремонт",
    "skate_molding": "Формовка",
    "blade_profiling": "Профилирование",
    "foot_scan": "3D-скан стопы",
    "discipline_hockey": "Хоккей",
    "discipline_figure": "Фигурное",
    "discipline_roller": "Ролики",
}


def amenity_keys_for_venue(venue_type: str | None) -> frozenset[str]:
    """Допустимые ключи для типа площадки. Неизвестный тип — как каток."""
    from src.shared.venue_types import VENUE_TYPE_SHOP, normalize_venue_type

    if normalize_venue_type(venue_type) == VENUE_TYPE_SHOP:
        return SHOP_AMENITY_KEYS
    return VENUE_AMENITY_KEYS


_CYRILLIC_TO_LATIN = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


class InvalidAmenitiesError(ValueError):
    """Unknown amenity key or non-bool value — reject on write, do not store silently."""


class InvalidArenaProfileStatusError(ValueError):
    """status must be draft | published | archived."""


# ---------------------------------------------------------------------------
# TASK-177: publish guard. «Тестовая Арена 1/3» reached the prod catalog because
# every create path inserted the profile as ``published`` unconditionally.
# ---------------------------------------------------------------------------

# «тест»/«test» at a word start: «Тестовая арена», «Test rink», «arena-test» — but not
# «Протестантская» or «Contest». \w is unicode-aware, so Cyrillic counts as a word char.
_TEST_NAME_RE = re.compile(r"(?<!\w)(?:тест|test)", re.IGNORECASE)

PUBLISH_BLOCKER_TEST_NAME = "test_name"
PUBLISH_BLOCKER_EMPTY_NAME = "empty_name"
PUBLISH_BLOCKER_NO_COORDINATES = "no_coordinates"


class ArenaNotPublishableError(ValueError):
    """Explicit publish of an arena that fails ``arena_publish_blockers``."""


def looks_like_test_arena_name(name: str | None) -> bool:
    return bool(_TEST_NAME_RE.search(name or ""))


def arena_publish_blockers(
    *,
    name: str | None,
    venue_type: str | None,
    latitude: float | None,
    longitude: float | None,
) -> list[str]:
    """Why this arena must not be published; empty list — it may be.

    Coordinates are required for rinks only: a rink off the map is a broken card on
    every map/nearby surface. Shops without coordinates are a supported state (imported
    before geocoding, listed but «not on map» — see catalog_shops_import). The city is
    a NOT NULL FK on ``arenas``, so «no city» cannot happen at this layer.
    """
    out: list[str] = []
    if not (name or "").strip():
        out.append(PUBLISH_BLOCKER_EMPTY_NAME)
    elif looks_like_test_arena_name(name):
        out.append(PUBLISH_BLOCKER_TEST_NAME)
    if (venue_type or "ice") == "ice" and (latitude is None or longitude is None):
        out.append(PUBLISH_BLOCKER_NO_COORDINATES)
    return out


async def load_arena_publish_blockers(session: AsyncSession, arena_id: int) -> list[str]:
    row = (
        await session.execute(
            text("SELECT name, venue_type, latitude, longitude FROM arenas WHERE id = :id"),
            {"id": int(arena_id)},
        )
    ).fetchone()
    if row is None:
        return []
    return arena_publish_blockers(name=row[0], venue_type=row[1], latitude=row[2], longitude=row[3])


def slugify_arena_name(name: str) -> str:
    """Transliterate a venue name to a URL-safe slug. Stable for the same input."""
    raw = (name or "").strip().lower()
    chars: list[str] = []
    for ch in raw:
        if ch in _CYRILLIC_TO_LATIN:
            chars.append(_CYRILLIC_TO_LATIN[ch])
        elif ch.isascii() and (ch.isalnum() or ch in "-_"):
            chars.append(ch)
        else:
            chars.append("-")
    slug = re.sub(r"-+", "-", "".join(chars)).strip("-")
    return slug or "arena"


def choose_arena_slug(
    base: str,
    *,
    taken: set[str],
    district: str | None,
    arena_id: int,
) -> str:
    """
    Pick a city-unique slug. Prefer the name slug; on collision append district, then id.

    Existing values in ``taken`` are never reused. Callers that already have a slug
    must not call this — backfill is idempotent only if it skips assigned slugs.
    """
    if base not in taken:
        return base
    if district:
        with_district = f"{base}-{slugify_arena_name(district)}"
        if with_district not in taken:
            return with_district
    return f"{base}-{int(arena_id)}"


def validate_amenities(
    value: Mapping[str, Any] | None, venue_type: str | None = None
) -> dict[str, bool]:
    """Ключи сверяются с типом площадки: «розница» у катка — ошибка ввода, а не данные."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise InvalidAmenitiesError("amenities must be an object")
    allowed = amenity_keys_for_venue(venue_type)
    out: dict[str, bool] = {}
    for key, raw in value.items():
        if key not in allowed:
            raise InvalidAmenitiesError(f"unknown amenity key: {key}")
        if not isinstance(raw, bool):
            raise InvalidAmenitiesError(f"amenity {key} must be a boolean")
        out[str(key)] = raw
    return out


def public_http_url(raw: Any) -> str | None:
    """http(s) only. Empty, javascript:, or whitespace in the value → None."""
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    lower = value.lower()
    if not (lower.startswith("https://") or lower.startswith("http://")):
        return None
    if any(ch.isspace() or ch in "<>\"'" for ch in value):
        return None
    if len(value) > 512:
        return None
    return value


def validate_profile_status(status: str | None) -> str:
    value = (status or ARENA_PROFILE_STATUS_PUBLISHED).strip()
    if value not in ARENA_PROFILE_STATUSES:
        raise InvalidArenaProfileStatusError(f"invalid arena profile status: {value}")
    return value


def is_in_season(start_month: int | None, end_month: int | None, month: int) -> bool:
    """True when ``month`` (1–12) falls in the season, including ranges that wrap New Year."""
    if start_month is None or end_month is None:
        return True
    start, end = int(start_month), int(end_month)
    m = int(month)
    if start <= end:
        return start <= m <= end
    return m >= start or m <= end


def district_from_nominatim_address(address: Mapping[str, Any] | None) -> str | None:
    """Prefer administrative district over micro-area labels (EDGE-002: report leftovers)."""
    if not address:
        return None
    for key in ("city_district", "suburb", "quarter", "neighbourhood"):
        val = str(address.get(key) or "").strip()
        if val:
            return val
    return None


def nominatim_result_matches_city(address: Mapping[str, Any] | None, city_name: str) -> bool:
    """True when reverse geocode looks like the arena's city, or when Nominatim omitted city."""
    expected = (city_name or "").strip().lower()
    if not address or not expected:
        return True
    candidates = [
        str(address.get(key) or "").strip().lower()
        for key in ("city", "town", "village", "municipality")
    ]
    candidates = [c for c in candidates if c]
    if not candidates:
        return True
    return any(expected in c or c in expected for c in candidates)


def serialize_arena_list_item(
    arena: Mapping[str, Any],
    *,
    district: str | None = None,
    slug: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Public/admin list row. ``district=None`` is a present field, not a reason to drop the row."""
    out = dict(arena)
    out["district"] = district
    if slug is not None:
        out["slug"] = slug
    if status is not None:
        out["status"] = status
    return out


async def slugs_taken_in_city(
    session: AsyncSession, city_id: int, *, exclude_arena_id: int | None = None
) -> set[str]:
    r = await session.execute(
        text(
            """
            SELECT slug FROM arena_profiles
            WHERE city_id = :cid
              AND (CAST(:exclude_id AS INTEGER) IS NULL OR arena_id <> CAST(:exclude_id AS INTEGER))
            """
        ),
        {"cid": city_id, "exclude_id": exclude_arena_id},
    )
    return {str(row[0]) for row in r.fetchall() if row[0]}


async def allocate_arena_slug(
    session: AsyncSession,
    *,
    city_id: int,
    name: str,
    arena_id: int,
    district: str | None = None,
    existing_slug: str | None = None,
) -> str:
    """Return the already-issued slug, or a new unique-in-city slug. Never rewrites existing."""
    current = (existing_slug or "").strip()
    if current:
        return current
    taken = await slugs_taken_in_city(session, city_id, exclude_arena_id=arena_id)
    return choose_arena_slug(
        slugify_arena_name(name), taken=taken, district=district, arena_id=arena_id
    )


async def ensure_arena_profile(
    session: AsyncSession,
    arena_id: int,
    *,
    city_id: int,
    name: str,
    district: str | None = None,
    status: str = ARENA_PROFILE_STATUS_PUBLISHED,
) -> str:
    """Insert a profile if missing; return the (stable) slug. Does not overwrite an existing slug."""
    existing = (
        await session.execute(
            text("SELECT slug FROM arena_profiles WHERE arena_id = :id"),
            {"id": arena_id},
        )
    ).fetchone()
    if existing and existing[0]:
        return str(existing[0])
    status = validate_profile_status(status)
    if status == ARENA_PROFILE_STATUS_PUBLISHED and PUBLISH_BLOCKER_TEST_NAME in (
        await load_arena_publish_blockers(session, arena_id)
    ):
        # TASK-177: a «Тестовая арена» starts as a draft; publishing it later goes through
        # apply_admin_arena_profile_patch / approve_arena, which re-check every blocker.
        # Missing coordinates alone do NOT draft here: a rink without coords stays in its
        # city list by design (public list AC-001); only explicit publish refuses it.
        status = ARENA_PROFILE_STATUS_DRAFT
    slug = await allocate_arena_slug(
        session,
        city_id=city_id,
        name=name,
        arena_id=arena_id,
        district=district,
        existing_slug=None,
    )
    await session.execute(
        text(
            """
            INSERT INTO arena_profiles (arena_id, city_id, slug, district, status, amenities, social_urls)
            VALUES (:arena_id, :city_id, :slug, :district, :status, '{}'::jsonb, '{}'::jsonb)
            ON CONFLICT (arena_id) DO NOTHING
            """
        ),
        {
            "arena_id": arena_id,
            "city_id": city_id,
            "slug": slug,
            "district": (district or "").strip() or None,
            "status": status,
        },
    )
    return slug


async def backfill_arena_profiles(session: AsyncSession) -> dict[str, int]:
    """
    Create missing profiles and fill empty slugs for active arenas.
    Already-issued slugs are left untouched (AC-001 idempotent).
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT a.id, a.city_id, a.name, a.is_active, p.slug, p.district
                FROM arenas a
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                WHERE a.is_active
                ORDER BY a.id
                """
            )
        )
    ).fetchall()
    created = 0
    filled = 0
    for arena_id, city_id, name, _is_active, slug, district in rows:
        if slug:
            continue
        before = (
            await session.execute(
                text("SELECT 1 FROM arena_profiles WHERE arena_id = :id"),
                {"id": arena_id},
            )
        ).fetchone()
        await ensure_arena_profile(
            session,
            int(arena_id),
            city_id=int(city_id),
            name=str(name or ""),
            district=str(district) if district else None,
        )
        if before:
            filled += 1
        else:
            created += 1
    return {"created": created, "filled": filled, "active": len(rows)}


def _optional_month(value: Any) -> int | None:
    if value is None or value == "":
        return None
    month = int(value)
    if month < 1 or month > 12:
        raise ValueError("season month must be 1–12")
    return month


_PROFILE_STRING_FIELDS = (
    "phone",
    "website_url",
    "short_description",
    "district",
    "timezone",
)


async def apply_admin_arena_profile_patch(
    session: AsyncSession,
    arena_id: int,
    fields: Mapping[str, Any],
) -> None:
    """Upsert vitrine fields. Unknown amenity keys raise InvalidAmenitiesError."""
    arena = (
        await session.execute(
            text("SELECT id, city_id, name, venue_type FROM arenas WHERE id = :id"),
            {"id": arena_id},
        )
    ).fetchone()
    if arena is None:
        raise LookupError("Arena not found")
    _arena_id, city_id, name = int(arena[0]), int(arena[1]), str(arena[2] or "")
    venue_type = str(arena[3] or "")
    await ensure_arena_profile(session, _arena_id, city_id=city_id, name=name)

    assignments: list[str] = []
    params: dict[str, Any] = {"id": _arena_id}
    if "city_id" in fields and fields["city_id"] is not None:
        assignments.append("city_id = :city_id")
        params["city_id"] = int(fields["city_id"])
    for key in _PROFILE_STRING_FIELDS:
        if key not in fields:
            continue
        raw = fields[key]
        assignments.append(f"{key} = :{key}")
        params[key] = (str(raw).strip() or None) if raw is not None else None
    if "social_urls" in fields:
        val = fields["social_urls"]
        if val is not None and not isinstance(val, dict):
            raise ValueError("social_urls must be an object")
        assignments.append("social_urls = CAST(:social_urls AS jsonb)")
        params["social_urls"] = json.dumps(val if isinstance(val, dict) else {})
    if "opening_hours" in fields:
        val = fields["opening_hours"]
        if val is not None and not isinstance(val, dict):
            raise ValueError("opening_hours must be an object")
        assignments.append("opening_hours = CAST(:opening_hours AS jsonb)")
        params["opening_hours"] = json.dumps(val) if val is not None else None
    if "season_start_month" in fields:
        assignments.append("season_start_month = :season_start_month")
        params["season_start_month"] = _optional_month(fields["season_start_month"])
    if "season_end_month" in fields:
        assignments.append("season_end_month = :season_end_month")
        params["season_end_month"] = _optional_month(fields["season_end_month"])
    if "amenities" in fields:
        amenities = validate_amenities(fields["amenities"], venue_type)
        assignments.append("amenities = CAST(:amenities AS jsonb)")
        params["amenities"] = json.dumps(amenities)
    if "status" in fields and fields["status"] is not None:
        new_status = validate_profile_status(str(fields["status"]))
        current_status = (
            await session.execute(
                text("SELECT status FROM arena_profiles WHERE arena_id = :id"), {"id": _arena_id}
            )
        ).scalar()
        # Only the transition into «published» is guarded: re-saving an already published
        # card (admin form, shop re-import) must not start failing on legacy rows.
        if new_status == ARENA_PROFILE_STATUS_PUBLISHED and current_status != new_status:
            blockers = await load_arena_publish_blockers(session, _arena_id)
            if blockers:
                raise ArenaNotPublishableError(
                    "arena cannot be published: " + ", ".join(blockers)
                )
        assignments.append("status = :status")
        params["status"] = new_status
    if "tickets_url" in fields:
        raw = fields["tickets_url"]
        if raw is None or str(raw).strip() == "":
            assignments.append("tickets_url = :tickets_url")
            params["tickets_url"] = None
        else:
            url = public_http_url(raw)
            if not url:
                raise ValueError("tickets_url must be an http(s) URL")
            assignments.append("tickets_url = :tickets_url")
            params["tickets_url"] = url
    schedule_keys = {"schedule_mode", "reopen_date", "schedule_mode_note"}
    schedule_reopened = False
    if schedule_keys & fields.keys():
        row = (
            await session.execute(
                text(
                    """
                    SELECT schedule_mode, reopen_date, schedule_mode_note
                    FROM arena_profiles WHERE arena_id = :id
                    """
                ),
                {"id": _arena_id},
            )
        ).mappings().first()
        previous_mode = normalize_schedule_mode((row or {}).get("schedule_mode"))
        merged = {
            "schedule_mode": previous_mode,
            "reopen_date": (row or {}).get("reopen_date"),
            "schedule_mode_note": (row or {}).get("schedule_mode_note"),
        }
        for key in schedule_keys:
            if key in fields:
                merged[key] = fields[key]
        validated = validate_schedule_mode_patch(merged)
        mode = validated.get("schedule_mode", merged["schedule_mode"])
        if "schedule_mode" in fields:
            assignments.append("schedule_mode = :schedule_mode")
            params["schedule_mode"] = mode
        if mode == SCHEDULE_MODE_SEASON_CLOSED:
            if "reopen_date" in fields:
                assignments.append("reopen_date = :reopen_date")
                params["reopen_date"] = validated.get("reopen_date")
            if "schedule_mode_note" in fields:
                assignments.append("schedule_mode_note = :schedule_mode_note")
                params["schedule_mode_note"] = validated.get("schedule_mode_note")
        elif "schedule_mode" in fields:
            assignments.append("reopen_date = NULL")
            assignments.append("schedule_mode_note = NULL")
    if (
        "schedule_mode" in fields
        and previous_mode == SCHEDULE_MODE_SEASON_CLOSED
        and mode == SCHEDULE_MODE_AUTO
    ):
        schedule_reopened = True
    if schedule_reopened:
        from src.application.arena_follow_notify import enqueue_arena_reopened

        await enqueue_arena_reopened(session, _arena_id)
    if not assignments:
        return
    assignments.append("updated_at = now()")
    await session.execute(
        text("UPDATE arena_profiles SET " + ", ".join(assignments) + " WHERE arena_id = :id"),
        params,
    )


async def touch_arena_profile(session: AsyncSession, arena_id: int) -> None:
    """Правка самой арены (имя, адрес, тип) — тоже правка карточки для «обновлено N назад»."""
    await session.execute(
        text("UPDATE arena_profiles SET updated_at = now() WHERE arena_id = :id"), {"id": int(arena_id)}
    )


# ---------------------------------------------------------------------------
# Часы работы (TASK-146). Форматы в opening_hours:
#   {"daily": {"open": "10:00", "close": "20:00"}} — каждый день одинаково;
#   {"weekly": {"mon": ["10:00", "19:00"], ...}}   — один интервал в день;
#   {"weekly": {"mon": [["11:00","15:00"],["19:00","22:00"]], ...}} — несколько окон (лыжероллерная).
#   Опционально: rental_close, access_note, free_entry (bool) — для карточки, не schema.org.
# ---------------------------------------------------------------------------

WEEKDAY_KEYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_SHORT_RU: tuple[str, ...] = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def normalize_hhmm(raw: Any) -> str:
    """«7:00» / «07.00» / «7» → «07:00». Непонятное — пустая строка.

    Часы вводят руками; сравнивать «7:00» и «10:00» строками нельзя — «7:00»
    окажется позже, и магазин «закроется» с утра.
    """
    text_value = str(raw or "").strip().replace(".", ":")
    if not text_value:
        return ""
    head, _, tail = text_value.partition(":")
    if not head.isdigit() or (tail and not tail.isdigit()):
        return ""
    h, m = int(head), int(tail or 0)
    if not (0 <= h <= 24 and 0 <= m < 60):
        return ""
    return f"{h:02d}:{m:02d}"


def _parse_day_intervals(raw: Any) -> list[tuple[str, str]]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], (list, tuple)):
        out: list[tuple[str, str]] = []
        for seg in raw:
            if isinstance(seg, (list, tuple)) and len(seg) == 2:
                o, c = normalize_hhmm(seg[0]), normalize_hhmm(seg[1])
                if o and c:
                    out.append((o, c))
        return out
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        o, c = normalize_hhmm(raw[0]), normalize_hhmm(raw[1])
        return [(o, c)] if o and c else []
    return []


def intervals_for_weekday(opening_hours: Mapping[str, Any] | None, weekday: int) -> list[tuple[str, str]]:
    """Интервалы массового доступа на день (0 = понедельник). Пусто — выходной."""
    hours = opening_hours if isinstance(opening_hours, Mapping) else {}
    weekly = hours.get("weekly")
    if isinstance(weekly, Mapping):
        return _parse_day_intervals(weekly.get(WEEKDAY_KEYS[weekday % 7]))
    daily = hours.get("daily")
    if isinstance(daily, Mapping):
        o, c = normalize_hhmm(daily.get("open")), normalize_hhmm(daily.get("close"))
        return [(o, c)] if o and c else []
    return []


def format_intervals_ru(intervals: Sequence[tuple[str, str]]) -> str:
    return " и ".join(f"{a}–{b}" for a, b in intervals)


def hours_for_weekday(opening_hours: Mapping[str, Any] | None, weekday: int) -> tuple[str, str] | None:
    """Первый интервал дня — для обратной совместимости и schema.org."""
    intervals = intervals_for_weekday(opening_hours, weekday)
    return intervals[0] if intervals else None


def has_known_hours(opening_hours: Mapping[str, Any] | None) -> bool:
    return any(intervals_for_weekday(opening_hours, d) for d in range(7))


def _day_hours_signature(opening_hours: Mapping[str, Any] | None, weekday: int) -> str | None:
    intervals = intervals_for_weekday(opening_hours, weekday)
    return format_intervals_ru(intervals) if intervals else None


def hours_groups(opening_hours: Mapping[str, Any] | None) -> list[tuple[str, tuple[str, str] | None]]:
    """Соседние дни с одинаковыми часами — одной строкой: [("Пн–Пт", ("10:00","19:00")), ("Вс", None)]."""
    if not has_known_hours(opening_hours):
        return []
    sigs = [_day_hours_signature(opening_hours, d) for d in range(7)]
    if all(s == sigs[0] for s in sigs):
        intervals = intervals_for_weekday(opening_hours, 0)
        return [("Ежедневно", intervals[0] if len(intervals) == 1 else None)]
    groups: list[tuple[str, tuple[str, str] | None]] = []
    start = 0
    for i in range(1, 8):
        if i == 7 or sigs[i] != sigs[start]:
            label = WEEKDAY_SHORT_RU[start] if i - 1 == start else f"{WEEKDAY_SHORT_RU[start]}–{WEEKDAY_SHORT_RU[i - 1]}"
            first = intervals_for_weekday(opening_hours, start)
            pair: tuple[str, str] | None = first[0] if len(first) == 1 else None
            groups.append((label, pair))
            start = i
    return groups


def opening_hours_schema_org(opening_hours: Mapping[str, Any] | None) -> list[str]:
    """«Mo-Fr 10:00-19:00» — для schema.org openingHours."""
    codes = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
    out: list[str] = []
    days = [hours_for_weekday(opening_hours, d) for d in range(7)]
    start = 0
    for i in range(1, 8):
        if i == 7 or days[i] != days[start]:
            if days[start]:
                span = codes[start] if i - 1 == start else f"{codes[start]}-{codes[i - 1]}"
                out.append(f"{span} {days[start][0]}-{days[start][1]}")
            start = i
    return out
