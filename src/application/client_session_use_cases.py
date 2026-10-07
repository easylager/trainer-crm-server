"""
Application layer: client bot session use cases. Get/update session state and choices.
"""
import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_time_windows import WHEN_KEYS
from src.infrastructure.repositories import ClientSessionRepository

_DAY_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


async def get_or_create_session(telegram_id: int, session: AsyncSession) -> dict[str, Any]:
    """Load session; if missing, create with state=idle and return."""
    repo = ClientSessionRepository(session)
    row = await repo.get(telegram_id)
    if row:
        return row
    await repo.upsert(telegram_id, state="idle")
    await session.commit()
    return {
        "telegram_id": telegram_id,
        "state": "idle",
        "city_id": None,
        "selected_service_id": None,
        "selected_trainer_id": None,
        "selected_arena_id": None,
        "payload": None,
        "updated_at": None,
    }


async def set_city(telegram_id: int, city_id: int, session: AsyncSession) -> None:
    """Set selected city; clear arena and trainer (they depend on city)."""
    repo = ClientSessionRepository(session)
    await repo.upsert(telegram_id, state="city_selected", city_id=city_id)
    await repo.clear_selected_arena(telegram_id)
    await repo.clear_selected_trainer(telegram_id)
    await session.commit()


async def set_arena(telegram_id: int, arena_id: int | None, session: AsyncSession) -> None:
    """Set selected arena (optional filter); clear trainer if setting to non-None."""
    repo = ClientSessionRepository(session)
    if arena_id is None:
        await repo.clear_selected_arena(telegram_id)
    else:
        await repo.upsert(telegram_id, selected_arena_id=arena_id)
        await repo.clear_selected_trainer(telegram_id)
    await session.commit()


async def set_service(telegram_id: int, service_id: int, session: AsyncSession) -> None:
    """Set selected service; clear trainer (trainer may not offer new service)."""
    repo = ClientSessionRepository(session)
    await repo.upsert(telegram_id, state="service_selected", selected_service_id=service_id)
    await repo.clear_selected_trainer(telegram_id)
    await session.commit()


async def clear_selected_service(telegram_id: int, session: AsyncSession) -> None:
    """Clear selected service when flow should start from service choice."""
    repo = ClientSessionRepository(session)
    await repo.clear_selected_service(telegram_id)
    await session.commit()


async def set_selected_trainer(
    telegram_id: int, trainer_id: int, session: AsyncSession
) -> None:
    """Set selected trainer and state to trainer_selected."""
    repo = ClientSessionRepository(session)
    await repo.upsert(
        telegram_id,
        state="trainer_selected",
        selected_trainer_id=trainer_id,
    )
    await session.commit()


