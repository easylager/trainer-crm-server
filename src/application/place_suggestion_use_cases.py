"""
User-submitted places (PDEC-028): the raw suggestion lives in ``place_suggestions`` and
never touches the catalog until an admin approves it.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_profile import ensure_arena_profile, normalize_hhmm, public_http_url
from src.application.catalog_consumer_events import hmac_actor
from src.application.place_links import place_path
from src.application.place_suggestion_notify import notify_admins_new_place_suggestion
from src.application.trainer_arena_create_use_cases import find_possible_duplicate_arenas
from src.application.trainer_city_create_use_cases import find_city_by_name_insensitive
from src.shared.currency import resolve_currency
from src.shared.place_suggestion import (
    PlaceSuggestionError,
    classify_contact,
    normalize_details,
    validate_core,
)

logger = logging.getLogger(__name__)

SOURCES = ("site", "miniapp")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _clean(value: Any, limit: int) -> str | None:
    s = re.sub(r"\s+", " ", str(value or "")).strip()[:limit]
    return s or None


def _coord(value: Any, bound: float) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if -bound <= v <= bound else None


def client_ip_hash(client_ip: str | None) -> str | None:
    """HMAC(IP) на ``CATALOG_ACTOR_HMAC_SECRET``; без секрета — ``None`` (сам IP не храним)."""
    ip = (client_ip or "").strip()
    if not ip:
        return None
    return hmac_actor("suggest-ip", ip)


async def create_place_suggestion(
    session: AsyncSession,
    *,
    source: str,
    kind: str,
    city_id: int | None,
    new_city: Mapping[str, Any] | None,
    name: str,
    address: str | None,
    details: Mapping[str, Any] | None,
    contact: str | None,
    author_telegram_id: int | None,
    client_ip: str | None,
) -> dict[str, Any]:
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")
    new_city = new_city or {}
    new_city_name, nm = validate_core(
        kind=kind, city_id=city_id, new_city_name=new_city.get("name"), name=name
    )
    clean_details = normalize_details(kind, dict(details or {}))
    contact_value, contact_kind = classify_contact(contact)

    new_country = new_region = None
    new_lat = new_lon = None
    if city_id is not None:
        ok = (await session.execute(text("SELECT 1 FROM cities WHERE id = :id"), {"id": int(city_id)})).fetchone()
        if not ok:
            raise PlaceSuggestionError("Город не найден.")
        new_city_name = None
    else:
        # Проверяем страну целиком, до обрезки: «RUS» — это ошибка, а не «RU».
        country = re.sub(r"\s+", "", str(new_city.get("country") or "")).upper()
        if not _COUNTRY_RE.match(country):
            raise PlaceSuggestionError("Укажите страну города.")
        # Одноимённые города бывают в разных странах (Пушкино и т. п.) — совпадение только с той же страной.
        existing = await find_city_by_name_insensitive(session, new_city_name or "", country=country)
        if existing:
            city_id = int(existing["id"])
            new_city_name = None
        else:
            new_country = country
            new_region = _clean(new_city.get("region"), 160)
            new_lat = _coord(new_city.get("lat"), 90)
            new_lon = _coord(new_city.get("lon"), 180)

    bind_token = secrets.token_urlsafe(12) if author_telegram_id is None else None

    r = await session.execute(
        text(
            """
            INSERT INTO place_suggestions (
                kind, source, city_id, new_city_name, new_city_country, new_city_region,
                new_city_lat, new_city_lon, name, address, details, contact, contact_kind,
                author_telegram_id, bind_token, client_ip_hash
            ) VALUES (
                :kind, :source, :city_id, :new_city_name, :new_city_country, :new_city_region,
                :new_city_lat, :new_city_lon, :name, :address, CAST(:details AS jsonb), :contact,
                :contact_kind, :author, :bind_token, :ip_hash
            )
            RETURNING id
            """
        ),
        {
            "kind": kind,
            "source": source,
            "city_id": city_id,
            "new_city_name": new_city_name,
            "new_city_country": new_country,
            "new_city_region": new_region,
            "new_city_lat": new_lat,
            "new_city_lon": new_lon,
            "name": nm,
            "address": _clean(address, 300),
            "details": json.dumps(clean_details, ensure_ascii=False),
            "contact": contact_value,
            "contact_kind": contact_kind,
            "author": int(author_telegram_id) if author_telegram_id is not None else None,
            "bind_token": bind_token,
            "ip_hash": client_ip_hash(client_ip),
        },
    )
    sid = int(r.scalar_one())
    await session.commit()

    try:
        await notify_admins_new_place_suggestion(sid)
    except Exception:  # noqa: BLE001
        logger.exception("notify admins after place suggestion failed suggestion_id=%s", sid)

    return {"id": sid, "bind_token": bind_token}


# ---------------------------------------------------------------------------
# Модерация (админка). Закрытые статусы — approved | rejected | duplicate.
# ---------------------------------------------------------------------------

OPEN_STATUSES = ("new", "needs_info")
TABS = {"new": ("new",), "waiting": ("needs_info",), "closed": ("approved", "rejected", "duplicate")}
REJECT_REASONS = ("spam", "not_ice", "closed", "other")
DUPLICATE_COPY_FIELDS = ("phone", "website_url", "visitor_prices", "opening_hours")
_PATCH_KEYS = (
    "name", "address", "latitude", "longitude", "details", "city_id",
    "new_city_name", "new_city_country", "new_city_region", "new_city_lat", "new_city_lon",
)
_PRICE_FIELDS = (("price_adult", "adult"), ("price_child", "child"), ("price_rental", "rental"))
_DAILY_HOURS_RE = re.compile(
    r"^(?:(?:ежедневно|каждый день)[\s,:]*)?(?:с\s*)?"
    r"(\d{1,2}(?:[:.]\d{2})?)\s*(?:[-–—]|до)\s*(\d{1,2}(?:[:.]\d{2})?)$",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"^\+?[\d\s()\-]+$")
_BARE_DOMAIN_RE = re.compile(r"^(?:www\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?:/\S*)?$")


class PlaceSuggestionAdminError(ValueError):
    """Отказ модерации; ``code`` стабилен для API (not_found | closed | invalid | arena_not_found)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def daily_hours_from_text(raw: str | None) -> dict[str, Any] | None:
    """«10:00–22:00» / «ежедневно с 9 до 21» → ``{"daily": {...}}``; всё прочее — ``None``.

    Форма админки понимает только daily-формат и затирает остальное, поэтому часы
    попадают в ``opening_hours`` лишь когда их можно записать так без потерь.
    """
    m = _DAILY_HOURS_RE.match(re.sub(r"\s+", " ", str(raw or "")).strip())
    if not m:
        return None
    open_, close = normalize_hhmm(m.group(1)), normalize_hhmm(m.group(2))
    if not open_ or not close:
        return None
    return {"daily": {"open": open_, "close": close}}


