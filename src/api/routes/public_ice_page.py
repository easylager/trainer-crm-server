"""
Публичная страница «Лёд сегодня в городе» — шеринг-артефакт №1 эпика (TASK-096, DEC-004).

Отдельный модуль и отдельный роутер без префикса ``/api``: это не API, а страница,
которую открывает человек по ссылке из чата. Авторизации нет **осознанно** — требовать
Telegram у получателя пересланной ссылки значит убить пересылку на первом же шаге.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application.ice_city_day import (
    city_slug,
    get_city_ice_day,
    resolve_city_by_ref,
)
from src.application.ice_city_day_og import render_ice_city_day_og
from src.application.ice_city_day_page import ice_city_day_paths, render_ice_city_day_page
from src.application.trainer_invite_links import normalize_client_bot_username
from src.shared.config import Settings

router = APIRouter(tags=["public-ice-share"])

# Страница живая: её открывают спустя часы после пересылки, и к этому моменту утренние
# сеансы уже прошли. Короткий кэш достаточен, чтобы пережить всплеск от одного репоста,
# и слишком короткий, чтобы показать вчерашнее расписание.
_PAGE_CACHE = {"Cache-Control": "public, max-age=300"}
_OG_CACHE = {"Cache-Control": "public, max-age=900"}


def _public_base() -> str:
    return (Settings().webapp_base_url or "").strip().rstrip("/")


def _cta_url() -> str | None:
    username = normalize_client_bot_username(Settings().client_bot_username)
    return f"https://t.me/{username}" if username else None


async def _load(session: AsyncSession, city_ref: str):
    city = await resolve_city_by_ref(session, city_ref)
    if city is None:
        raise HTTPException(status_code=404, detail="City not found")
    day = await get_city_ice_day(session, city_id=int(city["id"]))
    return city, day


@router.get("/ice/{city_ref}/today", response_class=HTMLResponse)
async def ice_city_day_page(
    city_ref: str,
    session: AsyncSession = Depends(get_session),
):
    """Расписание массовых катаний города на день + og-теги для превью в Telegram."""
    city, day = await _load(session, city_ref)
    city_name = str(city["name"])

    canonical_path, og_path = ice_city_day_paths(city_name)
    if city_ref.strip().lower() != city_slug(city_name):
        # Пришли по id (`/ice/12/today`) — уводим на канонический slug, чтобы в чатах
        # ходила одна ссылка, а не две на одно и то же.
        return RedirectResponse(url=canonical_path, status_code=301)

    base = _public_base()
    html = render_ice_city_day_page(
        city_name=city_name,
        day=day,
        canonical_url=f"{base}{canonical_path}" if base else canonical_path,
        og_image_url=f"{base}{og_path}" if base else og_path,
        cta_url=_cta_url(),
    )
    return HTMLResponse(content=html, media_type="text/html", headers=_PAGE_CACHE)


@router.get("/ice/{city_ref}/today/og.png")
async def ice_city_day_og(
    city_ref: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """og:image для страницы выше. Рисуется на лету из той же выборки — кэша на диске нет."""
    city, day = await _load(session, city_ref)
    png = render_ice_city_day_og(city_name=str(city["name"]), day=day)
    return Response(content=png, media_type="image/png", headers=_OG_CACHE)
