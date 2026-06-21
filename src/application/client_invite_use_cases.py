"""Client invite flows (welcome_ref / share_ref / pass): catalog bind + CRM roster."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import (
    get_trainer_default_city_and_service,
    link_trainer_client_roster,
    resolve_welcome_session_city_service,
)
from src.application.client_session_use_cases import save_catalog_filters
from src.application.client_trainer_edge_use_cases import set_primary_trainer
from src.application.client_use_cases import (
    get_client_id_by_telegram_id,
    get_client_phone_for_webapp,
    get_client_profile_basic,
    normalize_phone,
)
from src.application.trainer_client_registration_notify import (
    notify_trainer_client_registered_from_invite,
)


async def client_invite_needs_registration_form(
    session: AsyncSession,
    telegram_id: int,
) -> bool:
    """True when invite should open client-register (missing phone or display name)."""
    phone = await get_client_phone_for_webapp(session, telegram_id)
    if normalize_phone(phone) is None:
        return True
    profile = await get_client_profile_basic(session, telegram_id)
    first_name = (profile.get("first_name") or "").strip() if profile else ""
    return not bool(first_name)


async def bind_client_invite_trainer_context(
    telegram_id: int,
    trainer_id: int,
    session: AsyncSession,
    *,
    preferred_service_id: int | None = None,
    client_id: int | None = None,
) -> tuple[int | None, int | None]:
    """
    Persist catalog filters + primary trainer after invite / share_ref / welcome_ref.
    Also links trainer_client_roster so the client appears in CRM before first booking.
    """
    if preferred_service_id is not None:
        city_id, service_id = await resolve_welcome_session_city_service(
            session,
            trainer_id,
            preferred_service_id=preferred_service_id,
        )
    else:
        city_id, service_id = await get_trainer_default_city_and_service(session, trainer_id)

    resolved_client_id = client_id
    if resolved_client_id is None:
        resolved_client_id = await get_client_id_by_telegram_id(session, telegram_id)

    roster_created = False
    if resolved_client_id is not None:
        roster_created = await link_trainer_client_roster(
            session, int(trainer_id), int(resolved_client_id)
        )

    await save_catalog_filters(
        telegram_id,
        session,
        city_id=city_id,
        service_id=service_id,
        trainer_id=int(trainer_id),
    )
    await set_primary_trainer(telegram_id, int(trainer_id), session)

    if roster_created and resolved_client_id is not None:
        await notify_trainer_client_registered_from_invite(
            session=session,
            trainer_id=int(trainer_id),
            client_id=int(resolved_client_id),
            event="new_client",
        )

    return city_id, service_id