def link_profile_fields(raw: str | None) -> dict[str, str]:
    """Ссылка из заявки: URL → ``website_url``, похожее на телефон → ``phone``, иначе ничего."""
    value = str(raw or "").strip()
    if not value:
        return {}
    url = public_http_url(value)
    if url:
        return {"website_url": url}
    if _BARE_DOMAIN_RE.match(value):
        url = public_http_url(f"https://{value}")
        return {"website_url": url} if url else {}
    digits = sum(ch.isdigit() for ch in value)
    if _PHONE_RE.match(value) and 7 <= digits <= 15 and len(value) <= 32:
        return {"phone": value}
    return {}


def visitor_prices_from_details(details: Mapping[str, Any], currency: str) -> dict[str, str] | None:
    out = {key: str(details[src]) for src, key in _PRICE_FIELDS if details.get(src)}
    if not out:
        return None
    return {**out, "currency": currency, "source": "visitors"}


async def _profile_fields_from_details(
    session: AsyncSession, details: Mapping[str, Any], city_id: int
) -> dict[str, Any]:
    """Кандидаты в поля профиля: phone, website_url, visitor_prices, opening_hours."""
    fields: dict[str, Any] = dict(link_profile_fields(details.get("link")))
    prices = visitor_prices_from_details(details, await resolve_currency(session, city_id))
    if prices:
        fields["visitor_prices"] = prices
    hours = daily_hours_from_text(details.get("hours"))
    if hours:
        fields["opening_hours"] = hours
    return fields


