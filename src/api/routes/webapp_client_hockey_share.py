"""«Кто кого» в чат (TASK-300): готовое сообщение с карточкой и счётчики воронки.

Mini App просит сообщение — сервер собирает фото с кнопкой и кладёт его в Telegram
(savePreparedInlineMessage), игра открывает выбор чата (shareMessage). Бот в чат не добавляется.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import (
    MiniAppPlatform,
    MiniAppPrincipal,
    client_catalog_telegram_key,
    get_client_miniapp_principal,
)
from src.application.hockey_cards import (
    CARD_SIZE,
    crown_caption,
    crown_card_sig,
    league_caption,
    result_caption,
    result_card_sig,
)
from src.application.hockey_races import crown_card_data, race_by_id, race_result
from src.application.hockey_leagues import league_table, player_leagues
from src.application.hockey_share import league_card, record_card_event, result_card
from src.application.place_links import telegram_open_link
from src.shared.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webapp"])

# Параметры ссылок с карточек: по ним игра понимает, откуда пришли (воронка), и куда вести.
START_LEAGUE_CARD = "kkl"
START_RESULT_CARD = "kkr"


class ShareBody(BaseModel):
    card: Literal["result", "league", "crown"]
    match_id: int | None = None
    league_id: int | None = None
    race_id: int | None = None


class OpenedBody(BaseModel):
    card: Literal["result", "league", "crown"]


def card_link(prefix: str, code: str | None = None) -> str | None:
    settings = Settings()  # type: ignore[call-arg]
    return telegram_open_link(
        client_bot_username=settings.client_bot_username,
        mini_app_short_name=settings.client_mini_app_short_name,
        main_mini_app=settings.client_bot_main_mini_app,
        start_param=f"{prefix}_{code}" if code else prefix,
    )


def _public_root() -> str | None:
    root = (Settings().webapp_base_url or "").strip().rstrip("/")  # type: ignore[call-arg]
    return root if root.startswith("https://") else None


async def _prepare(
    token: str, user_id: int, result_id: str, photo: str | None, caption: str, button: dict
) -> str | None:
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
            "photo_width": CARD_SIZE[0],
            "photo_height": CARD_SIZE[1],
            "caption": caption,
            "reply_markup": markup,
        }
    else:
        result = {
            "type": "article",
            "id": result_id,
            "title": "Кто кого",
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
        logger.info("kto-kogo savePreparedInlineMessage failed: %s", type(exc).__name__)
        return None
    if not isinstance(data, dict) or data.get("ok") is not True:
        logger.info("kto-kogo savePreparedInlineMessage refused: %s", (data or {}).get("description"))
        return None
    return str((data.get("result") or {}).get("id") or "") or None


@router.post("/client/hockey/share")
async def post_client_hockey_share(
    body: ShareBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Сообщение для чата. Без бота или вне Telegram — текст и ссылка, игра отправит их через t.me/share."""
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    settings = Settings()  # type: ignore[call-arg]
    root = _public_root()

    if body.card == "crown":
        if body.race_id is None:
            raise HTTPException(status_code=422, detail="Нет месяца")
        race = await race_by_id(session, body.race_id)
        if race is None or race.closed_at is None:
            raise HTTPException(status_code=404, detail="Месяц ещё не закончился")
        res = await race_result(session, player_key=player_key, race=race)
        crown_league = res["league"]["id"] if res["league"] else None
        data = await crown_card_data(session, race_id=race.id, league_id=crown_league)
        assert data is not None
        caption = crown_caption(
            title=data["title"],
            where="в " + data["where"] if crown_league else "в общей таблице",
            winners=data["winners"],
            won=res["won"],
        )
        leagues = await player_leagues(session, player_key=player_key, now=now)
        code = next((x.invite_code for x in leagues if x.id == crown_league), None)
        url = card_link(START_LEAGUE_CARD, code) if code else card_link(START_RESULT_CARD)
        button = {"text": "Новый месяц — играть", "url": url}
        sig = crown_card_sig(settings.telegram_bot_token_client, race.id, crown_league or 0)
        photo = f"{root}/kk/c/{race.id}/{crown_league or 0}/{sig}.png" if root else None
        result_id = f"kkc{race.id}l{crown_league or 0}w{int(res['won'])}"
        league_id, match_id = crown_league, None
    elif body.card == "result":
        if body.match_id is None:
            raise HTTPException(status_code=422, detail="Нет матча")
        card = await result_card(session, player_key=player_key, match_id=body.match_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Похвастаться пока нечем")
        m = card.match
        assert m.home_score is not None and m.away_score is not None
        caption = result_caption(
            home=m.home_team, away=m.away_team, home_score=m.home_score, away_score=m.away_score, points=card.points
        )
        # Позвать в свою лигу, если она есть: хвастаются обычно там, где играют вместе.
        leagues = await player_leagues(session, player_key=player_key, now=now)
        url = card_link(START_RESULT_CARD, leagues[0].invite_code if leagues else None)
        button = {"text": "А ты угадаешь?", "url": url}
        sig = result_card_sig(settings.telegram_bot_token_client, m.id, card.points)
        photo = f"{root}/kk/r/{m.id}/{card.points}/{sig}.png" if root else None
        result_id = f"kkr{m.id}p{card.points}"
        league_id = leagues[0].id if leagues else None
        match_id: int | None = m.id
    else:
        if body.league_id is None:
            raise HTTPException(status_code=422, detail="Нет лиги")
        try:
            await league_table(session, league_id=body.league_id, player_key=player_key, now=now)
        except LookupError:
            raise HTTPException(status_code=404, detail="Лига не найдена") from None
        except PermissionError:
            raise HTTPException(status_code=403, detail="Нет доступа к этой лиге") from None
        mine = next(
            row for row in await player_leagues(session, player_key=player_key, now=now) if row.id == body.league_id
        )
        lc = await league_card(session, mine.invite_code, now=now)
        assert lc is not None
        caption = league_caption(lc.name)
        url = card_link(START_LEAGUE_CARD, lc.invite_code)
        button = {"text": "Вступить и угадать", "url": url}
        photo = f"{root}/kk/l/{lc.invite_code}.png?v={lc.version}" if root else None
        result_id = f"kkl{lc.invite_code}{lc.version[:6]}"
        league_id, match_id = body.league_id, None

    if not url:
        raise HTTPException(status_code=503, detail="Ссылка появится, когда бот будет настроен")
    prepared = None
    if principal.platform == MiniAppPlatform.TELEGRAM:
        prepared = await _prepare(settings.telegram_bot_token_client, player_key, result_id, photo, caption, button)
    await record_card_event(
        session, kind="shared", card=body.card, league_id=league_id, match_id=match_id, prepared=prepared is not None
    )
    await session.commit()
    return {"prepared_message_id": prepared, "text": caption, "url": url}


@router.post("/client/hockey/card-opened", status_code=204)
async def post_client_hockey_card_opened(
    body: OpenedBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Игру открыли с карточки в чате. Кто — не храним, только сколько."""
    await record_card_event(session, kind="opened", card=body.card)
    await session.commit()
