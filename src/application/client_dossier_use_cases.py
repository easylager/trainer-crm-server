"""
Trainer client dossier: structured profile, timeline entries, and tags.
Extends the simple note into a full client information system.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_client_scope import list_trainer_ids_for_client_crm_scope


# --- Profile (goals, limitations, level, season goal, legacy note) ---


async def get_client_dossier_profile(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> dict[str, Any]:
    """Get profile fields for a client. Returns empty strings if no record."""
    r = await session.execute(
        text("""
            SELECT id, note, goals, limitations, level, season_goal
            FROM trainer_client_notes
            WHERE trainer_id = :tid AND client_id = :cid
        """),
        {"tid": trainer_id, "cid": client_id},
    )
    row = r.fetchone()
    if not row:
        return {
            "note": "",
            "goals": "",
            "limitations": "",
            "level": "",
            "season_goal": "",
        }
    return {
        "id": row[0],
        "note": row[1] or "",
        "goals": row[2] or "",
        "limitations": row[3] or "",
        "level": row[4] or "",
        "season_goal": row[5] or "",
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
    season_goal: str | None = None,
) -> dict[str, Any]:
    """Update profile fields. Only provided fields are updated (None = keep existing)."""
    existing = await get_client_dossier_profile(session, trainer_id, client_id)
    
    final_note = note.strip() if note is not None else existing.get("note", "")
    final_goals = goals.strip() if goals is not None else existing.get("goals", "")
    final_limitations = limitations.strip() if limitations is not None else existing.get("limitations", "")
    final_level = level.strip() if level is not None else existing.get("level", "")
    final_season = (
        season_goal.strip()
        if season_goal is not None
        else existing.get("season_goal", "")
    )

    await session.execute(
        text("""
            INSERT INTO trainer_client_notes (
                trainer_id, client_id, note, goals, limitations, level, season_goal
            )
            VALUES (:tid, :cid, :note, :goals, :limitations, :level, :season_goal)
            ON CONFLICT (trainer_id, client_id)
            DO UPDATE SET 
                note = EXCLUDED.note,
                goals = EXCLUDED.goals,
                limitations = EXCLUDED.limitations,
                level = EXCLUDED.level,
                season_goal = EXCLUDED.season_goal,
                updated_at = now()
        """),
        {
            "tid": trainer_id,
            "cid": client_id,
            "note": final_note,
            "goals": final_goals,
            "limitations": final_limitations,
            "level": final_level,
            "season_goal": final_season,
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


async def add_client_entry_with_date(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    content: str,
    *,
    entry_date: datetime,
) -> dict[str, Any]:
    """Add a timeline entry bound to the provided lesson datetime."""
    trimmed = (content or "").strip()
    if not trimmed:
        raise ValueError("Entry content cannot be empty")

    r = await session.execute(
        text("""
            INSERT INTO trainer_client_entries (trainer_id, client_id, content, created_at)
            VALUES (:tid, :cid, :content, :created_at)
            RETURNING id, content, created_at
        """),
        {
            "tid": trainer_id,
            "cid": client_id,
            "content": trimmed,
            "created_at": entry_date,
        },
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
    "skills": "Навыки",
    "custom": "Другое",
    "system": "Система",
}

# Auto-managed dossier tag when client Family Access has extra Telegram accounts (see sync_family_access_dossier_tags).
DOSSIER_TAG_FAMILY_ACCESS = "Семейный доступ"

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
    {"tag": "Прыжки", "category": "skills"},
    {"tag": "Скольжение", "category": "skills"},
    {"tag": "Вращения", "category": "skills"},
    {"tag": "Баланс", "category": "skills"},
    {"tag": "Техника торможения", "category": "skills"},
    {"tag": "ОФП", "category": "skills"},
    {"tag": "Растяжка", "category": "skills"},
    {"tag": "Программа", "category": "skills"},
    {"tag": "Подготовка к соревнованиям", "category": "skills"},
]

# Quick picks for profile "Цель сезона" (stored as free text; trainer may edit).
SUGGESTED_SEASON_GOALS = [
    "Подготовка к соревнованиям",
    "Постановка программы",
    "Восстановление после перерыва",
    "Научиться кататься с нуля",
    "Подготовка к тестам / разряду",
    "Улучшить технику",
    "Просто кататься для себя",
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


async def sync_family_access_dossier_tags(session: AsyncSession, primary_client_id: int) -> None:
    """
    Mirror Family Access state into dossier tags for the primary client row.
    When extra members exist, ensure tag «Семейный доступ» for every trainer in CRM scope; otherwise remove it.
    No commit — caller owns the transaction (GET dossier commits in route; family flows commit in handler).
    """
    cid = int(primary_client_id)
    r = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM client_family_access_members
            WHERE primary_client_id = :cid
            """
        ),
        {"cid": cid},
    )
    row = r.fetchone()
    n = int(row[0] or 0) if row else 0
    tag = DOSSIER_TAG_FAMILY_ACCESS
    cat = "system"
    if n > 0:
        for trainer_id in await list_trainer_ids_for_client_crm_scope(session, cid):
            await session.execute(
                text(
                    """
                    INSERT INTO trainer_client_tags (trainer_id, client_id, tag, category)
                    VALUES (:tid, :cid, :tag, :cat)
                    ON CONFLICT (trainer_id, client_id, tag)
                    DO UPDATE SET category = EXCLUDED.category
                    """
                ),
                {"tid": int(trainer_id), "cid": cid, "tag": tag, "cat": cat},
            )
    else:
        await session.execute(
            text(
                """
                DELETE FROM trainer_client_tags
                WHERE client_id = :cid AND tag = :tag
                """
            ),
            {"cid": cid, "tag": tag},
        )


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
    if cat == "system":
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
    await sync_family_access_dossier_tags(session, client_id)
    profile = await get_client_dossier_profile(session, trainer_id, client_id)
    tags = await list_client_tags(session, trainer_id, client_id)
    entries = await list_client_entries(session, trainer_id, client_id, limit=entries_limit)
    
    return {
        "profile": profile,
        "tags": tags,
        "entries": entries,
        "suggested_tags": SUGGESTED_TAGS,
        "suggested_season_goals": SUGGESTED_SEASON_GOALS,
    }
