"""TASK-366: кому показывать новую навигацию your-season и вкладку «Записи»."""

from __future__ import annotations

import hashlib

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.config import Settings


def season_ui_bucket(account_key: int) -> int:
    """Стабильная корзина 0…99 для ключа аккаунта (``client_catalog_telegram_key``)."""
    digest = hashlib.sha256(f"season-ui:{int(account_key)}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def season_ui_enabled(account_key: int, settings: Settings) -> bool:
    if int(account_key) in (settings.client_season_ui_telegram_ids or ()):
        return True
    return season_ui_bucket(account_key) < settings.client_season_ui_percent


# Профили аккаунта — как у GET /client/passes и /client/bookings/history: своя строка,
# семейный доступ (resolve_acting_client_id) и профили из client_profile_links.
# Любой статус и любая давность: вкладка, появившись, не исчезает.
_TRAINER_HISTORY_SQL = text(
    """
    WITH profiles AS (
      SELECT id AS client_id FROM clients WHERE telegram_id = :key
      UNION
      SELECT primary_client_id FROM client_family_access_members WHERE member_telegram_id = :key
      UNION
      SELECT profile_client_id FROM client_profile_links WHERE account_telegram_id = :key
    )
    SELECT
      EXISTS (SELECT 1 FROM bookings b JOIN profiles p ON p.client_id = b.client_id)
      OR EXISTS (SELECT 1 FROM pass_instances pi JOIN profiles p ON p.client_id = pi.client_id)
    """
)


async def has_trainer_history(session: AsyncSession, account_key: int) -> bool:
    r = await session.execute(_TRAINER_HISTORY_SQL, {"key": int(account_key)})
    return bool(r.scalar())
