"""
Trainer client dossier: structured profile, timeline entries, and tags.
Extends the simple note into a full client information system.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# --- Profile (goals, limitations, level, legacy note) ---


async def get_client_dossier_profile(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> dict[str, Any]:
    """Get profile fields for a client. Returns empty strings if no record."""
    r = await session.execute(
        text("""
            SELECT id, note, goals, limitations, level
            FROM trainer_client_notes
            WHERE trainer_id = :tid AND client_id = :cid
        """),
        {"tid": trainer_id, "cid": client_id},
    )
    row = r.fetchone()
    if not row:
        return {"note": "", "goals": "", "limitations": "", "level": ""}
    return {
        "id": row[0],
        "note": row[1] or "",
        "goals": row[2] or "",
        "limitations": row[3] or "",
        "level": row[4] or "",
    }


async def upsert_client_dossier_profile(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    *,
    note: str | None = None,
    goals: str | None = None,
    limitations: str | None = None,
    level: str | None = None,
) -> dict[str, Any]:
    """Update profile fields. Only provided fields are updated (None = keep existing)."""
    existing = await get_client_dossier_profile(session, trainer_id, client_id)
    
    final_note = note.strip() if note is not None else existing.get("note", "")
    final_goals = goals.strip() if goals is not None else existing.get("goals", "")
    final_limitations = limitations.strip() if limitations is not None else existing.get("limitations", "")
    final_level = level.strip() if level is not None else existing.get("level", "")
    
    await session.execute(
        text("""
            INSERT INTO trainer_client_notes (trainer_id, client_id, note, goals, limitations, level)
            VALUES (:tid, :cid, :note, :goals, :limitations, :level)
            ON CONFLICT (trainer_id, client_id)
            DO UPDATE SET 
                note = EXCLUDED.note,
                goals = EXCLUDED.goals,
                limitations = EXCLUDED.limitations,
                level = EXCLUDED.level,
                updated_at = now()
        """),
        {
            "tid": trainer_id,
            "cid": client_id,
            "note": final_note,
            "goals": final_goals,
            "limitations": final_limitations,
            "level": final_level,
        },
    )
    await session.commit()
    return await get_client_dossier_profile(session, trainer_id, client_id)


# --- Timeline entries ---


async def list_client_entries(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List timeline entries for a client, newest first."""
    r = await session.execute(
        text("""
            SELECT id, content, created_at
            FROM trainer_client_entries
            WHERE trainer_id = :tid AND client_id = :cid
            ORDER BY created_at DESC
            LIMIT :lim
        """),
        {"tid": trainer_id, "cid": client_id, "lim": limit},
    )
    return [
        {
            "id": row[0],
            "content": row[1],
            "created_at": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
        }
        for row in r.fetchall()
    ]


async def add_client_entry(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    content: str,
) -> dict[str, Any]:
    """Add a new timeline entry."""
    trimmed = (content or "").strip()
    if not trimmed:
        raise ValueError("Entry content cannot be empty")
    
    r = await session.execute(
        text("""
            INSERT INTO trainer_client_entries (trainer_id, client_id, content)
            VALUES (:tid, :cid, :content)
            RETURNING id, content, created_at
        """),
        {"tid": trainer_id, "cid": client_id, "content": trimmed},
    )
    row = r.fetchone()
    await session.commit()
    return {
        "id": row[0],
        "content": row[1],
        "created_at": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
    }


async def delete_client_entry(
    session: AsyncSession,
    trainer_id: int,
    entry_id: int,
) -> bool:
    """Delete a timeline entry. Returns True if deleted."""
    r = await session.execute(
        text("""
            DELETE FROM trainer_client_entries
            WHERE id = :eid AND trainer_id = :tid
            RETURNING id
        """),
        {"eid": entry_id, "tid": trainer_id},
    )
    deleted = r.fetchone() is not None
    await session.commit()
    return deleted


# --- Tags ---


TAG_CATEGORIES = {
    "injury": "Травмы",
    "goal": "Цели",
    "level": "Уровень",
    "schedule": "Расписание",
    "custom": "Другое",
}

SUGGESTED_TAGS = [
    {"tag": "Травма колена", "category": "injury"},
    {"tag": "Травма спины", "category": "injury"},
    {"tag": "Травма голеностопа", "category": "injury"},
    {"tag": "Начинающий", "category": "level"},
    {"tag": "Средний уровень", "category": "level"},
    {"tag": "Продвинутый", "category": "level"},
    {"tag": "Цель: соревнования", "category": "goal"},
    {"tag": "Цель: для себя", "category": "goal"},
    {"tag": "Только утро", "category": "schedule"},
    {"tag": "Только вечер", "category": "schedule"},
    {"tag": "Выходные", "category": "schedule"},
]


async def list_client_tags(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> list[dict[str, Any]]:
    """List all tags for a client."""
    r = await session.execute(
        text("""
            SELECT id, tag, category, created_at
            FROM trainer_client_tags
            WHERE trainer_id = :tid AND client_id = :cid
            ORDER BY created_at ASC
        """),
        {"tid": trainer_id, "cid": client_id},
    )
    return [
        {
            "id": row[0],
            "tag": row[1],
            "category": row[2],
            "created_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
        }
        for row in r.fetchall()
    ]


async def add_client_tag(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    tag: str,
    category: str | None = None,
) -> dict[str, Any] | None:
    """Add a tag. Returns None if tag already exists."""
    trimmed = (tag or "").strip()[:100]
    if not trimmed:
        raise ValueError("Tag cannot be empty")
    
    cat = (category or "custom").strip()[:50]
    if cat not in TAG_CATEGORIES:
        cat = "custom"
    
    try:
        r = await session.execute(
            text("""
                INSERT INTO trainer_client_tags (trainer_id, client_id, tag, category)
                VALUES (:tid, :cid, :tag, :cat)
                ON CONFLICT (trainer_id, client_id, tag) DO NOTHING
                RETURNING id, tag, category, created_at
            """),
            {"tid": trainer_id, "cid": client_id, "tag": trimmed, "cat": cat},
        )
        row = r.fetchone()
        await session.commit()
        if not row:
            return None  # Already exists
        return {
            "id": row[0],
            "tag": row[1],
            "category": row[2],
            "created_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
        }
    except Exception:
        await session.rollback()
        return None


async def remove_client_tag(
    session: AsyncSession,
    trainer_id: int,
    tag_id: int,
) -> bool:
    """Remove a tag by ID. Returns True if deleted."""
    r = await session.execute(
        text("""
            DELETE FROM trainer_client_tags
            WHERE id = :id AND trainer_id = :tid
            RETURNING id
        """),
        {"id": tag_id, "tid": trainer_id},
    )
    deleted = r.fetchone() is not None
    await session.commit()
    return deleted


# --- Full dossier (combined) ---


async def get_full_client_dossier(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    entries_limit: int = 20,
) -> dict[str, Any]:
    """Get complete dossier: profile + tags + recent entries."""
    profile = await get_client_dossier_profile(session, trainer_id, client_id)
    tags = await list_client_tags(session, trainer_id, client_id)
    entries = await list_client_entries(session, trainer_id, client_id, limit=entries_limit)
    
    return {
        "profile": profile,
        "tags": tags,
        "entries": entries,
        "suggested_tags": SUGGESTED_TAGS,
    }
