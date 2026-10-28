"""
«Предложить место» из клиентского Mini App (PDEC-028).

Тот же use case, что у сайта, но автор известен из initData: владелец ответит ему через
клиентского бота, поэтому ни ``bind_token``, ни ссылки на бота в ответе нет. Без initData
(браузер, сбой подписи) заявка всё равно принимается — без автора. Лимит — общий бакет
``suggest`` с сайтом (см. ``http_limits``).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.middleware.http_limits import client_ip_from_request
from src.api.miniapp_auth.deps import get_optional_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.api.routes.public_place_suggestions import PlaceSuggestionFields, suggestion_error_response
from src.application.place_suggestion_use_cases import create_place_suggestion
from src.shared.place_suggestion import PlaceSuggestionError

router = APIRouter(tags=["webapp-place-suggestions"])


@router.post("/place-suggestions")
async def post_webapp_place_suggestion(
    request: Request,
    body: PlaceSuggestionFields,
    principal: MiniAppPrincipal | None = Depends(get_optional_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    author = (
        int(principal.user_id)
        if principal is not None and principal.platform == MiniAppPlatform.TELEGRAM
        else None
    )
    ip = client_ip_from_request(request)
    try:
        res = await create_place_suggestion(
            session,
            source="miniapp",
            kind=body.kind,
            city_id=body.city_id,
            new_city=body.new_city.model_dump() if body.new_city else None,
            name=body.name,
            address=body.address,
            details=body.details,
            contact=body.contact,
            author_telegram_id=author,
            client_ip=None if ip == "unknown" else ip,
        )
    except PlaceSuggestionError as exc:
        return suggestion_error_response(exc)
    return {"ok": True, "id": res["id"]}