async def _load_row(session: AsyncSession, sid: int, *, for_update: bool = False) -> dict[str, Any]:
    r = await session.execute(
        text(
            """
            SELECT s.id, s.kind, s.status, s.source, s.city_id, c.name AS city_name,
                   c.is_active AS city_is_active, c.country AS city_country,
                   s.new_city_name, s.new_city_country, s.new_city_region, s.new_city_lat, s.new_city_lon,
                   s.name, s.address, s.latitude, s.longitude, s.details, s.contact, s.contact_kind,
                   s.author_telegram_id, s.target_arena_id, s.result_arena_id, s.reject_reason,
                   s.created_at, s.updated_at, s.closed_at
            FROM place_suggestions s
            LEFT JOIN cities c ON c.id = s.city_id
            WHERE s.id = :id
            """
            + (" FOR UPDATE OF s" if for_update else "")
        ),
        {"id": int(sid)},
    )
    row = r.mappings().first()
    if not row:
        raise PlaceSuggestionAdminError("not_found", "Заявка не найдена.")
    out = dict(row)
    out["details"] = dict(out.get("details") or {})
    return out


def _require_open(row: Mapping[str, Any]) -> None:
    if row["status"] not in OPEN_STATUSES:
        raise PlaceSuggestionAdminError("closed", "Заявка уже закрыта.")


async def list_place_suggestions(session: AsyncSession, *, tab: str, limit: int = 50) -> list[dict[str, Any]]:
    statuses = TABS.get(tab)
    if statuses is None:
        raise PlaceSuggestionAdminError("invalid", "Неизвестная вкладка.")
    r = await session.execute(
        text(
            """
            SELECT s.id, s.kind, s.status, s.name, COALESCE(c.name, s.new_city_name) AS city_label,
                   s.city_id IS NULL AS is_new_city,
                   (s.contact IS NOT NULL OR s.author_telegram_id IS NOT NULL) AS has_contact,
                   s.created_at
            FROM place_suggestions s
            LEFT JOIN cities c ON c.id = s.city_id
            WHERE s.status = ANY(:statuses)
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT :limit
            """
        ),
        {"statuses": list(statuses), "limit": max(1, min(int(limit), 200))},
    )
    return [dict(m) for m in r.mappings().all()]


async def get_place_suggestion(session: AsyncSession, sid: int) -> dict[str, Any]:
    out = await _load_row(session, sid)
    msgs = await session.execute(
        text(
            "SELECT id, direction, body, created_at FROM place_suggestion_messages "
            "WHERE suggestion_id = :id ORDER BY created_at, id"
        ),
        {"id": int(sid)},
    )
    out["messages"] = [dict(m) for m in msgs.mappings().all()]
    out["similar"] = (
        await find_possible_duplicate_arenas(
            session, int(out["city_id"]), name=out["name"],
            latitude=out["latitude"], longitude=out["longitude"],
        )
        if out["city_id"] is not None
        else []
    )
    return out


def _patch_value(key: str, value: Any, kind: str) -> Any:
    if key == "name":
        nm = _clean(value, 200)
        if not nm:
            raise PlaceSuggestionAdminError("invalid", "Название не может быть пустым.")
        return nm
    if key == "address":
        return _clean(value, 300)
    if key == "new_city_name":
        return _clean(value, 120)
    if key == "new_city_region":
        return _clean(value, 160)
    if key == "new_city_country":
        if value is None or value == "":
            return None
        country = re.sub(r"\s+", "", str(value)).upper()
        if not _COUNTRY_RE.match(country):
            raise PlaceSuggestionAdminError("invalid", "Страна — двухбуквенный код (BY, RU).")
        return country
    if key in ("latitude", "longitude", "new_city_lat", "new_city_lon"):
        if value is None or value == "":
            return None
        v = _coord(value, 90 if key in ("latitude", "new_city_lat") else 180)
        if v is None:
            raise PlaceSuggestionAdminError("invalid", "Неверные координаты.")
        return v
    if key == "details":
        if not isinstance(value, Mapping):
            raise PlaceSuggestionAdminError("invalid", "details — объект.")
        return json.dumps(normalize_details(kind, dict(value)), ensure_ascii=False)
    if key == "city_id":
        return int(value) if value is not None else None
    raise KeyError(key)


