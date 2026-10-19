"""Cookie ``glide_city`` — город посетителя для главной (TASK-210-A)."""

from __future__ import annotations

import html as html_lib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.responses import Response

GLIDE_CITY_COOKIE = "glide_city"
GLIDE_CITY_MAX_AGE_SEC = 180 * 24 * 3600
GLIDE_CITY_PIN_VERSION = "1"
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalize_glide_city_slug(raw: str | None) -> str | None:
    slug = (raw or "").strip().lower()
    if not slug or not _SLUG_RE.fullmatch(slug):
        return None
    return slug


def apply_glide_city_cookie(response: Response, *, slug: str) -> None:
    """Ставит cookie только для нормализованного slug (валидность города — у вызывающего)."""
    normalized = normalize_glide_city_slug(slug)
    if not normalized:
        return
    response.set_cookie(
        key=GLIDE_CITY_COOKIE,
        value=normalized,
        max_age=GLIDE_CITY_MAX_AGE_SEC,
        path="/",
        samesite="lax",
        httponly=True,
        # Сайт только по https (HSTS). localhost браузеры считают безопасным — dev не ломается.
        secure=True,
    )


def glide_city_pin_script(slug: str) -> str:
    """Повторно ставит куку на pageshow: HTTP-кэш и bfcache не исполняют Set-Cookie."""
    normalized = normalize_glide_city_slug(slug)
    if not normalized:
        return ""
    safe = html_lib.escape(normalized, quote=True)
    return (
        f'<script src="/static/shared/glide-city-pin.js?v={GLIDE_CITY_PIN_VERSION}" '
        f'data-glide-city="{safe}"></script>'
    )
