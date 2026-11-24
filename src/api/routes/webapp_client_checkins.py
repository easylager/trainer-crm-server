"""TASK-446: «Я здесь» — API отметок о льде и загрузки катков (флаг ``redesign_s5``).

Всё за флагом: без ``redesign_s5`` каждый маршрут отвечает 404 — для остальных
клиентов фичи не существует. Профиль — как у остальных клиентских ручек:
``X-Profile-Id`` → acting client id; отметка пишется с ``profile_id`` выбранного
профиля (NULL = владелец аккаунта), лимит в сутки и загрузка — по аккаунту.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import (
    MiniAppPlatform,
    MiniAppPrincipal,
    client_catalog_telegram_key,
    get_client_miniapp_principal,
)
from src.application import ice_checkins as ic
from src.application.client_profile_use_cases import resolve_acting_client_id
from src.application.client_ui_flags import redesign_s5_enabled
from src.application.client_use_cases import get_client_id_by_telegram_id
from src.application.place_links import place_start_param, public_telegram_entry_link
from src.application.style_b import b_photo_url
from src.shared.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webapp"])

_ERROR_STATUS = {
    "unknown_session": 404,
    "not_found": 404,
    "not_ongoing": 409,
    "daily_limit": 409,
    "already_set": 409,
    "bad_level": 422,
    "bad_kind": 422,
}


def _flag_or_404(principal: MiniAppPrincipal) -> int:
    account_key = client_catalog_telegram_key(principal)
    if not redesign_s5_enabled(account_key, Settings()):  # type: ignore[call-arg]
        raise HTTPException(status_code=404, detail="Not found")
    return account_key


async def _profile_id(
    session: AsyncSession, telegram_id: int, requested: int | None
) -> int | None:
    """client_id выбранного профиля; NULL, когда действует владелец аккаунта."""
    if requested is None:
        return None
    acting = await resolve_acting_client_id(session, telegram_id, requested)
    own = await get_client_id_by_telegram_id(session, telegram_id)
    if acting is None or acting == own:
        return None
    return int(acting)


def _parse_profile_header(x_profile_id: str | None) -> int | None:
    if not x_profile_id:
        return None
    try:
        return int(x_profile_id)
    except (TypeError, ValueError):
        return None


def _raise(err: ic.CheckinError) -> None:
    status = _ERROR_STATUS.get(err.code, 409)
    raise HTTPException(status_code=status, detail={"code": err.code}) from err


class CheckinBody(BaseModel):
    session_id: int
    load_level: int | None = Field(default=None, ge=1, le=3)


class LoadBody(BaseModel):
    load_level: int = Field(ge=1, le=3)


class IntentBody(BaseModel):
    session_id: int
    kind: Literal["view", "route"]


async def _answer_payload(
    session: AsyncSession, telegram_id: int, profile_id: int | None, session_id: int, now: datetime
) -> dict:
    stats = await ic.me_stats(session, telegram_id, profile_id, now.astimezone(ic.MINSK).date())
    live = (await ic.session_live(session, [session_id], now)).get(session_id)
    return {
        "season_days": stats["season_days"],
        "nth_label": f"{stats['season_days']}-й раз за сезон",
        "streak_weeks": stats["streak_weeks"],
        "has_this_week": stats["has_this_week"],
        "live": live,
    }


@router.post("/client/checkins")
async def post_client_checkin(
    body: CheckinBody,
    x_profile_id: str | None = Header(None),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    telegram_id = _flag_or_404(principal)
    profile_id = await _profile_id(session, telegram_id, _parse_profile_header(x_profile_id))
    now = datetime.now(timezone.utc)
    try:
        res = await ic.check_in(
            session, telegram_id, profile_id, body.session_id, "app",
            load_level=body.load_level, now=now,
        )
    except ic.CheckinError as err:
        await session.rollback()
        _raise(err)
    await session.commit()
    payload = await _answer_payload(session, telegram_id, profile_id, body.session_id, now)
    checkin = (
        (
            await session.execute(
                text("SELECT load_level FROM ice_checkins WHERE id = :id"),
                {"id": res["checkin_id"]},
            )
        )
        .mappings()
        .first()
    )
    return {
        "checkin_id": res["checkin_id"],
        "session_id": res["session_id"],
        "load_level": (checkin or {}).get("load_level") if checkin else body.load_level,
        **payload,
    }


@router.patch("/client/checkins/{checkin_id}")
async def patch_client_checkin(
    checkin_id: int,
    body: LoadBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    telegram_id = _flag_or_404(principal)
    try:
        res = await ic.set_load(session, checkin_id, telegram_id, body.load_level)
    except ic.CheckinError as err:
        await session.rollback()
        _raise(err)
    await session.commit()
    return {"live": res["live"]}


@router.get("/client/checkins/state")
async def get_client_checkins_state(
    session_ids: str,
    focus: int | None = None,
    x_profile_id: str | None = Header(None),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    telegram_id = _flag_or_404(principal)
    ids = [int(s) for s in session_ids.split(",") if s.strip().isdigit()][:50]
    profile_id = await _profile_id(session, telegram_id, _parse_profile_header(x_profile_id))
    now = datetime.now(timezone.utc)
    if focus is not None:
        try:
            await ic.record_intent(session, telegram_id, int(focus), "view")
        except ic.CheckinError:
            pass
        try:
            await ic.record_helps(session, telegram_id, int(focus), now)
        except Exception:  # noqa: BLE001 — «помог выбрать» не должен ломать state
            logger.exception("checkin record_helps failed")
    if not ids:
        sessions: dict[int, dict] = {}
    else:
        sess_rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT id, kind, starts_at_utc, ends_at_utc, ends_at_local, status FROM ice_sessions
                        WHERE id = ANY(:ids)
                        """
                    ),
                    {"ids": ids},
                )
            )
            .mappings()
            .all()
        )
        live_map = await ic.session_live(session, ids, now)
        mine = (
            (
                await session.execute(
                    text(
                        """
                        SELECT session_id, id, load_level FROM ice_checkins
                        WHERE telegram_id = :t AND COALESCE(profile_id, 0) = :p
                          AND session_id = ANY(:ids)
                        """
                    ),
                    {"t": telegram_id, "p": int(profile_id or 0), "ids": ids},
                )
            )
            .mappings()
            .all()
        )
        mine_by_session = {int(r["session_id"]): r for r in mine}
        sessions = {}
        for r in sess_rows:
            sid = int(r["id"])
            my = mine_by_session.get(sid)
            sessions[sid] = {
                "ongoing": ic.is_ongoing(r, now),
                "checked_in": my is not None,
                "checkin_id": int(my["id"]) if my else None,
                "load_level": my["load_level"] if my else None,
                "ends_local": str(r["ends_at_local"])[:5] if r.get("ends_at_local") else None,
                "live": live_map.get(sid),
            }
    today = now.astimezone(ic.MINSK).date()
    stats = await ic.me_stats(session, telegram_id, profile_id, today)
    helped = await ic.helped_count(session, telegram_id)
    await session.commit()
    return {
        "sessions": {str(k): v for k, v in sessions.items()},
        "me": {**stats, "helped": helped},
    }