async def patch_place_suggestion(session: AsyncSession, sid: int, fields: Mapping[str, Any]) -> dict[str, Any]:
    row = await _load_row(session, sid, for_update=True)
    _require_open(row)
    values = {k: _patch_value(k, fields[k], row["kind"]) for k in _PATCH_KEYS if k in fields}
    if values.get("city_id") is not None:
        ok = (await session.execute(text("SELECT 1 FROM cities WHERE id = :id"), {"id": values["city_id"]})).first()
        if not ok:
            raise PlaceSuggestionAdminError("invalid", "Город не найден.")
    city_id = values.get("city_id", row["city_id"])
    new_city_name = values.get("new_city_name", row["new_city_name"])
    if city_id is None and not new_city_name:
        raise PlaceSuggestionAdminError("invalid", "Укажите город.")
    if values:
        assignments = ", ".join(
            f"{k} = CAST(:{k} AS jsonb)" if k == "details" else f"{k} = :{k}" for k in values
        )
        await session.execute(
            text(f"UPDATE place_suggestions SET {assignments}, updated_at = now() WHERE id = :sid"),
            {**values, "sid": int(sid)},
        )
        await session.commit()
    return await get_place_suggestion(session, sid)


async def reject_place_suggestion(session: AsyncSession, sid: int, reason: str) -> None:
    if reason not in REJECT_REASONS:
        raise PlaceSuggestionAdminError("invalid", "Неизвестная причина отказа.")
    row = await _load_row(session, sid, for_update=True)
    _require_open(row)
    await session.execute(
        text(
            "UPDATE place_suggestions SET status = 'rejected', reject_reason = :reason, "
            "closed_at = now(), updated_at = now() WHERE id = :sid"
        ),
        {"reason": reason, "sid": int(sid)},
    )
    await session.commit()


async def mark_duplicate(
    session: AsyncSession, sid: int, target_arena_id: int, copy_fields: list[str] | tuple[str, ...]
) -> None:
    """Закрыть как дубль; выбранные поля копируются только в пустые поля профиля цели."""
    unknown = set(copy_fields) - set(DUPLICATE_COPY_FIELDS)
    if unknown:
        raise PlaceSuggestionAdminError("invalid", f"Нельзя скопировать: {', '.join(sorted(unknown))}.")
    row = await _load_row(session, sid, for_update=True)
    _require_open(row)
    target = (
        await session.execute(
            text("SELECT id, city_id, name FROM arenas WHERE id = :id"), {"id": int(target_arena_id)}
        )
    ).first()
    if not target:
        raise PlaceSuggestionAdminError("arena_not_found", "Место не найдено.")
    candidates = await _profile_fields_from_details(session, row["details"], int(target[1]))
    picked = {k: v for k, v in candidates.items() if k in copy_fields}
    if picked:
        await ensure_arena_profile(session, int(target[0]), city_id=int(target[1]), name=str(target[2]))
        for key, value in picked.items():
            is_json = key in ("visitor_prices", "opening_hours")
            await session.execute(
                text(
                    f"UPDATE arena_profiles SET {key} = "
                    + ("CAST(:v AS jsonb)" if is_json else ":v")
                    + f", updated_at = now() WHERE arena_id = :a AND ({key} IS NULL"
                    + (f" OR {key} = 'null'::jsonb OR {key} = '{{}}'::jsonb)" if is_json else f" OR btrim({key}) = '')")
                ),
                {"v": json.dumps(value, ensure_ascii=False) if is_json else value, "a": int(target[0])},
            )
    await session.execute(
        text(
            "UPDATE place_suggestions SET status = 'duplicate', target_arena_id = :t, "
            "closed_at = now(), updated_at = now() WHERE id = :sid"
        ),
        {"t": int(target[0]), "sid": int(sid)},
    )
    await session.commit()


#: Услуги магазина из заявки → ключи ``arena_profiles.amenities`` (SHOP_AMENITY_KEYS).
_SHOP_SERVICE_AMENITY = {"sharpening": "skate_sharpening", "rental": "skate_rental", "sale": "retail"}
_PRICE_GROUP_BY_COUNTRY = {"RU": "RU_BASE"}
_ARENA_NAME_MAX = 128


async def notify_author_approved(sid: int) -> None:
    """Сообщить автору, что место появилось в каталоге. Заглушка: доставку делает Task 11."""
    del sid


