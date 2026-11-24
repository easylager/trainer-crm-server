"""TASK-389: замер «нажатие на вкладку бара -> содержимое показано» и холодного старта.

Метка уходит с клиента после показа. Пишется строкой лога (как /client/register-event):
таблица catalog_consumer_events держит CHECK на kind, новый kind требует миграции, а её
решает владелец. Без telegram id и initData: в строке только вкладки, миллисекунды,
платформа и флаг. Разбор строк и медианы — scripts/tab_timing_report.py.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from src.api.miniapp_auth import MiniAppPrincipal, get_client_miniapp_principal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webapp"])

Tab = Literal["home", "catalog", "bookings", "kk", "me", "more"]


class TabTimingBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Literal["tab", "cold"]
    from_: Tab | None = Field(None, alias="from")
    to: Tab
    ms: int = Field(..., ge=0, le=120_000)
    page_ms: int = Field(..., ge=0, le=120_000)
    # shell — переход внутри оболочки вкладок без загрузки страницы (TASK-391).
    nav: Literal["navigate", "reload", "back_forward", "prerender", "shell"] = "navigate"
    platform: str = Field("unknown", pattern=r"^[a-z0-9_]{1,16}$")
    season_ui: bool = False
    # TASK-448: src — откуда первый кадр (cache|net), data_ms — время до данных.
    src: Literal["cache", "net"] | None = None
    data_ms: int | None = Field(None, ge=0, le=120_000)


@router.post("/client/tab-timing", status_code=204)
async def post_client_tab_timing(
    body: TabTimingBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> Response:
    """Best-effort: ответ пустой, ошибки клиент глотает. Один вызов на переход."""
    logger.info(
        "client tab-timing kind=%s from=%s to=%s ms=%d page_ms=%d platform=%s season_ui=%d nav=%s src=%s data_ms=%s",
        body.kind,
        body.from_ or "-",
        body.to,
        body.ms,
        body.page_ms,
        body.platform,
        1 if body.season_ui else 0,
        body.nav,
        body.src or "-",
        body.data_ms if body.data_ms is not None else "-",
    )
    return Response(status_code=204)
