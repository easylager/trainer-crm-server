"""Upsert weekend/CMS ice sessions as ``source_id=admin``, ``schedule_basis=manual``.

No wipe of siblings: weekday live cashier rows stay. When the arena parser later
emits the same ``(starts_at_utc, kind)``, ``SqlAlchemyIceSessionPublisher`` adopts
the admin row (live basis + external_url) without changing ``source_id``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_session_use_cases import (
    KIND_PUBLIC_SKATE,
    SOURCE_ADMIN,
    STATUS_ACTIVE,
    compute_price_minor,
    compute_session_datetimes,
    parse_hhmm,
    validate_duration_minutes,
    validate_kind,
    validate_prices,
)
from src.shared.currency import resolve_currency
from src.shared.schedule_basis import SCHEDULE_BASIS_MANUAL


class AnnouncedSpecError(ValueError):
    """Spec cannot become admin/manual sessions."""


def _money_to_minor(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    return int(round(float(str(value).strip().replace(",", ".")) * 100))


async def _arena_timezone(session: AsyncSession, arena_id: int) -> tuple[int, str]:
    result = await session.execute(
        text(
            """
            SELECT a.city_id, COALESCE(p.timezone, 'Europe/Minsk') AS tz
            FROM arenas a
            LEFT JOIN arena_profiles p ON p.arena_id = a.id
            WHERE a.id = :aid
            """
        ),
        {"aid": arena_id},
    )
    row = result.mappings().first()
    if row is None:
        raise AnnouncedSpecError(f"Арена {arena_id} не найдена")
    return int(row["city_id"]), str(row["tz"])


async def upsert_admin_announced_sessions(session: AsyncSession, spec: Mapping[str, Any]) -> dict[str, int]:
    """Insert/update admin+manual sessions. Never deletes other rows. external_url stays null."""
    try:
        arena_id = int(spec["arena_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AnnouncedSpecError("Нужен arena_id") from exc
    sessions = spec.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise AnnouncedSpecError("В расписании нет сеансов")

    defaults = spec.get("defaults") if isinstance(spec.get("defaults"), Mapping) else {}
    city_id, tz_name = await _arena_timezone(session, arena_id)
    currency_code = str(spec.get("currency_code") or await resolve_currency(session, city_id))
    now = datetime.now(timezone.utc)
    counts = {"inserted": 0, "updated": 0, "skipped_live": 0, "skipped_same": 0}

    for raw in sessions:
        if not isinstance(raw, Mapping):
            raise AnnouncedSpecError("Сеанс должен быть объектом")
        merged = {**defaults, **raw}
        for key in ("date", "start"):
            if not merged.get(key):
                raise AnnouncedSpecError(f"У сеанса нет поля {key}")
        kind = validate_kind(str(merged.get("kind") or KIND_PUBLIC_SKATE))
        minutes = validate_duration_minutes(int(merged.get("duration_minutes") or 45))
        adult = _money_to_minor(merged.get("price_adult"))
        child = _money_to_minor(merged.get("price_child"))
        rental = _money_to_minor(merged.get("price_rental"))
        validate_prices(price_adult_minor=adult, price_child_minor=child, price_rental_minor=rental)
        try:
            local_date = datetime.strptime(str(merged["date"]), "%Y-%m-%d").date()
        except ValueError as exc:
            raise AnnouncedSpecError(f"Неверная дата: {merged['date']!r}") from exc
        parts = compute_session_datetimes(
            local_date=local_date,
            starts_at_local=parse_hhmm(str(merged["start"])),
            duration_minutes=minutes,
            tz_name=tz_name,
        )
        hall = (str(merged["hall"]).strip() if merged.get("hall") else None) or None
        price_minor = compute_price_minor(adult, child, rental)

        existing = (
            await session.execute(
                text(
                    """
                    SELECT id, source_id, schedule_basis, external_url,
                           price_adult_minor, price_child_minor, price_rental_minor,
                           hall, ends_at_utc, status
                    FROM ice_sessions
                    WHERE arena_id = :aid AND starts_at_utc = :starts AND kind = :kind
                    ORDER BY id
                    LIMIT 1
                    """
                ),
                {"aid": arena_id, "starts": parts.starts_at_utc, "kind": kind},
            )
        ).mappings().first()

        if existing is not None and str(existing["source_id"] or "") != SOURCE_ADMIN:
            # Live/parser row already owns this key — do not downgrade to manual announce.
            counts["skipped_live"] += 1
            continue

        params = {
            "arena_id": arena_id,
            "kind": kind,
            "starts_at_utc": parts.starts_at_utc,
            "ends_at_utc": parts.ends_at_utc,
            "local_date": parts.local_date,
            "starts_at_local": parts.starts_at_local,
            "ends_at_local": parts.ends_at_local,
            "price_adult_minor": adult,
            "price_child_minor": child,
            "price_rental_minor": rental,
            "price_minor": price_minor,
            "currency_code": currency_code,
            "hall": hall,
            "external_url": None,
            "status": STATUS_ACTIVE,
            "source_id": SOURCE_ADMIN,
            "observed_at": now,
            "valid_until": parts.ends_at_utc,
            "schedule_basis": SCHEDULE_BASIS_MANUAL,
            "confidence": 1.0,
        }

        if existing is None:
            await session.execute(
                text(
                    """
                    INSERT INTO ice_sessions (
                        arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                        starts_at_local, ends_at_local,
                        price_adult_minor, price_child_minor, price_rental_minor, price_minor,
                        currency_code, hall, external_url, status,
                        source_id, observed_at, valid_until, schedule_basis, confidence
                    ) VALUES (
                        :arena_id, :kind, :starts_at_utc, :ends_at_utc, :local_date,
                        :starts_at_local, :ends_at_local,
                        :price_adult_minor, :price_child_minor, :price_rental_minor, :price_minor,
                        :currency_code, :hall, :external_url, :status,
                        :source_id, :observed_at, :valid_until, :schedule_basis, :confidence
                    )
                    """
                ),
                params,
            )
            counts["inserted"] += 1
            continue

        same = (
            existing["price_adult_minor"] == adult
            and existing["price_child_minor"] == child
            and existing["price_rental_minor"] == rental
            and (existing["hall"] or None) == hall
            and existing["ends_at_utc"] == parts.ends_at_utc
            and str(existing["schedule_basis"] or "") == SCHEDULE_BASIS_MANUAL
            and existing["external_url"] is None
            and str(existing["status"] or "") == STATUS_ACTIVE
        )
        if same:
            counts["skipped_same"] += 1
            continue

        params["id"] = int(existing["id"])
        await session.execute(
            text(
                """
                UPDATE ice_sessions SET
                    ends_at_utc = :ends_at_utc,
                    local_date = :local_date,
                    starts_at_local = :starts_at_local,
                    ends_at_local = :ends_at_local,
                    price_adult_minor = :price_adult_minor,
                    price_child_minor = :price_child_minor,
                    price_rental_minor = :price_rental_minor,
                    price_minor = :price_minor,
                    currency_code = :currency_code,
                    hall = :hall,
                    external_url = :external_url,
                    status = :status,
                    source_id = :source_id,
                    observed_at = :observed_at,
                    valid_until = :valid_until,
                    schedule_basis = :schedule_basis,
                    confidence = :confidence
                WHERE id = :id AND arena_id = :arena_id AND source_id = 'admin'
                """
            ),
            params,
        )
        counts["updated"] += 1

    return counts
