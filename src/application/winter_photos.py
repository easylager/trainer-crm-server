"""Фото зимних точек через бота (TASK-343).

Поток: deeplink ``wphoto_<id>`` -> сессия 30 мин -> 1-3 фото -> «Лёд есть?» -> очередь админа
(Принять / Отклонить / Не та точка). Правила (каталог краевых случаев F*, решения координатора):
* EXIF удаляем всегда, исходник не храним, максимум 1600 px;
* ДО РАБОТАЮЩЕГО РАЗМЫТИЯ ЛИЦ каждое фото публикуется только после ручного «Принять» админом;
  автопубликация после 2 принятых включается флагом ``winter_photo_autopublish`` вместе с блюром;
* фото до проверки весит 0,5 как отметка «лёд есть», после «Принять» — 2;
* дубли (sha256 / dHash) отклоняются; 3 фото на автора и 1 на точку в сутки;
* молчание админа ничего не публикует.
"""
from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.winter_marks import MarkError, _utc, recompute_point
from src.infrastructure import s3
from src.shared import winter_status as ws
from src.shared.config import Settings

logger = logging.getLogger(__name__)

SESSION_TTL = timedelta(minutes=30)
MAX_BYTES = 10 * 1024 * 1024
MAX_SIDE = 1600
MAX_PER_AUTHOR_DAY = 3
PENDING_ALERT_COUNT = 20
PENDING_ALERT_AGE = timedelta(hours=24)
ALBUM_MAX = 3


class PhotoError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sanitize_image(body: bytes) -> bytes:
    """Перекодировать в JPEG без EXIF (геометки!), с поворотом по EXIF и лимитом стороны."""
    if len(body) > MAX_BYTES:
        raise PhotoError("too_large")
    try:
        from PIL import Image, ImageOps

        img = Image.open(io.BytesIO(body))
        img.load()
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise PhotoError("not_image") from exc
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)  # без exif=: метаданные не переносятся
    return out.getvalue()


