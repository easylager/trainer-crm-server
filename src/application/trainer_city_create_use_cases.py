"""
Trainer-proposed city on onboarding (TASK-170).

Creates ``cities`` with ``is_active=false`` until an admin activates it via
``PATCH /admin/cities/{id}``. The creator (and quick-setup city list) still see the row.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.repositories.trainer_repository import TrainerRepository

CITY_NAME_MAX_LEN = 128


def _normalize_city_name(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    return s[:CITY_NAME_MAX_LEN]


async def _find_city_by_name_insensitive(session: AsyncSession, name: str) -> dict[str, Any] | None:
    r = await session.execute(
        text(
            """
            SELECT id, name, is_active, created_by_trainer_id
            FROM cities
            WHERE lower(trim(name)) = lower(trim(:n))
            ORDER BY is_active DESC, id
            LIMIT 1
            """
        ),
        {"n": name},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]),
        "name": row[1],
        "is_active": bool(row[2]),
        "created_by_trainer_id": int(row[3]) if row[3] is not None else None,
    }


async def create_trainer_city(
    session: AsyncSession,
    trainer_id: int,
    *,
    name: str,
    country: str = "BY",
) -> dict[str, Any]:
    """
    Create or return an existing city matched by name (case-insensitive).

    Returns ``status``: ``created`` | ``existing_active`` | ``existing_inactive``.
    """
    nm = _normalize_city_name(name)
    if not nm:
        raise ValueError("Укажите название города.")
    if not re.search(r"\w", nm, flags=re.UNICODE):
        raise ValueError("Напишите название города буквами.")

    existing = await _find_city_by_name_insensitive(session, nm)
    if existing:
        if not existing["is_active"]:
            creator = existing.get("created_by_trainer_id")
            if creator is not None and int(creator) != int(trainer_id):
                raise ValueError(
                    "Такой город уже предложен другим тренером и на проверке. "
                    "Выберите его из списка после публикации или напишите название чуть иначе."
                )
            if not await trainer_may_use_city_id(session, trainer_id, int(existing["id"])):
                raise ValueError(
                    "Этот город пока недоступен — дождитесь публикации в каталоге "
                    "или выберите другой из списка."
                )
        status = "existing_active" if existing["is_active"] else "existing_inactive"
        return {
            "status": status,
            "city_id": existing["id"],
            "name": existing["name"],
            "is_active": existing["is_active"],
        }

    ins = await session.execute(
        text(
            """
            INSERT INTO cities (name, sort_order, is_active, country, created_by_trainer_id)
            VALUES (:name, 9999, false, :country, :tid)
            RETURNING id, name
            """
        ),
        {"name": nm, "country": (country or "BY").strip().upper()[:2] or "BY", "tid": trainer_id},
    )
    row = ins.fetchone()
    if not row:
        raise RuntimeError("city insert failed")
    city_id = int(row[0])
    city_name = str(row[1])

    repo = TrainerRepository(session)
    await repo.ensure_trainer_profile_row(trainer_id)
    await repo.update_profile(trainer_id, city_id=city_id)
    await session.commit()

    return {
        "status": "created",
        "city_id": city_id,
        "name": city_name,
        "is_active": False,
    }


async def trainer_may_use_city_id(session: AsyncSession, trainer_id: int, city_id: int) -> bool:
    """Active cities or rows created by this trainer."""
    r = await session.execute(
        text(
            """
            SELECT 1 FROM cities
            WHERE id = :cid
              AND (is_active = true OR created_by_trainer_id = :tid)
            """
        ),
        {"cid": int(city_id), "tid": int(trainer_id)},
    )
    return r.scalar() is not None
