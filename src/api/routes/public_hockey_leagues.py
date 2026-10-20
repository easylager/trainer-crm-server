"""Публичное превью лиги друзей и картинки карточек «Кто кого»: по ссылке, без входа."""

from __future__ import annotations

from datetime import datetime, timezone

import html
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.catalog_share_actor import catalog_share_actor
from src.api.deps import get_session
from src.api.miniapp_auth.deps import get_optional_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPrincipal
from src.api.routes.public_arenas import _SHARE_CHANNELS
from src.api.routes.webapp_client_hockey_leagues import invite_url_for_code
from src.application import hockey_event
from src.application.client_delight_metrics import record_client_share
from src.application.png_cache import cached_png
from src.application.hockey_cards import (
    check_result_card_sig,
    render_league_card,
    render_match_card,
    render_result_card,
    result_verdict,
)
from src.application.hockey_match_share import card_image_url, match_link, match_share_payload, when_phrase
from src.application.hockey_cards import match_card_version
from src.application.hockey_leagues import league_preview
from src.application.hockey_matches import STATUS_FINAL, get_match
from src.application.hockey_share import league_card
from src.application.ice_company.service import minsk_arena
from src.infrastructure.db.models import CLIENT_SHARE_KIND_PLACE
from src.shared.config import Settings

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/hockey/leagues/{code}")
async def get_public_hockey_league(code: str, session: AsyncSession = Depends(get_session)) -> dict:
    preview = await league_preview(session, code)
    if preview is None:
        raise HTTPException(status_code=404, detail="Лига не найдена")
    return {**preview, "invite_url": invite_url_for_code(preview["invite_code"])}


