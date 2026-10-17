"""Создание компании, ответ, отмена, удаление своих данных, повтор.

Порог min_people — цель, не потолок: ответы принимаем и после него.
max_people хранится и никого не отсекает.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_consumer_events import (
    CATALOG_CONSUMER_KINDS,
    public_actor_hash,
    telegram_actor_hash,
)
from src.application.ice_company.codes import new_public_code, new_web_token, tg_participant_key, web_participant_key
from src.application.ice_company.copy import Snap, card_text, together_line
from src.application.ice_company.flag import city_enabled
from src.application.ice_company.reminders import plan
from src.application.ice_company.safety import TextRejected, clean_free_text
from src.shared.config import Settings

logger = logging.getLogger(__name__)

_SKATE = ("public_skate", "open_ice", "hockey_practice")
_OPEN = ("open", "confirmed")


class CompanyRejected(Exception):
    def __init__(self, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current


def _settings(settings: Settings | None) -> Settings:
    return settings or Settings()


async def _track(
    session: AsyncSession,
    *,
    kind: str,
    city_id: int | None,
    arena_id: int | None,
    payload: dict[str, Any],
    actor_hash: str | None,
) -> None:
    if kind not in CATALOG_CONSUMER_KINDS:
        return
    try:
        async with session.begin_nested():
            await session.execute(
                text(
                    """
                    INSERT INTO catalog_consumer_events
                        (kind, surface, actor_hash, city_id, arena_id, payload)
                    VALUES
                        (:kind, 'ice_company', :actor, :city_id, :arena_id, CAST(:payload AS jsonb))
                    """
                ),
                {
                    "kind": kind,
                    "actor": actor_hash,
                    "city_id": city_id,
                    "arena_id": arena_id,
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            )
    except Exception:
        logger.info("ice_company analytics skipped kind=%s", kind)


async def _session_row(session: AsyncSession, session_id: int) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT s.id, s.kind, s.status, s.starts_at_utc, s.ends_at_utc, s.arena_id,
                       a.city_id, a.name AS arena_name
                FROM ice_sessions s
                JOIN arenas a ON a.id = s.arena_id
                WHERE s.id = :id
                """
            ),
            {"id": int(session_id)},
        )
    ).mappings().first()
    return dict(row) if row else None


def _arena_id(venue_ref: str) -> int | None:
    prefix = "arena:"
    if not str(venue_ref).startswith(prefix):
        return None
    raw = str(venue_ref)[len(prefix) :]
    return int(raw) if raw.isdigit() else None


