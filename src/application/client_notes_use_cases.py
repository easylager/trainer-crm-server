"""
Trainer-client notes: per-trainer private notes about clients.
Simple CRUD (get/set) used by trainer Mini App.
"""
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_trainer_client_note(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> dict[str, Any] | None:
    r = await session.execute(
        text(
            """
            SELECT id, note
            FROM trainer_client_notes
            WHERE trainer_id = :tid AND client_id = :cid
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {"id": row[0], "note": row[1] or ""}


async def upsert_trainer_client_note(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    note: str,
) -> dict[str, Any]:
    """
    Create or update note for (trainer, client).
    Returns {"id": ..., "note": ...}.
    """
    trimmed = (note or "").strip()
    await session.execute(
        text(
            """
            INSERT INTO trainer_client_notes (trainer_id, client_id, note)
            VALUES (:tid, :cid, :note)
            ON CONFLICT (trainer_id, client_id)
            DO UPDATE SET note = EXCLUDED.note, updated_at = now()
            """
        ),
        {"tid": trainer_id, "cid": client_id, "note": trimmed},
    )
    r = await session.execute(
        text(
            "SELECT id, note FROM trainer_client_notes WHERE trainer_id = :tid AND client_id = :cid"
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    row = r.fetchone()
    if trimmed:
        from src.application.trainer_feature_tracking import (
            FEATURE_CLIENT_NOTE_WRITTEN,
            record_feature_first_use,
        )

        await record_feature_first_use(session, trainer_id, FEATURE_CLIENT_NOTE_WRITTEN)
    await session.commit()
    return {"id": row[0], "note": row[1] or ""}

