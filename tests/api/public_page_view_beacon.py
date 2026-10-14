"""POST /api/public/catalog/page-view — как sendBeacon с публичных /, /c/, /p/."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

_PAGE_VIEW_URL = "/api/public/catalog/page-view"


async def post_catalog_page_view(
    client: AsyncClient,
    *,
    surface: str,
    path: str,
    city_id: int | None = None,
    arena_id: int | None = None,
    extra_params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
):
    params: dict[str, Any] = {"surface": surface, "path": path}
    if city_id is not None:
        params["city_id"] = city_id
    if arena_id is not None:
        params["arena_id"] = arena_id
    if extra_params:
        params.update(extra_params)
    return await client.post(_PAGE_VIEW_URL, params=params, headers=headers or {})
