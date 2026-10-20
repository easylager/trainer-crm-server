"""Правка карточек в чате после ответов и синхронизации сеанса."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_company.copy import MATCH_KIND, Snap, closed_headline
from src.application.ice_company.safety import callback_data
from src.application.ice_company.service import (
    _load,
    _responses,
    _settings,
    ice_slot_url,
    snap_from,
    sync_open_events,
)
from src.shared.config import Settings

logger = logging.getLogger(__name__)

DEBOUNCE_SEC = 1.5
_last_edit: dict[int, float] = {}


class BotBlocked(Exception):
    pass


class RateLimited(Exception):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after


class ChatMigrated(Exception):
    def __init__(self, new_chat_id: int) -> None:
        self.new_chat_id = new_chat_id


class Sender(Protocol):
    async def dm(self, chat_id: int, text: str, buttons: list[dict[str, str]]) -> int: ...

    async def edit(self, ref: dict[str, Any], text: str, buttons: list[dict[str, str]]) -> None: ...


def reset_edit_debounce() -> None:
    _last_edit.clear()


def response_action_buttons(code: str) -> list[dict[str, str]]:
    return [
        {"text": "Иду", "data": callback_data(code, "g"), "style": "primary"},
        {"text": "Не могу", "data": callback_data(code, "x"), "style": "danger"},
    ]


def match_action_buttons(code: str) -> list[dict[str, str]]:
    return [
        {"text": "Иду", "data": callback_data(code, "g"), "style": "primary"},
        {"text": "Смотрю дома", "data": callback_data(code, "m")},
        {"text": "Не смогу", "data": callback_data(code, "x"), "style": "danger"},
    ]


def calendar_url_for(settings: Settings, code: str) -> str:
    return _page(settings, code) + "/event.ics"


def buttons_for(
    company: dict[str, Any],
    snap: Snap,
    page_url: str,
    *,
    calendar_url: str | None = None,
) -> list[dict[str, str]]:
    code = str(company["public_code"])
    if snap.kind == MATCH_KIND:
        # Матч: «Подробнее» ведёт на страницу матча в Mini App, «в другой чат» не нужен (зовут из страницы матча).
        if closed_headline(snap) is not None:
            return [{"text": "Подробнее", "url": page_url}]
        return [*match_action_buttons(code), {"text": "Подробнее", "url": page_url}]
    if closed_headline(snap) is not None:
        return [{"text": "На лёд", "url": page_url}]
    buttons = list(response_action_buttons(code))
    if snap.going_names:
        buttons.append({"text": "В другой чат →", "switch_inline": f"k:{code}"})
    buttons.append({"text": "На лёд", "url": page_url})
    return buttons


def button_rows(buttons: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    return [[button] for button in buttons]


def render_hash(body: str, buttons: list[dict[str, str]]) -> str:
    raw = body + "\n" + json.dumps(buttons, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _page(settings: Settings, code: str) -> str:
    base = (settings.webapp_base_url or "").strip().rstrip("/")
    path = f"/k/{code}"
    return f"{base}{path}" if base else path


async def tick(
    session: AsyncSession,
    sender: Sender,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
    debounce_sec: float = DEBOUNCE_SEC,
) -> dict[str, int]:
    cfg = _settings(settings)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    stats = {"synced": 0, "expired": 0, "edits": 0}
    stats["synced"] = await sync_open_events(session, now=current)
    expired = await session.execute(
        text(
            """
            UPDATE ice_companies c
            SET status = 'expired', card_dirty = true
            FROM ice_company_events e
            WHERE e.id = c.event_id
              AND c.status = 'open'
              AND e.ends_at <= :now
            RETURNING c.id
            """
        ),
        {"now": current},
    )
    stats["expired"] = len(expired.all())
    await session.commit()
    stats["edits"] = await _edit_dirty(session, sender, settings=cfg, debounce_sec=debounce_sec, now=current)
    await _purge(session, now=current)
    await session.commit()
    return stats


async def remember_inline_card(session: AsyncSession, *, company_id: int, inline_message_id: str) -> None:
    inline_id = (inline_message_id or "").strip()
    if not inline_id:
        return
    await session.execute(
        text(
            """
            INSERT INTO ice_company_messages (company_id, inline_message_id, is_group)
            SELECT :company_id, CAST(:inline_id AS varchar(128)), false
            WHERE NOT EXISTS (
                SELECT 1 FROM ice_company_messages
                WHERE company_id = :company_id
                  AND inline_message_id = CAST(:inline_id AS varchar(128))
            )
            """
        ),
        {"company_id": company_id, "inline_id": inline_id},
    )
    await session.execute(
        text("UPDATE ice_companies SET card_dirty = true WHERE id = :id"),
        {"id": company_id},
    )


async def _edit_dirty(
    session: AsyncSession,
    sender: Sender,
    *,
    settings: Settings,
    debounce_sec: float,
    now: datetime,
) -> int:
    rows = (
        await session.execute(
            text(
                """
                SELECT id, public_code FROM ice_companies
                WHERE card_dirty = true AND status IN ('open', 'cancelled', 'expired')
                ORDER BY id
                LIMIT 20
                """
            )
        )
    ).mappings().all()
    edits = 0
    for row in rows:
        company = await _load(session, str(row["public_code"]))
        if company is None:
            continue
        if debounce_sec > 0:
            last = _last_edit.get(int(company["id"]), 0)
            if now.timestamp() - last < debounce_sec:
                continue
        responses = await _responses(session, int(company["id"]))
        snap = snap_from(company, responses)
        page = ice_slot_url(company, settings)
        body = card_text_of(snap)
        code = str(company["public_code"])
        markup = buttons_for(company, snap, page, calendar_url=calendar_url_for(settings, code))
        digest = render_hash(body, markup)
        from src.application.ice_company.og import company_photo

        photo, _ = company_photo(settings.webapp_base_url, company, str(company["public_code"]), digest)
        refs = (
            await session.execute(
                text("SELECT * FROM ice_company_messages WHERE company_id = :id"),
                {"id": company["id"]},
            )
        ).mappings().all()
        for ref in refs:
            if not ref["inline_message_id"]:
                continue
            if ref["last_render_hash"] == digest:
                continue
            payload = dict(ref)
            if photo:
                payload["photo_url"] = photo
            try:
                await sender.edit(payload, body, markup)
            except ChatMigrated as exc:
                await session.execute(
                    text("UPDATE ice_company_messages SET chat_id = :chat WHERE id = :id"),
                    {"chat": exc.new_chat_id, "id": ref["id"]},
                )
                moved = dict(ref)
                moved["chat_id"] = exc.new_chat_id
                await sender.edit(moved, body, markup)
            except RateLimited:
                return edits
            else:
                await session.execute(
                    text("UPDATE ice_company_messages SET last_render_hash = :hash WHERE id = :id"),
                    {"hash": digest, "id": ref["id"]},
                )
                edits += 1
        await session.execute(
            text("UPDATE ice_companies SET card_dirty = false WHERE id = :id"),
            {"id": company["id"]},
        )
        _last_edit[int(company["id"])] = now.timestamp()
    await session.commit()
    return edits


def card_text_of(snap: Snap) -> str:
    from src.application.ice_company.copy import card_text

    return card_text(snap)


async def _purge(session: AsyncSession, *, now: datetime) -> None:
    await session.execute(text("DELETE FROM ice_companies WHERE expires_at < :now"), {"now": now})
    await session.execute(
        text(
            """
            DELETE FROM ice_company_events e
            WHERE NOT EXISTS (SELECT 1 FROM ice_companies c WHERE c.event_id = e.id)
            """
        )
    )


def parse_callback(data: str) -> tuple[str, str] | None:
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != "ic" or len(parts[1]) != 8:
        return None
    if parts[2] not in {"g", "m", "x"}:
        return None
    return parts[1], parts[2]


ACTION_STATUS = {"g": "going", "m": "maybe", "x": "cant"}