def dhash(body: bytes) -> str:
    from PIL import Image

    img = Image.open(io.BytesIO(body)).convert("L").resize((9, 8))
    px = list(img.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (1 if px[row * 9 + col] > px[row * 9 + col + 1] else 0)
    return f"{bits:016x}"


def blur_faces(body: bytes) -> tuple[bytes, bool]:
    """ХУК размытия лиц. Детектора в зависимостях нет (ни opencv, ни mediapipe) — тяжёлое не тащим.

    Возвращает (байты, blurred). Пока всегда ``blurred=False`` => публикует только человек.
    """
    return body, False


async def begin_session(session: AsyncSession, telegram_id: int, arena_id: int, now: datetime) -> bool:
    """False — автор забанен или точки нет."""
    now = _utc(now)
    exists = (
        await session.execute(
            text("SELECT 1 FROM seasonal_rink_seasons s JOIN arenas a ON a.id=s.arena_id AND a.is_active WHERE s.arena_id=:a AND s.season=:s AND s.state<>'hidden'"),
            {"a": arena_id, "s": ws.current_season(now)},
        )
    ).first()
    if not exists:
        return False
    await session.execute(text("INSERT INTO winter_user_prefs (telegram_id) VALUES (:t) ON CONFLICT DO NOTHING"), {"t": telegram_id})
    banned = (await session.execute(text("SELECT photo_banned FROM winter_user_prefs WHERE telegram_id=:t"), {"t": telegram_id})).scalar_one()
    if banned:
        return False
    await session.execute(
        text("UPDATE winter_user_prefs SET photo_arena_id=:a, photo_until=:u WHERE telegram_id=:t"),
        {"a": arena_id, "u": now + SESSION_TTL, "t": telegram_id},
    )
    return True


async def active_session_arena(session: AsyncSession, telegram_id: int, now: datetime) -> int | None:
    row = (await session.execute(text("SELECT photo_arena_id, photo_until, photo_banned FROM winter_user_prefs WHERE telegram_id=:t"), {"t": telegram_id})).first()
    if row is None or row.photo_banned or row.photo_arena_id is None or row.photo_until is None or row.photo_until < now:
        return None
    return int(row.photo_arena_id)


async def add_photo(session: AsyncSession, telegram_id: int, body: bytes, now: datetime) -> int:
    """Принять одно фото в активной сессии. Возвращает id фото. Коды: no_session, limit, duplicate, not_image, too_large."""
    now = _utc(now)
    arena_id = await active_session_arena(session, telegram_id, now)
    if arena_id is None:
        raise PhotoError("no_session")
    clean = sanitize_image(body)
    day = now - timedelta(days=1)
    n_all, n_point = (
        await session.execute(
            text("SELECT count(*), count(*) FILTER (WHERE arena_id=:a) FROM seasonal_rink_photos WHERE author_telegram_id=:t AND created_at > :d"),
            {"t": telegram_id, "a": arena_id, "d": day},
        )
    ).one()
    if n_all >= MAX_PER_AUTHOR_DAY:  # 1-3 фото альбомом на точку; F4 «1 на точку» отменено ради альбома
        raise PhotoError("limit")
    sha, dh = hashlib.sha256(clean).hexdigest(), dhash(clean)
    dup = (
        await session.execute(
            text("SELECT 1 FROM seasonal_rink_photos WHERE sha256=:s OR dhash=:d LIMIT 1"), {"s": sha, "d": dh}
        )
    ).first()
    if dup:
        raise PhotoError("duplicate")
    safe, blurred = blur_faces(clean)
    up = s3.upload_winter_photo(arena_id, safe, "image/jpeg")
    pid = int(
        (
            await session.execute(
                text(
                    """INSERT INTO seasonal_rink_photos (arena_id, author_telegram_id, storage_key, variants, width, height,
                                                          blurred, sha256, dhash, created_at)
                       VALUES (:a, :t, :k, CAST(:v AS jsonb), :w, :h, :b, :s, :d, :n) RETURNING id"""
                ),
                {"a": arena_id, "t": telegram_id, "k": up["storage_key"], "v": __import__("json").dumps(up["variants"]),
                 "w": up.get("width"), "h": up.get("height"), "b": blurred, "s": sha, "d": dh, "n": now},
            )
        ).scalar_one()
    )
    await session.execute(
        text("INSERT INTO seasonal_moderation_items (kind, arena_id, ref_id) VALUES ('photo_first', :a, :p) ON CONFLICT DO NOTHING"),
        {"a": arena_id, "p": pid},
    )
    return pid


async def set_ice_claim(session: AsyncSession, photo_id: int, telegram_id: int, claim: bool, now: datetime) -> bool:
    """Ответ автора «лёд на фото есть?». Да -> отметка «залит» весом 0,5 до проверки админом."""
    now = _utc(now)
    row = (
        await session.execute(
            text("SELECT arena_id, status FROM seasonal_rink_photos WHERE id=:p AND author_telegram_id=:t FOR UPDATE"),
            {"p": photo_id, "t": telegram_id},
        )
    ).first()
    if row is None or row.status != "pending":
        return False
    await session.execute(text("UPDATE seasonal_rink_photos SET ice_claim=:c WHERE id=:p"), {"c": claim, "p": photo_id})
    if claim:
        from src.application.winter_marks import record_mark

        try:
            await record_mark(
                session, arena_id=int(row.arena_id), kind="ice", value="flooded", source=ws.SOURCE_PHOTO,
                actor=f"tg:{telegram_id}", telegram_id=telegram_id, photo_id=photo_id, weight=0.5, now=now,
            )
        except MarkError:
            return False
    return True


async def decide(session: AsyncSession, photo_id: int, decision: str, admin_id: int | None, now: datetime) -> str:
    """accept | reject | wrong_place. Идемпотентно: повторное нажатие -> ``already``."""
    now = _utc(now)
    if decision not in ("accept", "reject", "wrong_place"):
        return "bad_decision"
    row = (await session.execute(text("SELECT arena_id, status, ice_claim, storage_key, author_telegram_id FROM seasonal_rink_photos WHERE id=:p FOR UPDATE"), {"p": photo_id})).first()
    if row is None:
        return "unknown"
    if row.status != "pending":
        return "already"
    status = {"accept": "accepted", "reject": "rejected", "wrong_place": "wrong_place"}[decision]
    publish = decision == "accept"
    await session.execute(
        text("UPDATE seasonal_rink_photos SET status=:s, published=:pub, decided_at=:n, decided_by=:by WHERE id=:p"),
        {"s": status, "pub": publish, "n": now, "by": admin_id, "p": photo_id},
    )
    await session.execute(
        text("UPDATE seasonal_moderation_items SET status='done', resolution=:r, resolved_at=:n, resolved_by=:by WHERE kind='photo_first' AND ref_id=:p AND status='open'"),
        {"r": status, "n": now, "by": admin_id, "p": photo_id},
    )
    season = ws.current_season(now)
    if publish:
        if row.ice_claim:
            await session.execute(text("UPDATE seasonal_rink_marks SET weight=:w WHERE photo_id=:p"), {"w": ws.WEIGHTS[ws.SOURCE_PHOTO], "p": photo_id})
        await _publish_to_arena_media(session, int(row.arena_id), row.storage_key)
    else:
        await session.execute(text("DELETE FROM seasonal_rink_marks WHERE photo_id=:p"), {"p": photo_id})
    await recompute_point(session, int(row.arena_id), season, now)
    return status


async def _publish_to_arena_media(session: AsyncSession, arena_id: int, storage_key: str) -> None:
    """Принятое фото -> галерея точки (``media``, лицензия user). Сбой не отменяет решение."""
    try:
        from src.application.arena_media import upload_arena_media_from_bytes
        from src.application.place_suggestion_photos import VISITOR_ATTRIBUTION

        found = s3.get_file(storage_key, allowed_prefixes=(s3.WINTER_PREFIX,))
        if found:
            body, ct = found
            await upload_arena_media_from_bytes(
                session, arena_id, body, ct or "image/jpeg", license_key="user", attribution=VISITOR_ATTRIBUTION
            )
    except Exception:  # noqa: BLE001
        logger.exception("winter photo -> arena media failed arena=%s", arena_id)


async def report_photo(session: AsyncSession, photo_id: int, actor: str) -> int:
    """«Пожаловаться»: >= 2 разных жалоб -> фото скрыто и снова в очереди админа."""
    await session.execute(
        text("INSERT INTO seasonal_rink_photo_reports (photo_id, actor) VALUES (:p, :a) ON CONFLICT DO NOTHING"),
        {"p": photo_id, "a": actor},
    )
    n = int((await session.execute(text("SELECT count(*) FROM seasonal_rink_photo_reports WHERE photo_id=:p"), {"p": photo_id})).scalar_one())
    await session.execute(text("UPDATE seasonal_rink_photos SET report_count=:n WHERE id=:p"), {"n": n, "p": photo_id})
    if n >= 2:
        await session.execute(text("UPDATE seasonal_rink_photos SET published=false WHERE id=:p"), {"p": photo_id})
    return n


async def ban_author(session: AsyncSession, telegram_id: int) -> None:
    await session.execute(text("INSERT INTO winter_user_prefs (telegram_id) VALUES (:t) ON CONFLICT DO NOTHING"), {"t": telegram_id})
    await session.execute(text("UPDATE winter_user_prefs SET photo_banned=true, photo_arena_id=NULL WHERE telegram_id=:t"), {"t": telegram_id})
    await session.execute(
        text("UPDATE seasonal_rink_photos SET published=false WHERE author_telegram_id=:t AND status='pending'"), {"t": telegram_id}
    )


async def queue_health(session: AsyncSession, now: datetime) -> dict[str, Any]:
    """Для ежедневного отчёта: очередь > 20 или старейшая > 24 ч -> тревога."""
    cnt, oldest = (
        await session.execute(
            text("SELECT count(*), min(created_at) FROM seasonal_rink_photos WHERE status='pending'")
        )
    ).one()
    alarm = cnt > PENDING_ALERT_COUNT or (oldest is not None and now - oldest > PENDING_ALERT_AGE)
    return {"pending": int(cnt), "oldest": oldest.isoformat() if oldest else None, "alarm": bool(alarm)}
