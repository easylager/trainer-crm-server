"""Admin inbox for schedule screenshots (phone → Claude → admin's «да» → published).

Flow: the admin uploads a screenshot for an arena (``pending``); Claude reads it with the
``ice-inbox`` skill and stores a spec (``parsed``); the admin checks it on the phone and
publishes (``published``) or rejects. Nothing reaches the public schedule before that «да».
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.manual_schedule_publish import SpecError, preview_spec, publish_spec
from src.infrastructure import s3

MAX_IMAGE_BYTES = 10 * 1024 * 1024
STATUSES = ("pending", "parsed", "published", "rejected")


class InboxError(ValueError):
    """User-facing failure; ``code`` is stable for the API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _check_image(body: bytes) -> None:
    if not body:
        raise InboxError("empty", "Файл пустой")
    if len(body) > MAX_IMAGE_BYTES:
        raise InboxError("too_large", "Файл больше 10 МБ")
    try:
        from PIL import Image

        with Image.open(io.BytesIO(body)) as img:
            img.verify()
    except Exception as exc:  # noqa: BLE001 — any decoder failure means "not an image"
        raise InboxError("not_image", "Это не картинка") from exc


async def add_upload(
    session: AsyncSession, *, arena_id: int, body: bytes, content_type: str, admin_telegram_id: int | None
) -> int:
    _check_image(body)
    if (await session.execute(text("SELECT 1 FROM arenas WHERE id = :a"), {"a": arena_id})).first() is None:
        raise InboxError("arena_not_found", "Каток не найден")
    file_key = s3.upload_ice_inbox_image(body, content_type or "image/jpeg")
    if not file_key:
        raise InboxError("storage", "Не удалось сохранить файл")
    row = await session.execute(
        text(
            """
            INSERT INTO arena_schedule_inbox (arena_id, file_key, content_type, uploaded_by)
            VALUES (:a, :k, :ct, :by) RETURNING id
            """
        ),
        {"a": arena_id, "k": file_key, "ct": (content_type or "image/jpeg")[:64], "by": admin_telegram_id},
    )
    await session.commit()
    return int(row.scalar_one())


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v is not None else None


def _summary(parsed: dict | None) -> dict[str, Any] | None:
    """Sessions grouped by date for the review screen, plus the notes Claude wants checked."""
    if not parsed:
        return None
    defaults = parsed.get("defaults") or {}
    days: dict[str, list[str]] = {}
    for row in parsed.get("sessions") or []:
        merged = {**defaults, **row}
        label = merged.get("label")
        time_text = f"{merged.get('start')}" + (f" · {label}" if label else "")
        days.setdefault(str(merged.get("date")), []).append(time_text)
    return {
        "count": sum(len(v) for v in days.values()),
        "days": [{"date": d, "times": sorted(t)} for d, t in sorted(days.items())],
        "notes": [str(n) for n in (parsed.get("notes") or [])],
        "source": parsed.get("source"),
    }


_ITEM_SQL = """
    SELECT i.id, i.arena_id, a.name AS arena_name, c.name AS city_name, i.status, i.uploaded_at, i.parsed,
           i.parsed_at, i.published_at, i.published_count, i.note
    FROM arena_schedule_inbox i
    JOIN arenas a ON a.id = i.arena_id
    LEFT JOIN cities c ON c.id = a.city_id
"""


def _item(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "arena_id": row.arena_id,
        "arena_name": row.arena_name,
        "city": row.city_name,
        "status": row.status,
        "uploaded_at": _iso(row.uploaded_at),
        "parsed_at": _iso(row.parsed_at),
        "published_at": _iso(row.published_at),
        "published_count": row.published_count,
        "note": row.note,
        "summary": _summary(row.parsed),
        "image_url": f"/api/webapp/admin/ice-inbox/{row.id}/image",
    }


