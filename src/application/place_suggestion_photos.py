"""Фото к заявке «Предложить место» (PDEC-028).

Фото догружаются после создания заявки по ``photo_token`` (живёт 2 часа, стирается при
закрытии). Хранятся приватно под ``suggestions/``: публично не отдаются, админ смотрит их
через свой эндпоинт. При одобрении фото с ``publish=true`` копируются в галерею нового места.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_media import upload_arena_media_from_bytes
from src.application.trainer_use_cases import MAX_TRAINER_PHOTO_BYTES, trainer_photo_bytes_look_like_image
from src.infrastructure import s3

logger = logging.getLogger(__name__)

MAX_PHOTOS = 3
PHOTO_TOKEN_TTL = timedelta(hours=2)
VISITOR_ATTRIBUTION = "по данным посетителей"


class SuggestionPhotoError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def new_photo_token() -> str:
    return secrets.token_urlsafe(16)[:32]


def admin_photo_url(sid: int, photo_id: int) -> str:
    return f"/api/webapp/admin/place-suggestions/{int(sid)}/photos/{int(photo_id)}"


async def add_suggestion_photo(
    session: AsyncSession, sid: int, token: str, body: bytes, content_type: str, *, now: datetime | None = None
) -> dict[str, Any]:
    """Сохранить одно фото. Коды ошибок: ``forbidden`` (нет заявки / чужой или протухший ключ),
    ``limit``, ``too_large``, ``not_image``. Commit внутри."""
    row = (
        await session.execute(
            text("SELECT photo_token, created_at, status FROM place_suggestions WHERE id = :id FOR UPDATE"),
            {"id": int(sid)},
        )
    ).first()
    moment = now or datetime.now(timezone.utc)
    if (
        row is None
        or not row.photo_token
        or not token
        or not secrets.compare_digest(str(row.photo_token), str(token))
        or row.status not in ("new", "needs_info")
        or row.created_at + PHOTO_TOKEN_TTL < moment
    ):
        raise SuggestionPhotoError("forbidden")
    count = int(
        (
            await session.execute(
                text("SELECT COUNT(*) FROM place_suggestion_photos WHERE suggestion_id = :id"), {"id": int(sid)}
            )
        ).scalar_one()
    )
    if count >= MAX_PHOTOS:
        raise SuggestionPhotoError("limit")
    if len(body) > MAX_TRAINER_PHOTO_BYTES:
        raise SuggestionPhotoError("too_large")
    if not trainer_photo_bytes_look_like_image(body):
        raise SuggestionPhotoError("not_image")
    uploaded = s3.upload_suggestion_photo(int(sid), body, content_type)

    r = await session.execute(
        text(
            """
            INSERT INTO place_suggestion_photos (suggestion_id, storage_key, variants, width, height)
            VALUES (:sid, :key, CAST(:variants AS jsonb), :w, :h)
            RETURNING id
            """
        ),
        {
            "sid": int(sid),
            "key": uploaded["storage_key"],
            "variants": json.dumps(uploaded["variants"]),
            "w": uploaded.get("width"),
            "h": uploaded.get("height"),
        },
    )
    pid = int(r.scalar_one())
    await session.commit()
    return {"id": pid}


async def list_suggestion_photos(session: AsyncSession, sid: int) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT id, width, height, publish FROM place_suggestion_photos "
            "WHERE suggestion_id = :id ORDER BY id"
        ),
        {"id": int(sid)},
    )
    return [
        {"id": int(r.id), "url": admin_photo_url(sid, r.id), "width": r.width, "height": r.height, "publish": bool(r.publish)}
        for r in rows
    ]


async def set_photo_publish(session: AsyncSession, sid: int, photo_id: int, publish: bool) -> bool:
    r = await session.execute(
        text(
            "UPDATE place_suggestion_photos SET publish = :p WHERE id = :pid AND suggestion_id = :sid"
        ),
        {"p": bool(publish), "pid": int(photo_id), "sid": int(sid)},
    )
    await session.commit()
    return bool(r.rowcount)


async def get_photo_bytes(session: AsyncSession, sid: int, photo_id: int) -> tuple[bytes, str] | None:
    row = (
        await session.execute(
            text("SELECT variants, storage_key FROM place_suggestion_photos WHERE id = :pid AND suggestion_id = :sid"),
            {"pid": int(photo_id), "sid": int(sid)},
        )
    ).first()
    if row is None:
        return None
    key = (row.variants or {}).get("card") or row.storage_key
    return s3.get_file(key, allowed_prefixes=(s3.SUGGESTIONS_PREFIX,))


async def copy_photos_to_arena(session: AsyncSession, sid: int, arena_id: int) -> int:
    """Фото с ``publish=true`` → ``media`` места (лицензия ``user``). Не коммитит.
    Сбой чтения одного фото не мешает остальным и одобрению."""
    rows = (
        await session.execute(
            text(
                "SELECT id, storage_key FROM place_suggestion_photos "
                "WHERE suggestion_id = :sid AND publish ORDER BY id"
            ),
            {"sid": int(sid)},
        )
    ).all()
    copied = 0
    for r in rows:
        found = s3.get_file(r.storage_key, allowed_prefixes=(s3.SUGGESTIONS_PREFIX,))
        if found is None:
            logger.warning("suggestion photo missing sid=%s photo=%s", sid, r.id)
            continue
        body, content_type = found
        await upload_arena_media_from_bytes(
            session, int(arena_id), body, content_type or "image/jpeg",
            license_key="user", attribution=VISITOR_ATTRIBUTION,
        )
        copied += 1
    return copied
