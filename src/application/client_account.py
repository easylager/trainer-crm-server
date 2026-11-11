"""Имя и «мой каток» аккаунта Mini App (TASK-367). Без HTTP.

Ключ — ``client_catalog_telegram_key(principal)``, тот же, что ``hockey_players.player_key``.
Имя живёт в ``hockey_players.display_name``; каток — в ``client_account_prefs``.
"""

from __future__ import annotations

import unicodedata

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params

_ZWJ = "\u200d"
# Cc/Cf — управляющие и форматные, Cs — суррогаты, Co — private use. Cn (не назначены) не режем:
# таблица unicodedata отстаёт от клиентов, и новый эмодзи для неё «неназначенный».
_DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co"})
# Буквы и знаки, которые рисуются пустыми: Hangul filler, braille blank и родня.
_BLANK_FILLERS = frozenset("\u115f\u1160\u3164\uffa0\u2800")
_NAME_ERROR = "Имя — от 1 до 40 знаков"
_ARENA_ERROR = "Каток не найден"

_SET_NAME = text("""
    INSERT INTO hockey_players (player_key, display_name, name_set_by_user)
    VALUES (:player_key, :display_name, true)
    ON CONFLICT (player_key) DO UPDATE
    SET display_name = EXCLUDED.display_name,
        name_set_by_user = true,
        updated_at = now()
    RETURNING display_name
    """)

_HOME_ARENA = text("SELECT home_arena_id FROM client_account_prefs WHERE account_key = :account_key")

# Тот же предикат, что у списка катков вкладки «Поиск» (``PUBLIC_ARENA_VISIBLE_SQL``).
_VISIBLE_ARENA = text(f"""
    SELECT a.id
    FROM arenas a
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    WHERE a.id = :arena_id
      AND {PUBLIC_ARENA_VISIBLE_SQL}
    """)

_SET_HOME = text("""
    INSERT INTO client_account_prefs (account_key, home_arena_id)
    VALUES (:account_key, :arena_id)
    ON CONFLICT (account_key) DO UPDATE
    SET home_arena_id = EXCLUDED.home_arena_id,
        updated_at = now()
    RETURNING home_arena_id
    """)


def _counts_as_visible(ch: str) -> bool:
    """Буква, цифра, So — или неназначенный кодпоинт (эмодзи новее таблицы Python), но не нехарактер."""
    cat = unicodedata.category(ch)
    if cat[0] in ("L", "N") or cat == "So":
        return True
    cp = ord(ch)
    return cat == "Cn" and not (0xFDD0 <= cp <= 0xFDEF or (cp & 0xFFFE) == 0xFFFE)


def normalize_display_name(raw: str) -> str:
    """Имя для показа: пробелы схлопнуть, края обрезать, невидимое убрать. Эмодзи и ZWJ-склейки остаются.

    Убираются управляющие и форматные знаки, суррогаты и private use,
    а также «пустые» заполнители (U+3164, U+2800 и родня). ZWJ живёт только между двумя видимыми
    знаками. В имени должна быть буква, цифра или эмодзи, иначе оно выглядит пустым.
    """
    kept: list[str] = []
    for ch in raw:
        if ch == _ZWJ:
            kept.append(ch)
        elif ch in _BLANK_FILLERS or unicodedata.category(ch) in _DROPPED_CATEGORIES:
            continue
        else:
            kept.append(ch)
    chars = list(" ".join("".join(kept).split()))
    glued: list[str] = []
    for i, ch in enumerate(chars):
        if ch == _ZWJ:
            after = next((c for c in chars[i + 1 :] if c != _ZWJ), " ")
            if not glued or glued[-1] in (" ", _ZWJ) or after == " ":
                continue
        glued.append(ch)
    name = " ".join("".join(glued).split())
    if not any(_counts_as_visible(ch) for ch in name):
        raise ValueError(_NAME_ERROR)
    if not 1 <= len(name) <= 40:
        raise ValueError(_NAME_ERROR)
    return name


async def set_account_name(session: AsyncSession, account_key: int, raw: str) -> str:
    """Сохранить имя человека. Дальше ход из Telegram его не перезаписывает."""
    name = normalize_display_name(raw)
    saved = (
        await session.execute(_SET_NAME, {"player_key": account_key, "display_name": name})
    ).scalar_one()
    return str(saved)


async def get_home_arena_id(session: AsyncSession, account_key: int) -> int | None:
    arena_id = (await session.execute(_HOME_ARENA, {"account_key": account_key})).scalar_one_or_none()
    return None if arena_id is None else int(arena_id)


async def set_home_arena(session: AsyncSession, account_key: int, arena_id: int | None) -> int | None:
    """Поставить «мой каток» или снять выбор (``None``). Скрытый и чужой id — ошибка."""
    if arena_id is not None:
        visible = (
            await session.execute(_VISIBLE_ARENA, {"arena_id": arena_id, **public_scope_params()})
        ).scalar_one_or_none()
        if visible is None:
            raise ValueError(_ARENA_ERROR)
    saved = (
        await session.execute(_SET_HOME, {"account_key": account_key, "arena_id": arena_id})
    ).scalar_one()
    return None if saved is None else int(saved)