@router.post("/client/checkins/intent", status_code=204)
async def post_client_checkin_intent(
    body: IntentBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> None:
    telegram_id = _flag_or_404(principal)
    try:
        await ic.record_intent(session, telegram_id, body.session_id, body.kind)
    except ic.CheckinError as err:
        await session.rollback()
        _raise(err)
    await session.commit()


def _share_caption(first_name: str | None, arena_name: str, ends_local: str, live: dict | None) -> str:
    name = (first_name or "Я").strip() or "Я"
    text_cap = f"{name} на «{arena_name}» до {ends_local}"
    if live and live.get("level") in ic.LOAD_WORDS:
        text_cap += f"\n{ic.LOAD_WORDS[int(live['level'])]} · отметок: {live['count']}"
    return text_cap + "\nПодъезжай!"


async def _prepare_inline(
    token: str, user_id: int, result_id: str, photo: str | None, caption: str, button: dict
) -> str | None:
    """savePreparedInlineMessage — как у «Кто кого»: клиент откроет выбор чата."""
    import aiohttp

    if not (token or "").strip():
        return None
    markup = {"inline_keyboard": [[button]]}
    if photo:
        result = {
            "type": "photo",
            "id": result_id,
            "photo_url": photo,
            "thumbnail_url": photo,
            "caption": caption,
            "reply_markup": markup,
        }
    else:
        result = {
            "type": "article",
            "id": result_id,
            "title": "Я на катке",
            "input_message_content": {"message_text": caption},
            "reply_markup": markup,
        }
    payload = {
        "user_id": user_id,
        "allow_user_chats": True,
        "allow_group_chats": True,
        "allow_channel_chats": False,
        "allow_bot_chats": False,
        "result": result,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.post(
                f"https://api.telegram.org/bot{token}/savePreparedInlineMessage", json=payload
            ) as resp:
                data = await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001 — в тексте aiohttp бывает токен
        logger.info("checkin savePreparedInlineMessage failed: %s", type(exc).__name__)
        return None
    if not isinstance(data, dict) or data.get("ok") is not True:
        logger.info("checkin savePreparedInlineMessage refused: %s", (data or {}).get("description"))
        return None
    return str((data.get("result") or {}).get("id") or "") or None


@router.post("/client/checkins/{checkin_id}/share")
async def post_client_checkin_share(
    checkin_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    telegram_id = _flag_or_404(principal)
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT c.id, c.session_id, c.arena_id, s.ends_at_local, a.name AS arena_name,
                           cl.first_name,
                           (SELECT m.variants FROM media m
                             WHERE m.owner_type = 'arena' AND m.owner_id = c.arena_id
                               AND m.status = 'published'
                             ORDER BY m.sort_order, m.id LIMIT 1) AS variants
                    FROM ice_checkins c
                    JOIN ice_sessions s ON s.id = c.session_id
                    JOIN arenas a ON a.id = c.arena_id
                    LEFT JOIN clients cl ON cl.telegram_id = c.telegram_id
                    WHERE c.id = :id AND c.telegram_id = :t
                    """
                ),
                {"id": int(checkin_id), "t": telegram_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Отметка не найдена")
    settings = Settings()  # type: ignore[call-arg]
    url = public_telegram_entry_link(
        settings, start_param=place_start_param(int(row["arena_id"]), int(row["session_id"]))
    )
    if not url:
        raise HTTPException(status_code=503, detail="Ссылка пока недоступна")
    now = datetime.now(timezone.utc)
    live = (await ic.session_live(session, [int(row["session_id"])], now)).get(int(row["session_id"]))
    variants = row.get("variants") if isinstance(row.get("variants"), dict) else {}
    photo = b_photo_url(variants.get("card") or variants.get("thumb"))
    caption = _share_caption(row.get("first_name"), str(row["arena_name"]), str(row["ends_at_local"])[:5], live)
    button = {"text": "Я тоже · открыть сеанс", "url": url}
    prepared = None
    if principal.platform == MiniAppPlatform.TELEGRAM:
        prepared = await _prepare_inline(
            settings.telegram_bot_token_client, telegram_id,
            f"ci{checkin_id}s{int(row['session_id'])}"[:64], photo, caption, button,
        )
    await session.execute(
        text("UPDATE ice_checkins SET shared_at = :now WHERE id = :id AND shared_at IS NULL"),
        {"now": now, "id": int(checkin_id)},
    )
    await session.commit()
    from urllib.parse import quote

    share_url = f"https://t.me/share/url?url={quote(url, safe='')}&text={quote(caption, safe='')}"
    return {"prepared_message_id": prepared, "share_url": share_url, "text": caption}