async def list_inbox(session: AsyncSession) -> dict[str, Any]:
    """Open items first (pending, parsed), then the last 20 finished ones."""
    rows = (
        await session.execute(
            text(
                _ITEM_SQL
                + """
                WHERE i.status IN ('pending', 'parsed')
                   OR i.id IN (SELECT id FROM arena_schedule_inbox WHERE status IN ('published', 'rejected')
                               ORDER BY uploaded_at DESC LIMIT 20)
                ORDER BY (i.status IN ('pending', 'parsed')) DESC, i.uploaded_at DESC
                """
            )
        )
    ).all()
    items = [_item(r) for r in rows]
    return {"items": items, "open": sum(1 for i in items if i["status"] in ("pending", "parsed"))}


async def get_item(session: AsyncSession, inbox_id: int) -> dict[str, Any] | None:
    row = (await session.execute(text(_ITEM_SQL + " WHERE i.id = :id"), {"id": inbox_id})).first()
    return _item(row) if row else None


async def get_image(session: AsyncSession, inbox_id: int) -> tuple[bytes, str] | None:
    row = (
        await session.execute(
            text("SELECT file_key FROM arena_schedule_inbox WHERE id = :id"), {"id": inbox_id}
        )
    ).first()
    if row is None:
        return None
    return s3.get_file(row.file_key, allowed_prefixes=(s3.ICE_INBOX_PREFIX,))


async def submit_parsed(session: AsyncSession, inbox_id: int, spec: dict) -> int:
    """Claude's result. Validates the spec exactly as publishing will; returns the session count."""
    row = (
        await session.execute(
            text("SELECT arena_id, status FROM arena_schedule_inbox WHERE id = :id"), {"id": inbox_id}
        )
    ).first()
    if row is None:
        raise InboxError("not_found", "Нет такой записи")
    if row.status in ("published", "rejected"):
        raise InboxError("closed", "Запись уже закрыта")
    if int(spec.get("arena_id", -1)) != row.arena_id:
        raise InboxError("arena_mismatch", "В расписании указан другой каток")
    try:
        drafts = preview_spec(spec)
    except SpecError as exc:
        raise InboxError("bad_spec", str(exc)) from exc
    if not drafts:
        raise InboxError("empty_spec", "Ни один сеанс не прошёл проверку (прошедшие даты или время)")
    await session.execute(
        text(
            "UPDATE arena_schedule_inbox SET status = 'parsed', parsed = CAST(:p AS jsonb), parsed_at = now() "
            "WHERE id = :id"
        ),
        {"p": json.dumps(spec, ensure_ascii=False), "id": inbox_id},
    )
    await session.commit()
    return len(drafts)


async def reject(session: AsyncSession, inbox_id: int, note: str | None) -> bool:
    res = await session.execute(
        text(
            "UPDATE arena_schedule_inbox SET status = 'rejected', note = :n "
            "WHERE id = :id AND status IN ('pending', 'parsed')"
        ),
        {"id": inbox_id, "n": (note or "").strip()[:500] or None},
    )
    await session.commit()
    return bool(res.rowcount)


async def publish(session: AsyncSession, inbox_id: int) -> int:
    """The admin's «да»: publish the parsed spec through the ingest pipeline."""
    row = (
        await session.execute(
            text("SELECT status, parsed FROM arena_schedule_inbox WHERE id = :id FOR UPDATE"), {"id": inbox_id}
        )
    ).first()
    if row is None:
        raise InboxError("not_found", "Нет такой записи")
    if row.status != "parsed" or not row.parsed:
        raise InboxError("not_parsed", "Расписание ещё не разобрано")
    # Release the row lock before the pipeline opens its own sessions.
    await session.rollback()
    outcomes = await publish_spec(row.parsed)
    record = outcomes[0] if outcomes else None
    if record is None or record.status != "ok":
        detail = getattr(record, "error_message", None) or getattr(record, "status", "нет результата")
        raise InboxError("publish_failed", f"Публикация не прошла: {detail}")
    await session.execute(
        text(
            "UPDATE arena_schedule_inbox SET status = 'published', published_at = :now, published_count = :n "
            "WHERE id = :id"
        ),
        {"id": inbox_id, "now": datetime.now(timezone.utc), "n": record.slot_count},
    )
    await session.commit()
    return int(record.slot_count)
