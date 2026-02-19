"""
Application layer: trainer use cases. Orchestrates repository; no HTTP, no SQL.
"""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.repositories import TrainerRepository


def _profile_to_kwargs(profile: dict[str, Any]) -> dict[str, Any]:
    """Map profile dict to repository create_profile kwargs."""
    return {
        "first_name": profile.get("first_name") or "",
        "last_name": profile.get("last_name") or "",
        "age": profile.get("age", 0),
        "experience_years": profile.get("experience_years"),
        "description": profile.get("description"),
        "phone": profile.get("phone"),
        "contacts": profile.get("contacts"),
        "education": profile.get("education"),
    }


async def create_trainer(
    session: AsyncSession,
    *,
    profile: dict[str, Any] | None = None,
    service_ids: list[int] | None = None,
) -> int:
    """Create trainer; optionally with profile and service_ids. Returns new trainer id."""
    repo = TrainerRepository(session)
    trainer_id = await repo.create_trainer()
    if profile:
        await repo.create_profile(trainer_id, **_profile_to_kwargs(profile))
    if service_ids:
        await repo.set_trainer_services(trainer_id, service_ids)
    await session.commit()
    return trainer_id


async def get_trainer(session: AsyncSession, trainer_id: int) -> dict[str, Any] | None:
    """Load trainer by id with profile, photos, service_ids; None if not found."""
    return await TrainerRepository(session).get_by_id(trainer_id)


async def update_trainer_profile(
    session: AsyncSession,
    trainer_id: int,
    *,
    profile: dict[str, Any],
    service_ids: list[int] | None = None,
) -> bool:
    """Patch profile and/or service_ids. Returns False if trainer not found."""
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return False
    updates = {k: v for k, v in profile.items() if v is not None}
    if updates:
        await repo.update_profile(trainer_id, **updates)
    if service_ids is not None:
        await repo.set_trainer_services(trainer_id, service_ids)
    await session.commit()
    return True


async def list_trainers(
    session: AsyncSession,
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List trainers with optional status filter (e.g. status=active for catalog)."""
    return await TrainerRepository(session).list_trainers(limit=limit, offset=offset, status=status)


async def update_trainer_status(session: AsyncSession, trainer_id: int, status: str) -> bool:
    """Set trainer status. Returns False if trainer not found."""
    repo = TrainerRepository(session)
    if not await repo.update_status(trainer_id, status):
        return False
    await session.commit()
    return True


async def list_active_trainers_for_client(
    session: AsyncSession,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Active trainers with profile, photos, service_ids for client catalog/bot."""
    return await TrainerRepository(session).list_active_with_details(limit=limit)


async def register_photo(
    session: AsyncSession, trainer_id: int, file_key: str, sort_order: int = 0
) -> bool:
    """Attach photo to trainer by file_key. Returns False if trainer not found."""
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return False
    await repo.add_photo(trainer_id, file_key, sort_order)
    await session.commit()
    return True
