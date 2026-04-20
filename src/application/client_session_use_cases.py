"""
Application layer: client bot session use cases. Get/update session state and choices.
"""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.repositories import ClientSessionRepository


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
    await repo.upsert(telegram_id, payload=payload if payload else None)
    await session.commit()
