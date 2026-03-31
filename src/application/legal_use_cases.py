"""Legal documents and trainer agreements: trainer_terms versioning and acceptance."""
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_active_trainer_terms(session: AsyncSession) -> dict[str, Any] | None:
    """Return active trainer_terms document or None if not configured."""
    r = await session.execute(
        text(
            """
            SELECT id, code, version, title, file_key, is_active, created_at
            FROM legal_documents
            WHERE code = :code AND is_active = true
            ORDER BY version DESC
            LIMIT 1
            """
        ),
        {"code": "trainer_terms"},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "code": row[1],
        "version": row[2],
        "title": row[3],
        "file_key": row[4],
        "is_active": row[5],
        "created_at": row[6],
    }


async def trainer_has_accepted_active_terms(session: AsyncSession, trainer_id: int) -> bool:
    """Check if trainer has accepted current active trainer_terms version.

    If there is no active trainer_terms document yet, returns True (no requirement configured).
    """
    doc = await get_active_trainer_terms(session)
    if not doc:
        return True
    r = await session.execute(
        text(
            """
            SELECT 1
            FROM trainer_agreements
            WHERE trainer_id = :tid AND document_id = :doc_id
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "doc_id": doc["id"]},
    )
    return r.fetchone() is not None


async def accept_trainer_terms(session: AsyncSession, trainer_id: int) -> bool:
    """Mark active trainer_terms as accepted by trainer. Idempotent."""
    doc = await get_active_trainer_terms(session)
    if not doc:
        return False
    r = await session.execute(
        text(
            """
            INSERT INTO trainer_agreements (trainer_id, document_id, accepted_version)
            VALUES (:tid, :doc_id, :version)
            ON CONFLICT (trainer_id, document_id) DO NOTHING
            RETURNING id
            """
        ),
        {"tid": trainer_id, "doc_id": doc["id"], "version": doc["version"]},
    )
    # Even if row already existed, we consider it ok
    if not r.fetchone():
        # Already accepted earlier
        return True
    await session.commit()
    return True


async def get_trainer_terms_status(session: AsyncSession, trainer_id: int) -> dict[str, Any]:
    """Return status for trainer onboarding: active document + whether accepted."""
    doc = await get_active_trainer_terms(session)
    if not doc:
        return {
            "has_active_document": False,
            "has_accepted": True,
            "document": None,
        }
    r = await session.execute(
        text(
            """
            SELECT 1
            FROM trainer_agreements
            WHERE trainer_id = :tid AND document_id = :doc_id
            LIMIT 1
            """
        ),
        {"tid": trainer_id, "doc_id": doc["id"]},
    )
    has_accepted = r.fetchone() is not None
    return {
        "has_active_document": True,
        "has_accepted": has_accepted,
        "document": {
            "id": doc["id"],
            "code": doc["code"],
            "version": doc["version"],
            "title": doc["title"],
            "file_key": doc["file_key"],
        },
    }


async def create_trainer_terms_document(
    session: AsyncSession,
    *,
    version: int,
    title: str | None,
    file_key: str,
    make_active: bool,
) -> dict[str, Any]:
    """Admin: create new trainer_terms document. Optionally mark as active."""
    # Insert document
    r = await session.execute(
        text(
            """
            INSERT INTO legal_documents (code, version, title, file_key, is_active)
            VALUES (:code, :version, :title, :file_key, :is_active)
            RETURNING id, created_at
            """
        ),
        {
            "code": "trainer_terms",
            "version": version,
            "title": title,
            "file_key": file_key,
            "is_active": True if make_active else False,
        },
    )
    row = r.fetchone()
    doc_id = row[0]
    created_at = row[1]
    if make_active:
        # Deactivate others
        await session.execute(
            text(
                """
                UPDATE legal_documents
                SET is_active = false
                WHERE code = :code AND id != :id
                """
            ),
            {"code": "trainer_terms", "id": doc_id},
        )
    await session.commit()
    return {
        "id": doc_id,
        "version": version,
        "title": title,
        "file_key": file_key,
        "is_active": make_active,
        "created_at": created_at,
    }


async def activate_trainer_terms_document(session: AsyncSession, document_id: int) -> bool:
    """Admin: make specific trainer_terms document active."""
    # Ensure document exists and has correct code
    r = await session.execute(
        text(
            """
            SELECT code FROM legal_documents WHERE id = :id
            """
        ),
        {"id": document_id},
    )
    row = r.fetchone()
    if not row or row[0] != "trainer_terms":
        return False
    await session.execute(
        text(
            """
            UPDATE legal_documents
            SET is_active = (id = :id)
            WHERE code = :code
            """
        ),
        {"id": document_id, "code": "trainer_terms"},
    )
    await session.commit()
    return True


