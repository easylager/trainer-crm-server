"""Создание компании, ответ, отмена, удаление своих данных."""

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
from src.application.ice_company.copy import Snap, card_text, crowd_line
from src.application.ice_company.flag import city_enabled
from src.application.ice_company.safety import TextRejected, clean_free_text, clean_team_title
from src.shared.config import Settings

logger = logging.getLogger(__name__)

_SKATE = ("public_skate", "open_ice", "hockey_practice")
_OPEN = ("open",)


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
                       e.venue_ref, e.venue_label, e.city_id,
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
                SELECT participant_key, display_name, status, source, updated_at, avatar_file_key
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
    return tuple(str(row["display_name"]) for row in rows if row["status"] == "going")


def snap_from(company: dict[str, Any], rows: list[dict[str, Any]]) -> Snap:
    status = str(company["status"])
    return Snap(
        kind=str(company["event_kind"]),
        venue=str(company["venue_label"]),
        starts_at=company["starts_at"],
        status=status,
        going_names=_going_names(rows),
        team_title=str(company.get("name") or ""),
        session_cancelled=bool(company["event_cancelled"]),
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
) -> dict[str, Any]:
    going = [{"display_name": row["display_name"]} for row in rows if row["status"] == "going"]
    maybe = [{"display_name": row["display_name"]} for row in rows if row["status"] == "maybe"]
    cant = sum(1 for row in rows if row["status"] == "cant")
    snap = snap_from(company, rows)
    return {
        "public_code": company["public_code"],
        "name": company["name"],
        "status": company["status"],
        "going_count": len(going),
        "maybe_count": len(maybe),
        "cant_count": cant,
        "going": going,
        "maybe": maybe,
        "card_text": card_text(snap),
        "crowd_line": crowd_line(len(going)),
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
    return public_view(company, rows, settings=_settings(settings))


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


async def create_company(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    session_id: int,
    display_name: str,
    name: str = "",
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
        label = clean_free_text(display_name, max_len=cfg.ice_company_display_name_max_len, required=True, field="Имя")
        title = clean_team_title(name, max_len=cfg.ice_company_name_max_len, required=False)
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
                  AND c.status = 'open'
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
                                status, expires_at
                            ) VALUES (
                                :code, :name, :organizer, :event_id, :version,
                                'open', :expires_at
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
    await session.execute(
        text("UPDATE ice_companies SET card_dirty = true WHERE id = :id"),
        {"id": company_id},
    )
    await _track(
        session,
        kind="company_created",
        city_id=int(slot["city_id"]),
        arena_id=int(slot["arena_id"]),
        payload={"surface": surface},
        actor_hash=telegram_actor_hash(telegram_user_id),
    )
    await session.commit()
    view = await read_company(session, code, viewer_key=organizer, settings=cfg)
    assert view is not None
    return view


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
) -> dict[str, Any]:
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
    await session.execute(
        text(
            """
            INSERT INTO ice_company_responses (
                company_id, participant_key, display_name, status, source
            ) VALUES (
                :company_id, :key, :name, :status, :source
            )
            ON CONFLICT (company_id, participant_key) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                status = EXCLUDED.status,
                source = EXCLUDED.source,
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
    await session.execute(
        text("UPDATE ice_companies SET card_dirty = true WHERE id = :id"),
        {"id": company["id"]},
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
    await session.execute(
        text("UPDATE ice_companies SET card_dirty = true WHERE id = :id"),
        {"id": company["id"]},
    )
    await session.commit()


async def _require_organizer(session: AsyncSession, code: str, telegram_user_id: int) -> dict[str, Any]:
    company = await _load(session, code)
    if company is None:
        raise CompanyRejected("Компания не найдена.", 404)
    if company["organizer_ref"] != tg_participant_key(telegram_user_id):
        raise CompanyRejected("Это может сделать тот, кто собирал компанию.", 403)
    return company


async def sync_open_events(session: AsyncSession, *, now: datetime | None = None) -> int:
    current = _now(now)
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT e.id, e.source_ref, e.starts_at, e.ends_at, e.venue_ref,
                       e.version, e.cancelled
                FROM ice_company_events e
                JOIN ice_companies c ON c.event_id = e.id
                WHERE c.status = 'open'
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
                        SET status = 'cancelled', card_dirty = true
                        WHERE event_id = :id AND status = 'open'
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
                SET starts_at = :starts, ends_at = :ends,
                    venue_ref = :venue, venue_label = :label, version = version + 1,
                    updated_at = :now, cancelled = false
                WHERE id = :id
                """
            ),
            {
                "starts": slot["starts_at_utc"],
                "ends": slot["ends_at_utc"],
                "venue": venue_ref,
                "label": str(slot["arena_name"])[:120],
                "now": current,
                "id": event["id"],
            },
        )
        await session.execute(
            text(
                """
                UPDATE ice_companies
                SET card_dirty = true, expires_at = :expires
                WHERE event_id = :id AND status = 'open'
                """
            ),
            {
                "id": event["id"],
                "expires": slot["ends_at_utc"] + timedelta(days=_settings(None).ice_company_retention_days),
            },
        )
        changed += 1
    if changed:
        await session.commit()
    return changed


def actor_for_telegram(user_id: int | None, ip: str | None, ua: str | None) -> str | None:
    if user_id is not None:
        return telegram_actor_hash(user_id)
    return public_actor_hash(client_ip=ip, user_agent=ua)