async def _resolve_city_for_approve(session: AsyncSession, row: Mapping[str, Any]) -> tuple[int, str, bool]:
    """(city_id, city_name, kept_inactive). Существующий скрытый город не включаем (PDEC-018)."""
    if row["city_id"] is not None:
        return int(row["city_id"]), str(row["city_name"]), not bool(row["city_is_active"])
    name = _clean(row["new_city_name"], 120)
    country = row["new_city_country"]
    if not name or not country:
        raise PlaceSuggestionAdminError("invalid", "Укажите город и страну.")
    existing = await find_city_by_name_insensitive(session, name, country=country)
    if existing:
        return int(existing["id"]), str(existing["name"]), not existing["is_active"]
    r = await session.execute(
        text(
            """
            INSERT INTO cities (name, sort_order, is_active, country, price_group, latitude, longitude, region)
            VALUES (:name, 9999, true, :country, :pg, :lat, :lon, :region)
            RETURNING id
            """
        ),
        {
            "name": name,
            "country": country,
            "pg": _PRICE_GROUP_BY_COUNTRY.get(country, "BY_BASE"),
            "lat": row["new_city_lat"],
            "lon": row["new_city_lon"],
            "region": row["new_city_region"],
        },
    )
    return int(r.scalar_one()), name, False


async def approve_place_suggestion(session: AsyncSession, sid: int, *, admin_id: int) -> dict[str, Any]:
    """Заявка → город (если новый), подтверждённое место и опубликованная карточка; одна транзакция.

    Часы пишутся в ``opening_hours`` только в daily-формате (см. ``daily_hours_from_text``);
    остальное остаётся в заявке. Свежее место без парсера — ``schedule_mode='phone'``.
    """
    try:
        row = await _load_row(session, sid, for_update=True)
        _require_open(row)
        city_id, city_name, kept_inactive = await _resolve_city_for_approve(session, row)
        name = row["name"][:_ARENA_NAME_MAX].strip()
        r = await session.execute(
            text(
                """
                INSERT INTO arenas (city_id, name, address, latitude, longitude, venue_type,
                                    is_active, is_confirmed, confirmed_at, confirmed_by_admin_id)
                VALUES (:city_id, :name, :address, :lat, :lon, :venue_type, true, true, now(), :admin_id)
                RETURNING id
                """
            ),
            {
                "city_id": city_id,
                "name": name,
                "address": row["address"],
                "lat": row["latitude"],
                "lon": row["longitude"],
                "venue_type": row["kind"],
                "admin_id": int(admin_id),
            },
        )
        arena_id = int(r.scalar_one())
        slug = await ensure_arena_profile(session, arena_id, city_id=city_id, name=name)

        fields = await _profile_fields_from_details(session, row["details"], city_id)
        if row["kind"] == "shop":
            amenities = {
                _SHOP_SERVICE_AMENITY[s]: True for s in row["details"].get("services") or []
                if s in _SHOP_SERVICE_AMENITY
            }
            if amenities:
                fields["amenities"] = amenities
        fields["schedule_mode"] = "phone"
        json_keys = {"visitor_prices", "opening_hours", "amenities"}
        assignments = ", ".join(
            f"{k} = CAST(:{k} AS jsonb)" if k in json_keys else f"{k} = :{k}" for k in fields
        )
        await session.execute(
            text(f"UPDATE arena_profiles SET {assignments}, updated_at = now() WHERE arena_id = :arena_id"),
            {
                **{k: json.dumps(v, ensure_ascii=False) if k in json_keys else v for k, v in fields.items()},
                "arena_id": arena_id,
            },
        )
        await session.execute(
            text(
                "UPDATE place_suggestions SET status = 'approved', result_arena_id = :a, city_id = :c, "
                "closed_at = now(), updated_at = now() WHERE id = :sid"
            ),
            {"a": arena_id, "c": city_id, "sid": int(sid)},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    try:
        await notify_author_approved(int(sid))
    except Exception:  # noqa: BLE001
        logger.exception("notify author after place suggestion approve failed suggestion_id=%s", sid)

    return {
        "arena_id": arena_id,
        "city_id": city_id,
        "slug": slug,
        "url": place_path(city_name=city_name, slug=slug),
        "city_kept_inactive": kept_inactive,
    }
