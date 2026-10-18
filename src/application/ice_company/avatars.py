"""Аватарки участников из Telegram для плаката в чате."""

from __future__ import annotations

import io
import logging
from typing import Any, Sequence

from aiogram import Bot
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure import s3
from src.infrastructure.photo_bytes_cache import photo_bytes_cache
from src.shared.config import Settings

logger = logging.getLogger(__name__)

_PREFIX = "ice-company/"
_AVATAR_SIDE = 128


def _storage_key(company_id: int, participant_key: str) -> str:
    safe = participant_key.replace(":", "_").replace("/", "_")[:72]
    return f"{_PREFIX}{int(company_id)}/{safe}.jpg"


def upload_avatar_jpeg(company_id: int, participant_key: str, body: bytes) -> str | None:
    if not body:
        return None
    try:
        image = Image.open(io.BytesIO(body))
        image = image.convert("RGB")
        image.thumbnail((_AVATAR_SIDE, _AVATAR_SIDE), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=82, optimize=True)
        payload = buf.getvalue()
    except Exception:
        logger.info("ice_company avatar resize skipped", exc_info=True)
        return None
    key = _storage_key(company_id, participant_key)
    if not s3.upload_ice_company_avatar(key, payload):
        return None
    photo_bytes_cache.put(key, payload, "image/jpeg")
    return key


def read_avatar_bytes(file_key: str | None) -> bytes | None:
    if not file_key:
        return None
    cached = photo_bytes_cache.get(file_key)
    if cached is not None:
        return cached[0]
    loaded = s3.get_photo(file_key)
    if loaded is None:
        return None
    photo_bytes_cache.put(file_key, loaded[0], loaded[1])
    return loaded[0]


def going_avatar_bytes(rows: Sequence[dict[str, Any]]) -> list[bytes | None]:
    out: list[bytes | None] = []
    for row in rows:
        if row["status"] != "going" or row["needs_reconfirm"]:
            continue
        out.append(read_avatar_bytes(row.get("avatar_file_key")))
    return out


async def cache_telegram_avatar(
    session: AsyncSession,
    bot: Bot,
    *,
    company_id: int,
    participant_key: str,
    telegram_user_id: int,
) -> None:
    if not participant_key.startswith("tg:"):
        return
    existing = (
        await session.execute(
            text(
                """
                SELECT avatar_file_key FROM ice_company_responses
                WHERE company_id = :id AND participant_key = :key
                """
            ),
            {"id": company_id, "key": participant_key},
        )
    ).scalar()
    if existing:
        return
    try:
        photos = await bot.get_user_profile_photos(user_id=int(telegram_user_id), limit=1)
        sizes = (getattr(photos, "photos", None) or [None])[0]
        if not sizes:
            return
        file_id = sizes[-1].file_id
        tg_file = await bot.get_file(file_id)
        buf = await bot.download_file(tg_file.file_path)
        body = buf.read() if hasattr(buf, "read") else bytes(buf)
    except Exception:
        logger.info("ice_company telegram avatar fetch skipped user=%s", telegram_user_id, exc_info=True)
        return
    file_key = upload_avatar_jpeg(company_id, participant_key, body)
    if not file_key:
        return
    await session.execute(
        text(
            """
            UPDATE ice_company_responses
            SET avatar_file_key = :key, updated_at = now()
            WHERE company_id = :id AND participant_key = :participant
            """
        ),
        {"key": file_key, "id": company_id, "participant": participant_key},
    )
    await session.execute(
        text("UPDATE ice_companies SET card_dirty = true WHERE id = :id"),
        {"id": company_id},
    )


async def cache_telegram_avatar_with_token(
    session: AsyncSession,
    settings: Settings | None,
    *,
    company_id: int,
    participant_key: str,
    telegram_user_id: int,
) -> None:
    token = (settings or Settings()).telegram_bot_token_client
    if not (token or "").strip():
        return
    bot = Bot(token)
    try:
        await cache_telegram_avatar(
            session,
            bot,
            company_id=company_id,
            participant_key=participant_key,
            telegram_user_id=telegram_user_id,
        )
        await session.commit()
    finally:
        await bot.session.close()
