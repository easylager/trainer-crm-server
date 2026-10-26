"""Строка ``clients`` для действия из Mini App: найти или завести на месте.

Пользователь каталога живёт с одной ``client_sessions`` — регистрации у него нет и не будет.
Когда он впервые что-то делает (подписка, «сохранить тренера», сертификат), строку клиента
заводим здесь, а не отвечаем «завершите регистрацию»: такого шага для него не существует
(обращение #13).
"""

from __future__ import annotations

from urllib.parse import parse_qsl

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key
from src.api.miniapp_auth.types import MiniAppPlatform
from src.api.miniapp_auth.vk_launch_params import vk_launch_display_user_fields
from src.application.client_profile_use_cases import resolve_acting_client_id
from src.application.client_session_use_cases import get_or_create_session
from src.application.client_use_cases import get_or_create_client
from src.shared.telegram_webapp import parse_user_json_from_init_data


def _host_user_fields(principal: MiniAppPrincipal, raw_credential: str | None) -> dict:
    raw = (raw_credential or "").strip()
    if not raw:
        return {}
    if principal.platform == MiniAppPlatform.TELEGRAM:
        return parse_user_json_from_init_data(raw) or {}
    return vk_launch_display_user_fields(dict(parse_qsl(raw.lstrip("?"), keep_blank_values=True)))


async def ensure_acting_client_id(
    session: AsyncSession,
    principal: MiniAppPrincipal,
    raw_credential: str | None,
    requested_profile_id: int | None = None,
) -> int:
    """``clients.id``, от имени которого действует запрос; нет строки — заводим её и сессию.

    Имя берём из данных хоста (Telegram initData / VK launch), чтобы тренер видел человека,
    а не пустую карточку. Коммитит сам: дальше вызывающий пишет строки со ссылкой на клиента.
    """
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await resolve_acting_client_id(session, catalog_tid, requested_profile_id)
    if client_id is not None:
        return int(client_id)
    user = _host_user_fields(principal, raw_credential)
    client_id = await get_or_create_client(
        session,
        catalog_tid,
        vk_user_id=int(principal.user_id) if principal.platform == MiniAppPlatform.MAX else None,
        first_name=str(user.get("first_name") or "").strip() or None,
        last_name=str(user.get("last_name") or "").strip() or None,
        telegram_username=str(user.get("username") or "").strip() or None,
    )
    await session.commit()
    await get_or_create_session(catalog_tid, session)
    return int(client_id)
