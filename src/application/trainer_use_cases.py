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
        "city_id": profile.get("city_id"),
        "experience_years": profile.get("experience_years"),
        "description": profile.get("description"),
        "phone": profile.get("phone"),
        "contacts": profile.get("contacts"),
        "education": profile.get("education"),
    }


def _services_to_tuples(services: list[dict[str, Any]]) -> list[tuple[int, int | None]]:
    """Convert API services (price_byn in rubles) to (service_id, price_cents) for repo."""
    result = []
    for s in services:
        sid = s["service_id"]
        price_byn = s.get("price_byn")
        price_cents = int(round(price_byn * 100)) if price_byn is not None else None
        result.append((sid, price_cents))
    return result


async def create_trainer(
    session: AsyncSession,
    *,
    profile: dict[str, Any] | None = None,
    service_ids: list[int] | None = None,
    services: list[dict[str, Any]] | None = None,
    arena_ids: list[int] | None = None,
) -> int:
    """Create trainer; optionally with profile, services (with prices), arena_ids. Returns new trainer id."""
    repo = TrainerRepository(session)
    trainer_id = await repo.create_trainer()
    if profile:
        await repo.create_profile(trainer_id, **_profile_to_kwargs(profile))
    if services is not None:
        await repo.set_trainer_services(trainer_id, _services_to_tuples(services))
    elif service_ids:
        await repo.set_trainer_services(trainer_id, [(sid, None) for sid in service_ids])
    if arena_ids:
        await repo.set_trainer_arenas(trainer_id, arena_ids)
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
    services: list[dict[str, Any]] | None = None,
    arena_ids: list[int] | None = None,
) -> bool:
    """Patch profile and/or services (with prices) and/or arena_ids. Returns False if trainer not found."""
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return False
    updates = {k: v for k, v in profile.items() if v is not None}
    if updates:
        await repo.update_profile(trainer_id, **updates)
    if services is not None:
        await repo.set_trainer_services(trainer_id, _services_to_tuples(services))
    elif service_ids is not None:
        await repo.set_trainer_services(trainer_id, [(sid, None) for sid in service_ids])
    if arena_ids is not None:
        await repo.set_trainer_arenas(trainer_id, arena_ids)
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


async def set_trainer_moderation_feedback(
    session: AsyncSession, trainer_id: int, feedback: str | None
) -> bool:
    """Set or clear moderation feedback (shown on site). Returns False if trainer not found."""
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return False
    await repo.set_moderation_feedback(trainer_id, feedback)
    await session.commit()
    return True


async def list_active_trainers_for_client(
    session: AsyncSession,
    limit: int = 50,
    offset: int = 0,
    city_id: int | None = None,
    service_id: int | None = None,
    arena_id: int | None = None,
    order_by: str = "rating",
) -> tuple[list[dict[str, Any]], int]:
    """Active trainers; optional arena filter (trainers with slot in that arena). Returns (items, total)."""
    return await TrainerRepository(session).list_active_with_details(
        limit=limit,
        offset=offset,
        city_id=city_id,
        service_id=service_id,
        arena_id=arena_id,
        order_by=order_by,
    )


async def add_trainer_rating(
    session: AsyncSession,
    trainer_id: int,
    client_telegram_id: int,
    rating: int,
    review_text: str | None = None,
) -> bool:
    """Set or update client's rating 1–5 and optional review for trainer; updates profile aggregates."""
    ok = await TrainerRepository(session).add_rating(
        trainer_id, client_telegram_id, rating, review_text=review_text
    )
    if ok:
        await session.commit()
    return ok


async def register_photo(
    session: AsyncSession, trainer_id: int, file_key: str, sort_order: int = 0, file_key_list: str | None = None
) -> bool:
    """
    Attach photo to trainer (and optional list thumb).
    For now we enforce single-photo per trainer: new upload replaces any existing photos.
    Returns False if trainer not found.
    """
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return False
    # Single-photo policy: drop previous photos for this trainer.
    await repo.clear_photos(trainer_id)
    await repo.add_photo(trainer_id, file_key, sort_order, file_key_list=file_key_list)
    await session.commit()
    return True
