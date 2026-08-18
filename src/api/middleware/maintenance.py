"""
Planned maintenance: fail API calls fast with a stable 503 JSON body.

Static Mini App HTML (/webapp, /static/webapp) and /health/live stay up so the
WebView can render the outage overlay instead of a blank Telegram screen.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.shared.config import Settings
from src.shared.outage import SERVICE_UNAVAILABLE_CODE, service_unavailable_payload


def _api_path_blocked_in_maintenance(path: str) -> bool:
    return path.startswith("/api/")


class MaintenanceModeMiddleware(BaseHTTPMiddleware):
    """When MAINTENANCE_MODE=1, short-circuit /api/* without touching Postgres."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)
        if not _api_path_blocked_in_maintenance(request.url.path):
            return await call_next(request)
        if not Settings().maintenance_mode:
            return await call_next(request)
        payload = service_unavailable_payload(db="skip")
        payload["status"] = "maintenance"
        return JSONResponse(
            status_code=503,
            content=payload,
            headers={
                "Retry-After": "60",
                "X-Ice-Studio-Outage": SERVICE_UNAVAILABLE_CODE,
            },
        )
