"""``GET /<ключ>.txt`` — файл-подтверждение владения сайтом для IndexNow.

Маршрут точный (путь с конкретным ключом, не ``/{x}.txt``), поэтому ничего не
перекрывает; регистрируется только при INDEXNOW_ENABLED и валидном INDEXNOW_KEY.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from src.application.indexnow import active_key


def build_indexnow_key_router() -> APIRouter | None:
    key = active_key()
    if key is None:
        return None
    router = APIRouter(tags=["indexnow"])

    @router.get(f"/{key}.txt", response_class=PlainTextResponse, include_in_schema=False)
    async def indexnow_key_file() -> PlainTextResponse:
        return PlainTextResponse(key, media_type="text/plain")

    return router