def _payload_dict(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    raw = row.get("payload") or {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def normalize_ice_tab_when_pref(when: str | None, when_day: str | None = None) -> tuple[str, str]:
    """Persisted ice-tab window; ``auto`` → ``any`` (legacy smart default)."""
    key = (when or "any").strip().lower()
    day = (when_day or "").strip()
    if key == "auto":
        return "any", ""
    if key == "day":
        if not _DAY_ISO_RE.match(day):
            return "any", ""
        return "day", day
    if key in WHEN_KEYS:
        return key, ""
    return "any", ""


def ice_tab_when_from_session_row(row: dict[str, Any] | None) -> dict[str, str] | None:
    payload = _payload_dict(row)
    when = payload.get("ice_tab_when")
    if when is None:
        return None
    norm_when, norm_day = normalize_ice_tab_when_pref(str(when), str(payload.get("ice_tab_when_day") or ""))
    return {"when": norm_when, "when_day": norm_day}


async def save_ice_tab_when_pref(
    telegram_id: int,
    session: AsyncSession,
    *,
    when: str,
    when_day: str = "",
) -> None:
    """Ice catalog «Когда» — survives Telegram WebView storage wipes."""
    norm_when, norm_day = normalize_ice_tab_when_pref(when, when_day)
    repo = ClientSessionRepository(session)
    row = await repo.get(telegram_id)
    payload = _payload_dict(row)
    payload["ice_tab_when"] = norm_when
    payload["ice_tab_when_day"] = norm_day
    if row:
        await repo.upsert(telegram_id, payload=payload)
    else:
        await repo.upsert(telegram_id, state="idle", payload=payload)
    await session.commit()


async def save_catalog_filters(
    telegram_id: int,
    session: AsyncSession,
    *,
    city_id: int | None = None,
    service_id: int | None = None,
    arena_id: int | None = None,
    trainer_id: int | None = None,
) -> None:
    """
    Persist catalog filter chips (city / service / arena / trainer) from Mini App summary.
    Applies fields in dependency order; trainer_id is written last so it survives set_service.
    """
    if city_id is not None:
        await set_city(telegram_id, city_id, session)
    if service_id is not None:
        await set_service(telegram_id, service_id, session)
    if arena_id is not None:
        await set_arena(telegram_id, arena_id, session)
    if trainer_id is not None:
        await set_selected_trainer(telegram_id, trainer_id, session)


async def sync_session_catalog_after_client_booking(
    telegram_id: int,
    trainer_id: int,
    service_id: int,
    session: AsyncSession,
) -> None:
    """After catalog booking: persist city (from trainer profile), service, and trainer in client_sessions."""
    from src.application.trainer_use_cases import get_trainer

    city_id: int | None = None
    trainer = await get_trainer(session, trainer_id)
    if trainer and trainer.get("profile"):
        raw_city = trainer["profile"].get("city_id")
        if raw_city is not None:
            city_id = int(raw_city)
    await save_catalog_filters(
        telegram_id,
        session,
        city_id=city_id,
        service_id=service_id,
        trainer_id=trainer_id,
    )


async def get_session(telegram_id: int, session: AsyncSession) -> dict[str, Any] | None:
    """Load session by telegram_id; None if not found."""
    return await ClientSessionRepository(session).get(telegram_id)


async def clear_choices(telegram_id: int, session: AsyncSession) -> None:
    """Reset city, service, trainer; keep session row for future choices."""
    repo = ClientSessionRepository(session)
    await repo.clear_choices(telegram_id)
    await session.commit()


async def set_pending_request_id(
    telegram_id: int, request_id: int, session: AsyncSession
) -> None:
    """Store request_id in session payload for booking-from-request flow; merged with existing payload."""
    repo = ClientSessionRepository(session)
    row = await repo.get(telegram_id)
    if not row:
        await repo.upsert(telegram_id, state="idle", payload={"pending_request_id": request_id})
    else:
        payload = dict(row.get("payload") or {})
        payload["pending_request_id"] = request_id
        await repo.upsert(telegram_id, payload=payload)
    await session.commit()


async def clear_pending_request_id(telegram_id: int, session: AsyncSession) -> None:
    """Remove pending_request_id from session payload (after booking created or user left request flow)."""
    repo = ClientSessionRepository(session)
    row = await repo.get(telegram_id)
    if not row:
        return
    payload = dict(row.get("payload") or {})
    payload.pop("pending_request_id", None)
    # {} is falsy. Passing None tells upsert to leave payload untouched, so a
    # flag that was the only key would survive the clear.
    await repo.upsert(telegram_id, payload=payload)
    await session.commit()


async def set_pending_referral(telegram_id: int, trainer_id: int, session: AsyncSession) -> None:
    """
    Store trainer_id from a welcome_ref invite that needs the registration form
    (missing phone/name). Read by the client hub to gate access until the client
    completes registration (phone match resolves dedup).
    """
    repo = ClientSessionRepository(session)
    row = await repo.get(telegram_id)
    if not row:
        await repo.upsert(telegram_id, state="idle", payload={"pending_referral_trainer_id": trainer_id})
    else:
        payload = dict(row.get("payload") or {})
        payload["pending_referral_trainer_id"] = trainer_id
        await repo.upsert(telegram_id, payload=payload)
    await session.commit()


async def get_pending_referral(telegram_id: int, session: AsyncSession) -> int | None:
    """trainer_id of an unresolved welcome_ref invite, or None."""
    row = await ClientSessionRepository(session).get(telegram_id)
    if not row:
        return None
    tid = (row.get("payload") or {}).get("pending_referral_trainer_id")
    return int(tid) if tid is not None else None


async def clear_pending_referral(telegram_id: int, session: AsyncSession) -> None:
    """Clear pending referral once resolved (registered, or bound through any other invite path)."""
    repo = ClientSessionRepository(session)
    row = await repo.get(telegram_id)
    if not row:
        return
    payload = dict(row.get("payload") or {})
    payload.pop("pending_referral_trainer_id", None)
    # {} is falsy. Passing None tells upsert to leave payload untouched, so a
    # welcome_ref flag that was the only key would survive registration and the
    # client hub would keep showing the invite gate.
    await repo.upsert(telegram_id, payload=payload)
    await session.commit()