async def _load(session: AsyncSession, code: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT c.*, e.kind AS event_kind, e.source_ref, e.starts_at, e.ends_at,
                       e.previous_starts_at, e.venue_ref, e.venue_label, e.city_id,
                       e.version AS live_version, e.cancelled AS event_cancelled
                FROM ice_companies c
                JOIN ice_company_events e ON e.id = c.event_id
                WHERE c.public_code = :code
                """
            ),
            {"code": code},
        )
    ).mappings().first()
    return dict(row) if row else None


async def _responses(session: AsyncSession, company_id: int) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT participant_key, display_name, status, attended, reminders_enabled,
                       needs_reconfirm, departing, source, join_notified_at, updated_at
                FROM ice_company_responses
                WHERE company_id = :id
                ORDER BY updated_at, id
                """
            ),
            {"id": company_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def _going_names(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        str(row["display_name"])
        for row in rows
        if row["status"] == "going" and not row["needs_reconfirm"]
    )


def snap_from(company: dict[str, Any], rows: list[dict[str, Any]]) -> Snap:
    status = str(company["status"])
    return Snap(
        kind=str(company["event_kind"]),
        venue=str(company["venue_label"]),
        starts_at=company["starts_at"],
        min_people=int(company["min_people"]),
        status=status,
        going_names=_going_names(rows),
        previous_starts_at=company["previous_starts_at"] if any(row["needs_reconfirm"] for row in rows) else None,
        cancelled=bool(company["event_cancelled"]) or status == "cancelled" and bool(company.get("cancel_notice_pending")),
        expired=status == "expired",
    )


def _page_url(settings: Settings, code: str) -> str:
    base = (settings.webapp_base_url or "").strip().rstrip("/")
    path = f"/k/{code}"
    return f"{base}{path}" if base else path


def _session_id(source_ref: str) -> int | None:
    prefix = "ice_session:"
    if not str(source_ref).startswith(prefix):
        return None
    raw = str(source_ref)[len(prefix) :]
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def ice_slot_url(company: dict[str, Any], settings: Settings) -> str:
    """«На лёд» открывает мини-приложение на этом сеансе.

    Кнопка на карточке в чате — ссылка ``t.me/<бот>?startapp=arena_<id>_s_<сеанс>``.
    Telegram открывает её как мини-приложение, если в BotFather задан Main Mini App.
    Прямая кнопка web_app на таком сообщении не ставится: её принимает только личный чат с ботом.
    """
    from urllib.parse import urlencode

    from src.application.place_links import place_start_param, telegram_open_link

    arena_id = _arena_id(str(company.get("venue_ref") or ""))
    session_id = _session_id(str(company.get("source_ref") or ""))
    if arena_id:
        link = telegram_open_link(
            client_bot_username=settings.client_bot_username,
            mini_app_short_name=settings.client_mini_app_short_name,
            start_param=place_start_param(arena_id, session_id),
            main_mini_app=settings.client_bot_main_mini_app,
        )
        if link:
            return link
    base = (settings.webapp_base_url or "").strip().rstrip("/")
    if arena_id and base.lower().startswith("https://"):
        params = {"ref": str(arena_id)}
        if session_id is not None:
            params["s"] = str(session_id)
        return f"{base}/webapp/arena?" + urlencode(params)
    return _page_url(settings, str(company["public_code"]))


def public_view(
    company: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    settings: Settings,
    together: int = 0,
) -> dict[str, Any]:
    going = [
        {"display_name": row["display_name"]}
        for row in rows
        if row["status"] == "going" and not row["needs_reconfirm"]
    ]
    maybe = [
        {"display_name": row["display_name"]}
        for row in rows
        if row["status"] == "maybe" and not row["needs_reconfirm"]
    ]
    cant = sum(1 for row in rows if row["status"] == "cant")
    snap = snap_from(company, rows)
    payload: dict[str, Any] = {
        "public_code": company["public_code"],
        "name": company["name"],
        "status": company["status"],
        "min_people": int(company["min_people"]),
        "max_people": company["max_people"],
        "going_count": len(going),
        "maybe_count": len(maybe),
        "cant_count": cant,
        "going": going,
        "maybe": maybe,
        "needs_reconfirm": any(bool(row["needs_reconfirm"]) for row in rows),
        "card_text": card_text(snap),
        "together_line": together_line(together) if together else "",
        "event": {
            "kind": company["event_kind"],
            "starts_at": company["starts_at"].isoformat(),
            "ends_at": company["ends_at"].isoformat(),
            "venue_label": company["venue_label"],
            "venue_ref": company["venue_ref"],
            "version": int(company["live_version"]),
            "cancelled": bool(company["event_cancelled"]),
        },
        "page_url": _page_url(settings, company["public_code"]),
        "calendar_url": _page_url(settings, company["public_code"]) + "/event.ics",
    }
    return payload


async def _together(session: AsyncSession, company_id: int, rows: list[dict[str, Any]], viewer: str | None) -> int:
    if not viewer:
        return 0
    others = [
        row["participant_key"]
        for row in rows
        if row["status"] == "going" and row["participant_key"] != viewer
    ]
    if not others:
        return 0
    value = (
        await session.execute(
            text(
                """
                SELECT COUNT(DISTINCT c.id)
                FROM ice_companies c
                JOIN ice_company_events e ON e.id = c.event_id
                JOIN ice_company_responses me
                  ON me.company_id = c.id AND me.participant_key = :me AND me.status = 'going'
                JOIN ice_company_responses other
                  ON other.company_id = c.id AND other.participant_key = ANY(:others) AND other.status = 'going'
                WHERE c.id <> :current AND c.status = 'confirmed' AND e.ends_at < now()
                """
            ),
            {"me": viewer, "others": others, "current": company_id},
        )
    ).scalar()
    return int(value or 0)


async def read_company(
    session: AsyncSession,
    code: str,
    *,
    viewer_key: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    company = await _load(session, code)
    if company is None:
        return None
    rows = await _responses(session, int(company["id"]))
    together = await _together(session, int(company["id"]), rows, viewer_key)
    return public_view(company, rows, settings=_settings(settings), together=together)


async def _insert_event(session: AsyncSession, slot: dict[str, Any]) -> int:
    source = f"ice_session:{int(slot['id'])}"
    existing = (
        await session.execute(
            text("SELECT id, starts_at, venue_ref, cancelled, version FROM ice_company_events WHERE source_ref = :src"),
            {"src": source},
        )
    ).mappings().first()
    venue_ref = f"arena:{int(slot['arena_id'])}"
    cancelled = str(slot["status"]) == "cancelled"
    if existing is None:
        row = (
            await session.execute(
                text(
                    """
                    INSERT INTO ice_company_events (
                        kind, source_ref, starts_at, ends_at, venue_ref, venue_label, city_id,
                        version, cancelled
                    ) VALUES (
                        :kind, :src, :starts, :ends, :venue, :label, :city, 1, :cancelled
                    )
                    RETURNING id
                    """
                ),
                {
                    "kind": slot["kind"],
                    "src": source,
                    "starts": slot["starts_at_utc"],
                    "ends": slot["ends_at_utc"],
                    "venue": venue_ref,
                    "label": str(slot["arena_name"])[:120],
                    "city": int(slot["city_id"]),
                    "cancelled": cancelled,
                },
            )
        ).first()
        return int(row[0])
    return int(existing["id"])


async def _schedule_reminders(
    session: AsyncSession,
    company_id: int,
    *,
    created_at: datetime,
    starts_at: datetime,
    ends_at: datetime,
    weekly_in_chat: bool,
) -> None:
    for kind, due_at, status in plan(
        created_at=created_at,
        starts_at=starts_at,
        ends_at=ends_at,
        weekly_in_chat=weekly_in_chat,
    ):
        await session.execute(
            text(
                """
                INSERT INTO ice_company_reminders (company_id, kind, due_at, status)
                VALUES (:company_id, :kind, :due_at, :status)
                ON CONFLICT (company_id, kind) DO NOTHING
                """
            ),
            {"company_id": company_id, "kind": kind, "due_at": due_at, "status": status},
        )


async def create_company(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    session_id: int,
    min_people: int,
    display_name: str,
    name: str = "",
    max_people: int | None = None,
    surface: str = "miniapp",
    now: datetime | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    cfg = _settings(settings)
    current = _now(now)
    slot = await _session_row(session, session_id)
    if slot is None or slot["kind"] not in _SKATE:
        raise CompanyRejected("Сеанс не найден.", 404)
    if not city_enabled(int(slot["city_id"]), cfg):
        raise CompanyRejected("Сбор компании в этом городе пока выключен.", 404)
    if str(slot["status"]) != "active" or slot["starts_at_utc"] <= current:
        raise CompanyRejected("Этот сеанс уже нельзя собрать.", 422)
    try:
        min_n = int(min_people)
    except (TypeError, ValueError):
        raise CompanyRejected("Укажите, сколько человек нужно.") from None
    if min_n < 1 or min_n > 30:
        raise CompanyRejected("Нужно от 1 до 30.")
    if max_people is not None and int(max_people) < min_n:
        raise CompanyRejected("Верхняя цифра меньше порога.")
    try:
        label = clean_free_text(display_name, max_len=cfg.ice_company_display_name_max_len, required=True, field="Имя")
        title = clean_free_text(name, max_len=cfg.ice_company_name_max_len, required=False, field="Название")
    except TextRejected as exc:
        raise CompanyRejected(exc.detail) from exc
    organizer = tg_participant_key(telegram_user_id)
    active = (
        await session.execute(
            text(
                """
                SELECT COUNT(*) FROM ice_companies c
                JOIN ice_company_events e ON e.id = c.event_id
                WHERE c.organizer_ref = :ref
                  AND c.status IN ('open', 'confirmed')
                  AND e.starts_at > :now
                """
            ),
            {"ref": organizer, "now": current},
        )
    ).scalar()
    if int(active or 0) >= cfg.ice_company_max_active_per_organizer:
        raise CompanyRejected("Уже есть пять активных компаний.", 429)
    event_id = await _insert_event(session, slot)
    event = (
        await session.execute(
            text("SELECT version, starts_at, ends_at FROM ice_company_events WHERE id = :id"),
            {"id": event_id},
        )
    ).mappings().one()
    code = ""
    company_id = 0
    for _ in range(8):
        code = new_public_code()
        try:
            async with session.begin_nested():
                inserted = (
                    await session.execute(
                        text(
                            """
                            INSERT INTO ice_companies (
                                public_code, name, organizer_ref, event_id, event_version,
                                min_people, max_people, status, expires_at
                            ) VALUES (
                                :code, :name, :organizer, :event_id, :version,
                                :min_people, :max_people, 'open', :expires_at
                            )
                            RETURNING id
                            """
                        ),
                        {
                            "code": code,
                            "name": title,
                            "organizer": organizer,
                            "event_id": event_id,
                            "version": int(event["version"]),
                            "min_people": min_n,
                            "max_people": max_people,
                            "expires_at": event["ends_at"] + timedelta(days=cfg.ice_company_retention_days),
                        },
                    )
                ).mappings().one()
            company_id = int(inserted["id"])
            break
        except IntegrityError:
            code = ""
            continue
    if not code:
        raise CompanyRejected("Не получилось создать компанию. Попробуйте ещё раз.", 503)
    await session.execute(
        text(
            """
            INSERT INTO ice_company_responses (
                company_id, participant_key, display_name, status, source
            ) VALUES (:company_id, :key, :name, 'going', 'tg')
            """
        ),
        {"company_id": company_id, "key": organizer, "name": label},
    )
    await _refresh_status(session, company_id)
    await _track(
        session,
        kind="company_created",
        city_id=int(slot["city_id"]),
        arena_id=int(slot["arena_id"]),
        payload={"surface": surface, "min_people": min_n},
        actor_hash=telegram_actor_hash(telegram_user_id),
    )
    await session.commit()
    view = await read_company(session, code, viewer_key=organizer, settings=cfg)
    assert view is not None
    return view


async def _refresh_status(session: AsyncSession, company_id: int) -> str:
    company = (
        await session.execute(
            text("SELECT status, min_people FROM ice_companies WHERE id = :id FOR UPDATE"),
            {"id": company_id},
        )
    ).mappings().one()
    going = (
        await session.execute(
            text(
                """
                SELECT COUNT(*) FROM ice_company_responses
                WHERE company_id = :id AND status = 'going' AND needs_reconfirm = false
                """
            ),
            {"id": company_id},
        )
    ).scalar()
    status = str(company["status"])
    if status not in _OPEN:
        return status
    met = int(going or 0) >= int(company["min_people"])
    new_status = "confirmed" if met else "open"
    if new_status != status:
        await session.execute(
            text("UPDATE ice_companies SET status = :status, card_dirty = true WHERE id = :id"),
            {"status": new_status, "id": company_id},
        )
        if new_status == "confirmed":
            await session.execute(
                text(
                    """
                    UPDATE ice_company_responses
                    SET join_notified_at = now()
                    WHERE company_id = :id AND join_notified_at IS NULL
                    """
                ),
                {"id": company_id},
            )
    else:
        await session.execute(
            text("UPDATE ice_companies SET card_dirty = true WHERE id = :id"),
            {"id": company_id},
        )
    return new_status


async def respond(
    session: AsyncSession,
    *,
    code: str,
    status: str,
    display_name: str | None,
    participant_key: str,
    source: str,
    consent: bool,
    now: datetime | None = None,
    settings: Settings | None = None,
    actor_hash: str | None = None,
    action: str = "status",
) -> dict[str, Any]:
    """Повторный ответ того же ключа меняет статус. action: status|quiet|depart|attended|missed."""
    cfg = _settings(settings)
    company = await _load(session, code)
    if company is None:
        raise CompanyRejected("Компания не найдена.", 404)
    if str(company["status"]) in ("cancelled", "expired") or bool(company["event_cancelled"]):
        raise CompanyRejected("Сбор уже закрыт.", 409)
    rows_before = await _responses(session, int(company["id"]))
    if len(rows_before) >= cfg.ice_company_max_responses and not any(
        row["participant_key"] == participant_key for row in rows_before
    ):
        raise CompanyRejected("В этой компании уже много ответов.", 429)
    existing = next((row for row in rows_before if row["participant_key"] == participant_key), None)
    if existing is None and source in ("web", "viber") and not consent:
        raise CompanyRejected("Нужно согласие, прежде чем ответить.", 422)
    if action == "quiet":
        if existing is None:
            raise CompanyRejected("Сначала ответьте, идёте ли вы.", 422)
        await session.execute(
            text(
                """
                UPDATE ice_company_responses
                SET reminders_enabled = false, updated_at = now()
                WHERE company_id = :id AND participant_key = :key
                """
            ),
            {"id": company["id"], "key": participant_key},
        )
        await _track(
            session,
            kind="company_unsubscribed",
            city_id=int(company["city_id"]),
            arena_id=_arena_id(str(company["venue_ref"])),
            payload={"source": source},
            actor_hash=actor_hash,
        )
        await session.commit()
        view = await read_company(session, code, viewer_key=participant_key, settings=cfg)
        assert view is not None
        return view
    if action in ("attended", "missed"):
        if existing is None or existing["status"] not in ("going", "maybe"):
            raise CompanyRejected("Этот вопрос для тех, кто собирался.", 422)
        if _now(now) < company["ends_at"]:
            raise CompanyRejected("Сеанс ещё не закончился.", 422)
        await session.execute(
            text(
                """
                UPDATE ice_company_responses
                SET attended = :attended, updated_at = now()
                WHERE company_id = :id AND participant_key = :key
                """
            ),
            {"attended": action == "attended", "id": company["id"], "key": participant_key},
        )
        await _track(
            session,
            kind="company_attended",
            city_id=int(company["city_id"]),
            arena_id=_arena_id(str(company["venue_ref"])),
            payload={"attended": action == "attended"},
            actor_hash=actor_hash,
        )
        await session.commit()
        view = await read_company(session, code, viewer_key=participant_key, settings=cfg)
        assert view is not None
        return view
    if action == "depart":
        if existing is None or existing["status"] != "going":
            raise CompanyRejected("Выезд отмечают те, кто идёт.", 422)
        await session.execute(
            text(
                """
                UPDATE ice_company_responses
                SET departing = true, updated_at = now()
                WHERE company_id = :id AND participant_key = :key
                """
            ),
            {"id": company["id"], "key": participant_key},
        )
        await session.commit()
        view = await read_company(session, code, viewer_key=participant_key, settings=cfg)
        assert view is not None
        return view
    if status not in ("going", "maybe", "cant"):
        raise CompanyRejected("Ответ: иду, может быть или не могу.")
    kept = existing["display_name"] if existing and source == "tg" else None
    try:
        label = clean_free_text(
            kept or display_name or (existing["display_name"] if existing else None) or ("Участник" if source == "tg" else None),
            max_len=cfg.ice_company_display_name_max_len,
            required=True,
            field="Имя",
        )
    except TextRejected as exc:
        raise CompanyRejected(exc.detail) from exc
    was_going = bool(existing and existing["status"] == "going" and not existing["needs_reconfirm"])
    await session.execute(
        text(
            """
            INSERT INTO ice_company_responses (
                company_id, participant_key, display_name, status, source, needs_reconfirm
            ) VALUES (
                :company_id, :key, :name, :status, :source, false
            )
            ON CONFLICT (company_id, participant_key) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                status = EXCLUDED.status,
                source = EXCLUDED.source,
                needs_reconfirm = false,
                updated_at = now()
            """
        ),
        {
            "company_id": company["id"],
            "key": participant_key,
            "name": label,
            "status": status,
            "source": source,
        },
    )
    before = str(company["status"])
    after = await _refresh_status(session, int(company["id"]))
    if after == "confirmed" and before != "confirmed":
        await _track(
            session,
            kind="company_confirmed",
            city_id=int(company["city_id"]),
            arena_id=_arena_id(str(company["venue_ref"])),
            payload={"min_people": int(company["min_people"])},
            actor_hash=actor_hash,
        )
    if (
        before == "confirmed"
        and after == "confirmed"
        and status == "going"
        and not was_going
        and participant_key != company["organizer_ref"]
    ):
        await session.execute(
            text(
                """
                UPDATE ice_company_responses
                SET join_notified_at = NULL
                WHERE company_id = :id AND participant_key = :key
                """
            ),
            {"id": company["id"], "key": participant_key},
        )
    await _track(
        session,
        kind="company_response",
        city_id=int(company["city_id"]),
        arena_id=_arena_id(str(company["venue_ref"])),
        payload={"source": source, "status": status},
        actor_hash=actor_hash,
    )
    await session.commit()
    view = await read_company(session, code, viewer_key=participant_key, settings=cfg)
    assert view is not None
    return view


def resolve_participant(
    *,
    telegram_user_id: int | None,
    raw_token: str | None,
    source: str,
) -> tuple[str, str | None]:
    """Возвращает ключ и новый веб-токен, если его выпустили сейчас."""
    if telegram_user_id is not None:
        return tg_participant_key(telegram_user_id), None
    if raw_token:
        return web_participant_key(raw_token), None
    if source not in ("web", "viber"):
        raise CompanyRejected("Нужен вход через Telegram.", 401)
    raw, key = new_web_token()
    return key, raw


async def cancel_company(
    session: AsyncSession,
    *,
    code: str,
    telegram_user_id: int,
    settings: Settings | None = None,
) -> dict[str, Any]:
    company = await _require_organizer(session, code, telegram_user_id)
    await session.execute(
        text(
            """
            UPDATE ice_companies
            SET status = 'cancelled', card_dirty = true
            WHERE id = :id
            """
        ),
        {"id": company["id"]},
    )
    await session.commit()
    view = await read_company(session, code, settings=_settings(settings))
    assert view is not None
    return view


async def delete_own(
    session: AsyncSession,
    *,
    code: str,
    participant_key: str,
    settings: Settings | None = None,
) -> None:
    company = await _load(session, code)
    if company is None:
        raise CompanyRejected("Компания не найдена.", 404)
    await session.execute(
        text(
            "DELETE FROM ice_company_responses WHERE company_id = :id AND participant_key = :key"
        ),
        {"id": company["id"], "key": participant_key},
    )
    if participant_key == company["organizer_ref"]:
        await session.execute(
            text("UPDATE ice_companies SET organizer_ref = 'deleted', card_dirty = true WHERE id = :id"),
            {"id": company["id"]},
        )
    await _refresh_status(session, int(company["id"]))
    await session.commit()


async def set_weekly(
    session: AsyncSession,
    *,
    code: str,
    telegram_user_id: int,
    enabled: bool,
    settings: Settings | None = None,
) -> dict[str, Any]:
    company = await _require_organizer(session, code, telegram_user_id)
    await session.execute(
        text("UPDATE ice_companies SET weekly_in_chat = :enabled WHERE id = :id"),
        {"enabled": bool(enabled), "id": company["id"]},
    )
    if enabled:
        await _schedule_reminders(
            session,
            int(company["id"]),
            created_at=company["created_at"],
            starts_at=company["starts_at"],
            ends_at=company["ends_at"],
            weekly_in_chat=True,
        )
    await session.commit()
    view = await read_company(session, code, settings=_settings(settings))
    assert view is not None
    return view


async def _require_organizer(session: AsyncSession, code: str, telegram_user_id: int) -> dict[str, Any]:
    company = await _load(session, code)
    if company is None:
        raise CompanyRejected("Компания не найдена.", 404)
    if company["organizer_ref"] != tg_participant_key(telegram_user_id):
        raise CompanyRejected("Это может сделать тот, кто собирал компанию.", 403)
    return company


async def repeat_company(
    session: AsyncSession,
    *,
    code: str,
    telegram_user_id: int,
    session_id: int | None,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    cfg = _settings(settings)
    current = _now(now)
    company = await _require_organizer(session, code, telegram_user_id)
    chosen = session_id
    candidates = await nearest_sessions(session, company, now=current)
    exact = next((row for row in candidates if row.get("exact")), None)
    if chosen is None:
        if exact is None:
            return {"candidates": [_candidate_public(row) for row in candidates[:3]]}
        chosen = int(exact["id"])
    elif exact is None or int(chosen) not in {int(row["id"]) for row in candidates}:
        slot = await _session_row(session, int(chosen))
        if slot is None or int(slot["city_id"]) != int(company["city_id"]):
            raise CompanyRejected("Этот сеанс не подходит.", 422)
    await _track(
        session,
        kind="repeat_clicked",
        city_id=int(company["city_id"]),
        arena_id=_arena_id(str(company["venue_ref"])),
        payload={},
        actor_hash=telegram_actor_hash(telegram_user_id),
    )
    organizer_row = next(
        (
            row
            for row in await _responses(session, int(company["id"]))
            if row["participant_key"] == company["organizer_ref"]
        ),
        None,
    )
    created = await create_company(
        session,
        telegram_user_id=telegram_user_id,
        session_id=int(chosen),
        min_people=int(company["min_people"]),
        display_name=organizer_row["display_name"] if organizer_row else "Я",
        name=str(company["name"] or ""),
        max_people=company["max_people"],
        surface="repeat",
        now=current,
        settings=cfg,
    )
    new_company = await _load(session, created["public_code"])
    assert new_company is not None
    await session.execute(
        text(
            """
            INSERT INTO ice_company_responses (
                company_id, participant_key, display_name, status, source, reminders_enabled
            )
            SELECT :new_id, participant_key, display_name, status, source, reminders_enabled
            FROM ice_company_responses
            WHERE company_id = :old_id
              AND participant_key <> :organizer
              AND status IN ('going', 'maybe')
              AND reminders_enabled = true
            ON CONFLICT (company_id, participant_key) DO NOTHING
            """
        ),
        {"new_id": new_company["id"], "old_id": company["id"], "organizer": company["organizer_ref"]},
    )
    await _refresh_status(session, int(new_company["id"]))
    await session.commit()
    view = await read_company(session, created["public_code"], settings=cfg)
    assert view is not None
    return view


def _candidate_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": int(row["id"]),
        "starts_at": row["starts_at_utc"].isoformat(),
        "venue_label": row["arena_name"],
        "exact": bool(row.get("exact")),
    }


async def nearest_sessions(
    session: AsyncSession,
    company: dict[str, Any],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    arena_id = _arena_id(str(company["venue_ref"])) or 0
    rows = (
        await session.execute(
            text(
                """
                SELECT s.id, s.starts_at_utc, s.ends_at_utc, s.kind, s.arena_id, a.name AS arena_name,
                       a.city_id
                FROM ice_sessions s
                JOIN arenas a ON a.id = s.arena_id
                WHERE a.city_id = :city
                  AND s.status = 'active'
                  AND s.kind = :kind
                  AND s.starts_at_utc > :now
                ORDER BY (s.arena_id = :arena) DESC, s.starts_at_utc
                LIMIT 12
                """
            ),
            {
                "city": int(company["city_id"]),
                "kind": company["event_kind"],
                "now": now,
                "arena": arena_id,
            },
        )
    ).mappings().all()
    local = company["starts_at"].astimezone(timezone.utc)
    out = []
    for row in rows:
        item = dict(row)
        start = item["starts_at_utc"]
        item["exact"] = (
            int(item["arena_id"]) == arena_id
            and start.weekday() == local.weekday()
            and start.hour == local.hour
            and start.minute == local.minute
        )
        out.append(item)
    out.sort(key=lambda item: (not item["exact"], item["starts_at_utc"]))
    return out


async def sync_open_events(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Сверяет снимок с ice_sessions. Возвращает число сдвигов версии."""
    current = _now(now)
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT e.id, e.source_ref, e.starts_at, e.ends_at, e.venue_ref,
                       e.version, e.cancelled
                FROM ice_company_events e
                JOIN ice_companies c ON c.event_id = e.id
                WHERE c.status IN ('open', 'confirmed')
                  AND e.source_ref LIKE 'ice_session:%'
                """
            )
        )
    ).mappings().all()
    changed = 0
    for event in rows:
        raw = str(event["source_ref"]).split(":", 1)[-1]
        if not raw.isdigit():
            continue
        slot = await _session_row(session, int(raw))
        missing = slot is None or str(slot["status"]) == "cancelled"
        if missing:
            if not event["cancelled"]:
                await session.execute(
                    text(
                        """
                        UPDATE ice_company_events
                        SET cancelled = true, version = version + 1, updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {"id": event["id"], "now": current},
                )
                await session.execute(
                    text(
                        """
                        UPDATE ice_companies
                        SET status = 'cancelled', cancel_notice_pending = true, card_dirty = true
                        WHERE event_id = :id AND status IN ('open', 'confirmed')
                        """
                    ),
                    {"id": event["id"]},
                )
                changed += 1
            continue
        venue_ref = f"arena:{int(slot['arena_id'])}"
        moved = slot["starts_at_utc"] != event["starts_at"] or venue_ref != event["venue_ref"]
        if not moved:
            continue
        await session.execute(
            text(
                """
                UPDATE ice_company_events
                SET starts_at = :starts, ends_at = :ends, previous_starts_at = :prev,
                    venue_ref = :venue, venue_label = :label, version = version + 1,
                    updated_at = :now, cancelled = false
                WHERE id = :id
                """
            ),
            {
                "starts": slot["starts_at_utc"],
                "ends": slot["ends_at_utc"],
                "prev": event["starts_at"],
                "venue": venue_ref,
                "label": str(slot["arena_name"])[:120],
                "now": current,
                "id": event["id"],
            },
        )
        await session.execute(
            text(
                """
                UPDATE ice_company_responses r
                SET needs_reconfirm = true
                FROM ice_companies c
                WHERE r.company_id = c.id AND c.event_id = :id
                  AND c.status IN ('open', 'confirmed')
                  AND r.status IN ('going', 'maybe')
                """
            ),
            {"id": event["id"]},
        )
        await session.execute(
            text(
                """
                UPDATE ice_companies
                SET schedule_notice_pending = true, card_dirty = true, expires_at = :expires
                WHERE event_id = :id AND status IN ('open', 'confirmed')
                """
            ),
            {
                "id": event["id"],
                "expires": slot["ends_at_utc"] + timedelta(days=_settings(None).ice_company_retention_days),
            },
        )
        companies = (
            await session.execute(
                text("SELECT id FROM ice_companies WHERE event_id = :id AND status IN ('open', 'confirmed')"),
                {"id": event["id"]},
            )
        ).all()
        for (company_id,) in companies:
            await _refresh_status(session, int(company_id))
        changed += 1
    if changed:
        await session.commit()
    return changed


def actor_for_telegram(user_id: int | None, ip: str | None, ua: str | None) -> str | None:
    if user_id is not None:
        return telegram_actor_hash(user_id)
    return public_actor_hash(client_ip=ip, user_agent=ua)
