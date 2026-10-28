"""
«Предложить место» без логина (PDEC-028): поиск города и создание заявки с сайта.

Бот-защита — honeypot ``website`` и узкие бакеты ``suggest`` / ``suggest_cities`` в
``http_limits``. Заявка с сайта получает ``bind_token``: ссылка ``t.me/<бот>?start=sg_<token>``
привязывает автора к Telegram, чтобы владелец мог ему ответить.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.middleware.http_limits import client_ip_from_request
from src.application.place_suggestion_city_search import search_cities
from src.application.place_suggestion_use_cases import create_place_suggestion
from src.shared.config import Settings
from src.shared.place_suggestion import PlaceSuggestionError

router = APIRouter(prefix="/api/public/place-suggestions", tags=["public-place-suggestions"])

_NO_STORE = {"Cache-Control": "no-store"}


class NewCityBody(BaseModel):
    name: str = Field(max_length=120)
    country: str = Field(min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=160)
    lat: float | None = None
    lon: float | None = None


class PlaceSuggestionFields(BaseModel):
    """Поля заявки, общие для сайта и Mini App."""

    kind: str = Field(max_length=16)
    city_id: int | None = None
    new_city: NewCityBody | None = None
    name: str = Field(max_length=200)
    address: str | None = Field(default=None, max_length=300)
    details: dict[str, Any] = Field(default_factory=dict)
    contact: str | None = Field(default=None, max_length=120)


class PlaceSuggestionBody(PlaceSuggestionFields):
    website: str | None = Field(default=None, max_length=200)  # honeypot — must stay empty


def suggestion_error_response(exc: PlaceSuggestionError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)}, headers=_NO_STORE)


def telegram_bind_link(bind_token: str | None) -> str | None:
    username = (Settings().client_bot_username or "").strip().lstrip("@")
    if not bind_token or not username:
        return None
    return f"https://t.me/{username}?start=sg_{bind_token}"


@router.get("/cities")
async def get_place_suggestion_cities(
    response: Response,
    q: str = Query(default="", max_length=120),
    session: AsyncSession = Depends(get_session),
) -> dict:
    response.headers.update(_NO_STORE)
    return {"items": await search_cities(session, q)}


@router.post("")
async def post_place_suggestion(
    request: Request,
    body: PlaceSuggestionBody,
    session: AsyncSession = Depends(get_session),
):
    # Honeypot: bots fill hidden fields; reject without hinting (как /trainer-start).
    if body.website and body.website.strip():
        raise HTTPException(status_code=400, detail="Invalid request")
    ip = client_ip_from_request(request)
    try:
        res = await create_place_suggestion(
            session,
            source="site",
            kind=body.kind,
            city_id=body.city_id,
            new_city=body.new_city.model_dump() if body.new_city else None,
            name=body.name,
            address=body.address,
            details=body.details,
            contact=body.contact,
            author_telegram_id=None,
            client_ip=None if ip == "unknown" else ip,
        )
    except PlaceSuggestionError as exc:
        return suggestion_error_response(exc)
    return JSONResponse(
        content={"ok": True, "id": res["id"], "telegram_link": telegram_bind_link(res["bind_token"])},
        headers=_NO_STORE,
    )
