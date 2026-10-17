"""Напоминания, подтверждение, перенос, отмена сеанса, правка карточек.

Планировщик идемпотентный: напоминание помечается отправленным до повторного тика,
одинаковый хэш карточки не правится.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_company.copy import (
    Snap,
    after_dm,
    cancel_dm,
    confirm_dm,
    day_reminder,
    followup_dm,
    hour_going,
    hour_maybe,
    join_dm,
    moved_dm,
    weekly_dm,
)
from src.application.ice_company.safety import callback_data
from src.application.ice_company.service import (
    _going_names,
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


def buttons_for(company: dict[str, Any], snap: Snap, page_url: str) -> list[dict[str, str]]:
    code = str(company["public_code"])
    if snap.cancelled or snap.expired or snap.status in ("cancelled", "expired"):
        return [{"text": "На лёд", "url": page_url}]
    return [
        {"text": "Иду", "data": callback_data(code, "g")},
        {"text": "Не могу", "data": callback_data(code, "x")},
        {"text": "На лёд", "url": page_url},
    ]


def button_rows(buttons: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    """Ответы в одном ряду. «На лёд» отдельно: в общем ряду телефон оставляет «На»."""
    actions = [button for button in buttons if not button.get("url")]
    links = [button for button in buttons if button.get("url")]
    rows: list[list[dict[str, str]]] = []
    if actions:
        rows.append(actions)
    rows.extend([link] for link in links)
    return rows


def render_hash(body: str, buttons: list[dict[str, str]]) -> str:
    raw = body + "\n" + json.dumps(buttons, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _page(settings: Settings, code: str) -> str:
    base = (settings.webapp_base_url or "").strip().rstrip("/")
    path = f"/k/{code}"
    return f"{base}{path}" if base else path


def _chat_id(participant_key: str) -> int | None:
    if not participant_key.startswith("tg:"):
        return None
    raw = participant_key[3:]
    return int(raw) if raw.isdigit() else None


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
    stats = {"synced": 0, "expired": 0, "edits": 0, "dms": 0, "skipped": 0}
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
    stats["edits"] += await _edit_dirty(session, sender, settings=cfg, debounce_sec=debounce_sec, now=current)
    # Сбор живёт на карточке в чате. Личные «через час», «выезжаю», «были на льду» не шлём.
    skipped_reminders = await session.execute(
        text("UPDATE ice_company_reminders SET status = 'skipped' WHERE status = 'pending'")
    )
    stats["skipped"] += int(skipped_reminders.rowcount or 0)
    await _purge(session, now=current)
    await session.commit()
    return stats


async def remember_inline_card(session: AsyncSession, *, company_id: int, inline_message_id: str) -> None:
    """Карточка из inline-режима. Id приходит в callback и в chosen_inline_result."""
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
                WHERE card_dirty = true AND status IN ('open', 'confirmed', 'cancelled', 'expired')
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
        body = snap and card_text_of(snap)
        markup = buttons_for(company, snap, page)
        digest = render_hash(body, markup)
        from src.application.ice_company.og import card_photo_url

        photo = card_photo_url(settings.webapp_base_url, str(company["public_code"]), digest)
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


async def _dm(
    sender: Sender,
    session: AsyncSession,
    *,
    chat_id: int,
    body: str,
    buttons: list[dict[str, str]],
    company_id: int,
) -> bool:
    try:
        message_id = await sender.dm(chat_id, body, buttons)
    except BotBlocked:
        await session.execute(
            text(
                """
                UPDATE ice_company_responses
                SET reminders_enabled = false
                WHERE company_id = :id AND participant_key = :key
                """
            ),
            {"id": company_id, "key": f"tg:{chat_id}"},
        )
        return False
    except RateLimited:
        return False
    if message_id:
        await session.execute(
            text(
                """
                INSERT INTO ice_company_messages (company_id, chat_id, message_id, is_group)
                VALUES (:company_id, :chat_id, :message_id, false)
                """
            ),
            {"company_id": company_id, "chat_id": chat_id, "message_id": int(message_id)},
        )
    return True


async def _confirm_dms(session: AsyncSession, sender: Sender, *, settings: Settings) -> int:
    rows = (
        await session.execute(
            text(
                """
                SELECT id, public_code FROM ice_companies
                WHERE status = 'confirmed' AND confirm_notified_at IS NULL
                LIMIT 20
                """
            )
        )
    ).mappings().all()
    sent = 0
    for row in rows:
        company = await _load(session, str(row["public_code"]))
        if company is None:
            continue
        responses = await _responses(session, int(company["id"]))
        snap = snap_from(company, responses)
        body = confirm_dm(snap)
        url = _page(settings, company["public_code"]) + "/event.ics"
        buttons = [{"text": "В календарь", "url": url}]
        for person in responses:
            if person["status"] != "going" or person["needs_reconfirm"] or not person["reminders_enabled"]:
                continue
            chat_id = _chat_id(str(person["participant_key"]))
            if chat_id is None:
                continue
            if await _dm(sender, session, chat_id=chat_id, body=body, buttons=buttons, company_id=int(company["id"])):
                sent += 1
        await session.execute(
            text("UPDATE ice_companies SET confirm_notified_at = now() WHERE id = :id"),
            {"id": company["id"]},
        )
    await session.commit()
    return sent


async def _join_dms(session: AsyncSession, sender: Sender) -> int:
    rows = (
        await session.execute(
            text(
                """
                SELECT r.company_id, r.participant_key, r.display_name, c.organizer_ref, c.public_code
                FROM ice_company_responses r
                JOIN ice_companies c ON c.id = r.company_id
                WHERE c.status = 'confirmed'
                  AND r.status = 'going'
                  AND r.needs_reconfirm = false
                  AND r.join_notified_at IS NULL
                  AND r.participant_key <> c.organizer_ref
                LIMIT 20
                """
            )
        )
    ).mappings().all()
    sent = 0
    for row in rows:
        chat_id = _chat_id(str(row["organizer_ref"]))
        if chat_id is not None:
            if await _dm(
                sender,
                session,
                chat_id=chat_id,
                body=join_dm(str(row["display_name"])),
                buttons=[],
                company_id=int(row["company_id"]),
            ):
                sent += 1
        await session.execute(
            text(
                """
                UPDATE ice_company_responses
                SET join_notified_at = now()
                WHERE company_id = :id AND participant_key = :key
                """
            ),
            {"id": row["company_id"], "key": row["participant_key"]},
        )
    await session.commit()
    return sent


async def _schedule_dms(session: AsyncSession, sender: Sender) -> int:
    rows = (
        await session.execute(
            text(
                """
                SELECT id, public_code FROM ice_companies
                WHERE schedule_notice_pending = true
                LIMIT 20
                """
            )
        )
    ).mappings().all()
    sent = 0
    for row in rows:
        company = await _load(session, str(row["public_code"]))
        if company is None:
            continue
        responses = await _responses(session, int(company["id"]))
        snap = snap_from(company, responses)
        if snap.previous_starts_at is None:
            await session.execute(
                text("UPDATE ice_companies SET schedule_notice_pending = false WHERE id = :id"),
                {"id": company["id"]},
            )
            continue
        body = moved_dm(snap)
        code = str(company["public_code"])
        buttons = [
            {"text": "Иду", "data": callback_data(code, "g")},
            {"text": "Не могу", "data": callback_data(code, "x")},
        ]
        for person in responses:
            if person["status"] not in ("going", "maybe") or not person["reminders_enabled"]:
                continue
            chat_id = _chat_id(str(person["participant_key"]))
            if chat_id is None:
                continue
            if await _dm(sender, session, chat_id=chat_id, body=body, buttons=buttons, company_id=int(company["id"])):
                sent += 1
        await session.execute(
            text("UPDATE ice_companies SET schedule_notice_pending = false, card_dirty = true WHERE id = :id"),
            {"id": company["id"]},
        )
    await session.commit()
    return sent


async def _cancel_dms(session: AsyncSession, sender: Sender) -> int:
    rows = (
        await session.execute(
            text(
                """
                SELECT c.id, c.public_code, e.city_id, e.kind, e.starts_at
                FROM ice_companies c
                JOIN ice_company_events e ON e.id = c.event_id
                WHERE c.cancel_notice_pending = true
                LIMIT 20
                """
            )
        )
    ).mappings().all()
    sent = 0
    for row in rows:
        company = await _load(session, str(row["public_code"]))
        if company is None:
            continue
        alts = (
            await session.execute(
                text(
                    """
                    SELECT a.name, s.starts_at_utc
                    FROM ice_sessions s
                    JOIN arenas a ON a.id = s.arena_id
                    WHERE a.city_id = :city AND s.status = 'active' AND s.kind = :kind
                      AND s.starts_at_utc > now()
                    ORDER BY s.starts_at_utc
                    LIMIT 3
                    """
                ),
                {"city": int(company["city_id"]), "kind": company["event_kind"]},
            )
        ).all()
        lines = [cancel_dm()]
        for name, starts in alts:
            lines.append(f"{name}, {starts.astimezone().strftime('%d.%m %H:%M')}")
        body = "\n".join(lines)
        responses = await _responses(session, int(company["id"]))
        for person in responses:
            if person["status"] not in ("going", "maybe") or not person["reminders_enabled"]:
                continue
            chat_id = _chat_id(str(person["participant_key"]))
            if chat_id is None:
                continue
            if await _dm(sender, session, chat_id=chat_id, body=body, buttons=[], company_id=int(company["id"])):
                sent += 1
        await session.execute(
            text("UPDATE ice_companies SET cancel_notice_pending = false WHERE id = :id"),
            {"id": company["id"]},
        )
    await session.commit()
    return sent


async def _reminders(
    session: AsyncSession,
    sender: Sender,
    *,
    settings: Settings,
    now: datetime,
) -> tuple[int, int]:
    due = (
        await session.execute(
            text(
                """
                SELECT r.id, r.kind, r.company_id, c.public_code, c.organizer_ref, c.min_people, c.created_at
                FROM ice_company_reminders r
                JOIN ice_companies c ON c.id = r.company_id
                WHERE r.status = 'pending' AND r.due_at <= :now
                ORDER BY r.due_at
                LIMIT 30
                FOR UPDATE OF r SKIP LOCKED
                """
            ),
            {"now": now},
        )
    ).mappings().all()
    sent = 0
    skipped = 0
    for row in due:
        company = await _load(session, str(row["public_code"]))
        if company is None or company["status"] in ("cancelled", "expired"):
            await _mark_reminder(session, int(row["id"]), "skipped")
            skipped += 1
            continue
        responses = await _responses(session, int(company["id"]))
        snap = snap_from(company, responses)
        kind = str(row["kind"])
        if kind == "organizer_followup":
            others = [p for p in responses if p["participant_key"] != company["organizer_ref"]]
            chat_id = _chat_id(str(company["organizer_ref"]))
            if others or chat_id is None:
                await _mark_reminder(session, int(row["id"]), "skipped")
                skipped += 1
                continue
            if await _dm(sender, session, chat_id=chat_id, body=followup_dm(), buttons=[], company_id=int(company["id"])):
                sent += 1
            await _mark_reminder(session, int(row["id"]), "sent")
            continue
        if kind == "weekly":
            if not company["weekly_in_chat"]:
                await _mark_reminder(session, int(row["id"]), "skipped")
                skipped += 1
                continue
            body = weekly_dm(snap, were=len(_going_names(responses)), goal=int(company["min_people"]))
            markup = [{"text": "Повторить", "data": callback_data(str(company["public_code"]), "r")}]
            groups = (
                await session.execute(
                    text(
                        """
                        SELECT * FROM ice_company_messages
                        WHERE company_id = :id AND is_group = true
                        """
                    ),
                    {"id": company["id"]},
                )
            ).mappings().all()
            if not groups:
                await _mark_reminder(session, int(row["id"]), "skipped")
                skipped += 1
                continue
            for ref in groups:
                chat_id = ref["chat_id"]
                if chat_id is None:
                    continue
                if await _dm(sender, session, chat_id=int(chat_id), body=body, buttons=markup, company_id=int(company["id"])):
                    sent += 1
            await _mark_reminder(session, int(row["id"]), "sent")
            continue
        targets = [
            person
            for person in responses
            if person["status"] in ("going", "maybe")
            and person["reminders_enabled"]
            and not person["needs_reconfirm"]
            and _chat_id(str(person["participant_key"])) is not None
        ]
        if not targets:
            await _mark_reminder(session, int(row["id"]), "skipped")
            skipped += 1
            continue
        if not await _mark_reminder(session, int(row["id"]), "sent"):
            continue
        await session.commit()
        code = str(company["public_code"])
        for person in targets:
            chat_id = _chat_id(str(person["participant_key"]))
            assert chat_id is not None
            if kind == "day":
                body, markup = day_reminder(snap), [{"text": "Не напоминать", "data": callback_data(code, "q")}]
            elif kind == "hour" and person["status"] == "maybe":
                body = hour_maybe(snap)
                markup = [
                    {"text": "Иду", "data": callback_data(code, "g")},
                    {"text": "Не получится", "data": callback_data(code, "x")},
                ]
            elif kind == "hour":
                body, markup = hour_going(snap), [{"text": "Выезжаю", "data": callback_data(code, "e")}]
            elif kind == "after":
                body = after_dm()
                markup = [
                    {"text": "Были", "data": callback_data(code, "a")},
                    {"text": "Не получилось", "data": callback_data(code, "b")},
                ]
            else:
                continue
            if await _dm(sender, session, chat_id=chat_id, body=body, buttons=markup, company_id=int(company["id"])):
                sent += 1
    await session.commit()
    return sent, skipped


async def _mark_reminder(session: AsyncSession, reminder_id: int, status: str) -> bool:
    # Один и тот же bind дважды даёт AmbiguousParameterError в asyncpg,
    # транзакция откатывается, и тик шлёт то же напоминание снова.
    result = await session.execute(
        text(
            """
            UPDATE ice_company_reminders
            SET status = :status,
                sent_at = CASE WHEN :is_sent THEN now() ELSE sent_at END
            WHERE id = :id AND status = 'pending'
            """
        ),
        {"status": status, "is_sent": status == "sent", "id": reminder_id},
    )
    return result.rowcount == 1


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
    if parts[2] not in {"g", "m", "x", "q", "e", "a", "b", "r"}:
        return None
    return parts[1], parts[2]


ACTION_STATUS = {"g": "going", "m": "maybe", "x": "cant"}
