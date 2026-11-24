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


def fast_tabs_bucket(account_key: int) -> int:
    """Своя корзина: процент fast_tabs не повторяет выборку season_ui."""
    digest = hashlib.sha256(f"fast-tabs:{int(account_key)}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def fast_tabs_enabled(account_key: int, settings: Settings) -> bool:
    """TASK-391: «Я» и «Записи» в одной оболочке. Только поверх season_ui."""
    if not season_ui_enabled(account_key, settings):
        return False
    if int(account_key) in (settings.client_fast_tabs_telegram_ids or ()):
        return True
    return fast_tabs_bucket(account_key) < settings.client_fast_tabs_percent


def search_board_bucket(account_key: int) -> int:
    """Своя корзина: процент search_board не повторяет выборки season_ui и fast_tabs."""
    digest = hashlib.sha256(f"search-board:{int(account_key)}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def search_board_enabled(account_key: int, settings: Settings) -> bool:
    """TASK-438: вкладка «Поиск» — лента сеансов по времени. От season_ui не зависит."""
    if int(account_key) in (settings.client_search_board_telegram_ids or ()):
        return True
    return search_board_bucket(account_key) < settings.client_search_board_percent


def redesign_s1_bucket(account_key: int) -> int:
    """Своя корзина: процент redesign_s1 не повторяет выборки season_ui/fast_tabs/search_board."""
    digest = hashlib.sha256(f"redesign-s1:{int(account_key)}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def redesign_s1_enabled(account_key: int, settings: Settings) -> bool:
    """TASK-445: этап 1 редизайна — новая главная, меню 5 вкладок, светлая тема."""
    if int(account_key) in (settings.client_redesign_s1_telegram_ids or ()):
        return True
    return redesign_s1_bucket(account_key) < settings.client_redesign_s1_percent


def redesign_s5_bucket(account_key: int) -> int:
    """Своя корзина: процент redesign_s5 не повторяет выборки остальных флагов."""
    digest = hashlib.sha256(f"redesign-s5:{int(account_key)}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def redesign_s5_enabled(account_key: int, settings: Settings) -> bool:
    """TASK-446: «Я здесь» — отметки и загрузка катков. Независим от redesign_s1."""
    if int(account_key) in (settings.client_redesign_s5_telegram_ids or ()):
        return True
    return redesign_s5_bucket(account_key) < settings.client_redesign_s5_percent


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
