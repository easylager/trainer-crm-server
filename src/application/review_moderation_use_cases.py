"""Модерация текстов отзывов: подтвердить / отклонить (кнопки админ-бота)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.review_moderation import STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED


class ReviewModerationError(Exception):
    """``code``: ``missing`` — нет такого отзыва; ``closed`` — уже разобран."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def display_name(first_name: str | None, last_name: str | None) -> str:
    """«Марк М.» — имя и инициал фамилии; нет имени — «Ученик»."""
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    if not first:
        return "Ученик"
    return f"{first} {last[0].upper()}." if last else first


async def load_review_for_moderation(session: AsyncSession, rating_id: int) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT r.id, r.trainer_id, r.rating, r.review_text, r.review_status,
                       p.first_name, p.last_name, c.first_name, c.last_name
                FROM trainer_ratings r
                LEFT JOIN trainer_profiles p ON p.trainer_id = r.trainer_id
                LEFT JOIN clients c ON c.telegram_id = r.client_telegram_id
                WHERE r.id = :id
                """
            ),
            {"id": int(rating_id)},
        )
    ).fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]),
        "trainer_id": int(row[1]),
        "rating": int(row[2]),
        "review_text": (row[3] or "").strip(),
        "status": row[4],
        "trainer_name": " ".join(x for x in (row[5], row[6]) if x) or f"Тренер №{int(row[1])}",
        "client_name": display_name(row[7], row[8]),
    }


async def list_pending_reviews(session: AsyncSession, *, limit: int = 10) -> list[int]:
    rows = await session.execute(
        text(
            "SELECT id FROM trainer_ratings WHERE review_status = :st "
            "ORDER BY created_at, id LIMIT :lim"
        ),
        {"st": STATUS_PENDING, "lim": int(limit)},
    )
    return [int(r[0]) for r in rows.fetchall()]


async def moderate_review(session: AsyncSession, rating_id: int, *, approve: bool, admin_id: int) -> dict[str, Any]:
    """Pending → approved / rejected. Уже разобранный отзыв повторно не меняем (``closed``)."""
    new_status = STATUS_APPROVED if approve else STATUS_REJECTED
    row = (
        await session.execute(
            text(
                """
                UPDATE trainer_ratings
                SET review_status = :new, reviewed_at = now(), reviewed_by = :admin
                WHERE id = :id AND review_status = :pending
                RETURNING trainer_id
                """
            ),
            {"new": new_status, "admin": int(admin_id), "id": int(rating_id), "pending": STATUS_PENDING},
        )
    ).fetchone()
    if row is None:
        exists = (
            await session.execute(text("SELECT 1 FROM trainer_ratings WHERE id = :id"), {"id": int(rating_id)})
        ).scalar()
        raise ReviewModerationError("closed" if exists else "missing")
    await session.commit()
    return {"rating_id": int(rating_id), "trainer_id": int(row[0]), "status": new_status}
