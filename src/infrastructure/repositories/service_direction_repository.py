"""
Привязка своей услуги тренера к направлению каталога.

Направление — публичная услуга справочника (``services.is_public``) той же вертикали;
у своих услуг ``vertical_key`` пуст, поэтому они относятся к льду.

Читать привязку:
  SELECT direction_service_id, direction_decided_at FROM services WHERE id = :id;
  * decided_at IS NULL                        — ещё не разобрано;
  * decided_at NOT NULL, direction IS NULL    — «не показывать»;
  * оба заданы                                — услуга в направлении direction_service_id.
Или ``get_service_direction``.
"""
from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_VERTICAL_KEY = "ice"

SetResult = Literal["changed", "unchanged", "not_found", "not_custom", "bad_direction"]


async def list_directions(session: AsyncSession, vertical_key: str | None = None) -> list[dict[str, Any]]:
    """Публичные услуги справочника вертикали — кандидаты в направления, в порядке sort_order."""
    rows = (
        await session.execute(
            text(
                """
                SELECT id, name FROM services
                WHERE is_public = true AND vertical_key = :vk
                ORDER BY sort_order, id
                """
            ),
            {"vk": vertical_key or DEFAULT_VERTICAL_KEY},
        )
    ).fetchall()
    return [{"id": int(r[0]), "name": r[1]} for r in rows]


async def get_service_direction(session: AsyncSession, service_id: int) -> dict[str, Any] | None:
    """None — услуги нет. Иначе direction_id/name, decided_at/by (см. docstring модуля)."""
    r = (
        await session.execute(
            text(
                """
                SELECT s.id, s.name, s.direction_service_id, d.name,
                       s.direction_decided_at, s.direction_decided_by
                FROM services s
                LEFT JOIN services d ON d.id = s.direction_service_id
                WHERE s.id = :sid
                """
            ),
            {"sid": service_id},
        )
    ).fetchone()
    if r is None:
        return None
    return {
        "service_id": int(r[0]),
        "name": r[1],
        "direction_id": int(r[2]) if r[2] is not None else None,
        "direction_name": r[3],
        "decided_at": r[4],
        "decided_by": r[5],
    }


async def set_service_direction(
    session: AsyncSession, service_id: int, direction_id: int | None, *, admin_id: int
) -> SetResult:
    """
    direction_id=None — «не показывать». Повтор того же решения ничего не меняет (автор и время
    первого решения сохраняются). Только своя услуга тренера; цель — публичная услуга той же вертикали.
    """
    own = (
        await session.execute(
            text(
                """
                SELECT created_by_trainer_id, is_public, vertical_key,
                       direction_service_id, direction_decided_at
                FROM services WHERE id = :sid FOR UPDATE
                """
            ),
            {"sid": service_id},
        )
    ).fetchone()
    if own is None:
        return "not_found"
    if own[0] is None or own[1]:
        return "not_custom"
    if direction_id is not None:
        ok = (
            await session.execute(
                text(
                    """
                    SELECT 1 FROM services
                    WHERE id = :did AND id <> :sid AND is_public = true AND vertical_key = :vk
                    """
                ),
                {"did": direction_id, "sid": service_id, "vk": own[2] or DEFAULT_VERTICAL_KEY},
            )
        ).fetchone()
        if ok is None:
            return "bad_direction"
    if own[4] is not None and own[3] == direction_id:
        return "unchanged"
    await session.execute(
        text(
            """
            UPDATE services
            SET direction_service_id = :did, direction_decided_at = now(), direction_decided_by = :admin
            WHERE id = :sid
            """
        ),
        {"did": direction_id, "sid": service_id, "admin": admin_id},
    )
    await session.commit()
    return "changed"