@router.get("/hockey/matches/{match_id}/share")
async def get_public_hockey_match_share(
    match_id: int,
    request: Request,
    response: Response,
    invite: bool = Query(False, description="Тон «Погнали?» вместо «Поделиться»."),
    share_context: str | None = Query(None, description="Где нажали: match_page, hub."),
    record: bool = Query(True, description="false — предпросмотр в шите: показать, но не считать шерингом."),
    channel: str | None = Query(None, description="Канал: telegram | copy | story | system."),
    principal: MiniAppPrincipal | None = Depends(get_optional_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Шеринг домашнего матча Динамо: тот же контракт, что у ``/arenas/{ref}/share`` (TASK-304).

    Матч, выездной матч, чужой id и выключенный флаг игры дают одинаковый 404.
    ``record=true`` пишет событие шаринга в ``client_share_events`` (kind ``place``, арена матчей,
    ``payload.surface = hockey_match``): таблица и её CHECK уже есть, а канал живёт в ``payload.channel``,
    как у места. ``hockey_card_events`` не годится — у него нет канала и CHECK пускает только карточки игры.
    """
    response.headers["Cache-Control"] = "no-store"
    if not hockey_event.enabled():
        raise HTTPException(status_code=404, detail="Матч не найден")
    ctx = (share_context or "").strip().lower()[:40] or "match_page"
    try:
        payload = await match_share_payload(session, match_id=match_id, invite=invite, share_context=ctx)
    except hockey_event.MatchNotFound:
        raise HTTPException(status_code=404, detail="Матч не найден") from None
    if record:
        ch = (channel or "").strip().lower()
        telegram_id, actor = catalog_share_actor(principal, request)
        arena = await minsk_arena(session)
        await record_client_share(
            session,
            kind=CLIENT_SHARE_KIND_PLACE,
            share_context=ctx,
            city_id=int(arena["city_id"]) if arena else None,
            arena_id=int(arena["id"]) if arena else None,
            telegram_id=telegram_id,
            actor_hash=actor,
            payload={
                "surface": "hockey_match",
                "match_id": int(match_id),
                "invite": bool(invite),
                "channel": ch if ch in _SHARE_CHANNELS else None,
            },
        )
    return payload


# Картинки карточек для чата (TASK-300): Telegram забирает их по адресу без initData.
card_router = APIRouter(tags=["public"])

_IMMUTABLE = {"Cache-Control": "public, max-age=604800, immutable"}


@card_router.get("/kk/r/{match_id}/{points}/{sig}.png")
async def get_result_card_png(
    match_id: int, points: int, sig: str, session: AsyncSession = Depends(get_session)
) -> Response:
    """Итог «в точку!»: адрес подписан, счёт берём из базы, а не из адреса."""
    if not check_result_card_sig(Settings().telegram_bot_token_client, match_id, points, sig):  # type: ignore[call-arg]
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    match = await get_match(session, match_id)
    if match is None or match.status != STATUS_FINAL or result_verdict(points) is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    assert match.home_score is not None and match.away_score is not None
    home_score, away_score = match.home_score, match.away_score
    png = await cached_png(
        ("result", match.home_team, match.away_team, home_score, away_score, points),
        lambda: render_result_card(
            home=match.home_team, away=match.away_team, home_score=home_score, away_score=away_score, points=points
        ),
    )
    return Response(content=png, media_type="image/png", headers=_IMMUTABLE)


@card_router.get("/kk/l/{code}.png")
async def get_league_card_png(code: str, session: AsyncSession = Depends(get_session)) -> Response:
    """Приглашение в лигу. Адрес несёт ?v= от содержимого — новая версия, новый адрес."""
    card = await league_card(session, code, now=datetime.now(timezone.utc))
    if card is None:
        raise HTTPException(status_code=404, detail="Лига не найдена")
    png = await cached_png(
        ("league", card.name, card.members, tuple(card.names), card.next_match),
        lambda: render_league_card(name=card.name, members=card.members, names=card.names, next_match=card.next_match),
    )
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


# Только краулеры превью. «WhatsApp» и «Viber» в UA есть и у живого браузера внутри мессенджера —
# их не держим на странице, иначе человек не попадёт в приложение.
_PREVIEW_BOTS = ("telegrambot", "twitterbot", "facebookexternalhit", "slackbot", "vkshare", "discordbot")


def _preview_bot(request: Request) -> bool:
    """Краулер превью не уводим на t.me: иначе он снимет картинку уже с чужой страницы."""
    agent = (request.headers.get("user-agent") or "").lower()
    return any(bot in agent for bot in _PREVIEW_BOTS)


async def _match_card(session: AsyncSession, match_id: int, *, invite: bool, story: bool) -> Response:
    if not hockey_event.enabled():
        raise HTTPException(status_code=404, detail="Матч не найден")
    try:
        row = await hockey_event._home_match(session, match_id)  # noqa: SLF001
    except hockey_event.MatchNotFound:
        raise HTTPException(status_code=404, detail="Матч не найден") from None
    # Ключ — команды, время и тон, а не версия из адреса: «/kk/m/11/любое.png» не рисуется заново.
    png = await cached_png(
        ("match", row.home_team, row.away_team, row.starts_at.isoformat(), invite, story),
        lambda: render_match_card(home=row.home_team, away=row.away_team, starts_at=row.starts_at, invite=invite, story=story),
    )
    # Версия в адресе меняется вместе с командами и временем, поэтому кэш на час безопасен;
    # старая ссылка из давно отправленного сообщения получает актуальную картинку, а не 404.
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


@card_router.get("/kk/m/{match_id}")
async def get_match_share_page(
    match_id: int,
    request: Request,
    i: int = Query(0),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Страница-превью матча для ссылки в чате: картинка «Погнали?» в превью и сразу вход в Mini App.

    Её открывает Telegram, чтобы собрать превью, и друг — по тапу; друг сразу уходит в приложение.
    """
    if not hockey_event.enabled():
        raise HTTPException(status_code=404, detail="Матч не найден")
    try:
        row = await hockey_event._home_match(session, match_id)  # noqa: SLF001
    except hockey_event.MatchNotFound:
        raise HTTPException(status_code=404, detail="Матч не найден") from None
    cfg = Settings()  # type: ignore[call-arg]
    starts_at = row.starts_at if row.starts_at.tzinfo else row.starts_at.replace(tzinfo=timezone.utc)
    invite = i == 1
    title = f"{row.home_team} — {row.away_team}"
    head = f"Погнали? {title}" if invite else title
    where = f"{when_phrase(starts_at)} · Минск-Арена"
    image = card_image_url(
        cfg,
        match_id=int(row.id),
        version=match_card_version(row.home_team, row.away_team, starts_at),
        invite=invite,
        story=False,
    )
    go = match_link(int(row.id), cfg)
    e = html.escape
    hop = ""
    if not _preview_bot(request):
        hop = (
            f'<meta http-equiv="refresh" content="0; url={e(go)}">'
            f"<script>location.replace({json.dumps(go)});</script>"
        )
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(head)}</title>
<meta property="og:type" content="website">
<meta property="og:title" content="{e(head)}">
<meta property="og:description" content="{e(where)}">
<meta property="og:image" content="{e(image)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
{hop}
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#1747b5;color:#fff;font:600 18px/1.4 system-ui,sans-serif;text-align:center}}a{{color:#ffd23f}}</style>
</head><body><p>{e(head)}<br>{e(where)}<br><a href="{e(go)}">Открыть в Glide</a></p>
</body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=300"})


@card_router.get("/kk/m/{match_id}/{version}.story.png")
async def get_match_story_png(
    match_id: int,
    version: str,  # noqa: ARG001 — часть адреса для кэша, на содержимое не влияет
    i: int = Query(0),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Открытка матча для историй, 1080×1920."""
    return await _match_card(session, match_id, invite=i == 1, story=True)


@card_router.get("/kk/m/{match_id}/{version}.png")
async def get_match_card_png(
    match_id: int,
    version: str,  # noqa: ARG001
    i: int = Query(0),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Открытка матча для превью ссылки и ленты, 1200×630."""
    return await _match_card(session, match_id, invite=i == 1, story=False)
