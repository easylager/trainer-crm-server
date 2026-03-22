"""FastAPI app: health check and API routers. No business logic here."""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger(__name__)

from sqlalchemy import text

from src.api.routes import (
    public_router,
    trainers_router,
    upload_router,
    webapp_router,
    webhooks_router,
)
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

app = FastAPI(title="Trainer CRM API")

# Mini Apps open in Telegram WebView; origin may be tunnel URL or telegram.org. Allow all so fetch() works.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(_request, exc: RequestValidationError):
    """Return first validation error as readable detail; log full errors for debugging."""
    errs = getattr(exc, "errors", ()) or []
    logger.warning("Request validation failed: %s", errs)
    detail = "Validation error"
    if errs:
        e = errs[0]
        loc = e.get("loc", ())
        msg = e.get("msg", "Validation error")
        loc_str = ".".join(str(x) for x in loc if x != "body")
        detail = f"{loc_str}: {msg}" if loc_str else msg
    return JSONResponse(status_code=422, content={"detail": detail})


# Telegram Web App: trainer schedule (Mini App)
_WEBAPP_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "webapp"

# No-cache for Mini App HTML: one extra request per open, but users always get latest after deploy.
# Alternative: max-age=60 (cache 1 min) — faster repeat opens, may see stale version once after deploy.
_WEBAPP_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _webapp_file_response(path: Path):
    return FileResponse(
        path,
        media_type="text/html",
        headers=_WEBAPP_NO_CACHE_HEADERS,
    )


@app.get("/webapp/schedule")
def webapp_schedule_page():
    """Serve the trainer schedule Mini App (HTML)."""
    path = _WEBAPP_DIR / "schedule.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/book")
def webapp_book_page():
    """Serve the client booking Mini App (HTML). URL should include ?trainer_id=..."""
    path = _WEBAPP_DIR / "book.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/catalog")
def webapp_catalog_page():
    """Serve the client catalog Mini App (city → service → arena → trainers → select)."""
    path = _WEBAPP_DIR / "catalog.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/trainer-bookings")
def webapp_trainer_bookings_page():
    """Serve the trainer bookings Mini App (list, detail, confirm/decline/cancel/recurring)."""
    path = _WEBAPP_DIR / "trainer-bookings.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/client-requests")
def webapp_client_requests_page():
    """Serve the client 'My requests and responses' Mini App."""
    path = _WEBAPP_DIR / "client-requests.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/client-bookings")
def webapp_client_bookings_page():
    """Serve the client 'My bookings' Mini App (list by day, arena/address/map, cancel with reason)."""
    path = _WEBAPP_DIR / "client-bookings.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/trainer-requests")
def webapp_trainer_requests_page():
    """Serve the trainer 'Client requests' Mini App (list, respond, decline, book)."""
    path = _WEBAPP_DIR / "trainer-requests.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/schedule-editor")
def webapp_schedule_editor_page():
    """Serve the trainer schedule editor Mini App (template + calendar, apply week, delete slot)."""
    path = _WEBAPP_DIR / "schedule-editor.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/trainer-stats")
def webapp_trainer_stats_page():
    """Serve the trainer statistics dashboard Mini App (KPIs, trends, charts)."""
    path = _WEBAPP_DIR / "trainer-stats.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/admin-stats")
def webapp_admin_stats_page():
    """Serve the admin dashboard Mini App (platform metrics, alerts, support count)."""
    path = _WEBAPP_DIR / "admin-stats.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/admin-dicts")
def webapp_admin_dicts_page():
    """Serve the admin dictionaries Mini App (cities & arenas)."""
    path = _WEBAPP_DIR / "admin-dicts.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/trainer-pass-products")
def webapp_trainer_pass_products_page():
    """Serve the trainer pass products Mini App (subscription products for sale)."""
    path = _WEBAPP_DIR / "trainer-pass-products.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/trainer-pay-subscription")
def webapp_trainer_pay_subscription_page():
    """Serve the trainer 'Pay subscription' Mini App: redirects to payment_url from API."""
    path = _WEBAPP_DIR / "trainer-pay-subscription.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/trainer-clients")
def webapp_trainer_clients_page():
    """Serve the trainer 'Clients' Mini App: list of clients with at least one booking."""
    path = _WEBAPP_DIR / "trainer-clients.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/client-buy-pass")
def webapp_client_buy_pass_page():
    """Serve the client 'Buy pass' Mini App (?trainer_id=..., optional trainer_name=...)."""
    path = _WEBAPP_DIR / "client-buy-pass.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/client-passes")
def webapp_client_passes_page():
    """Serve the client 'My passes' Mini App (list of owned абонементы, redeem link)."""
    path = _WEBAPP_DIR / "client-passes.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/client-certificates")
def webapp_client_certificates_page():
    """Serve the client 'My certificates' Mini App (list of issued certificates)."""
    path = _WEBAPP_DIR / "client-certificates.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/health")
async def health() -> dict[str, str]:
    """
    Liveness + readiness: DB must be reachable for 200.
    Optional S3: reported as ok/skip/error; 503 only on DB failure.
    """
    result: dict[str, str] = {"status": "ok", "db": "ok"}

    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"database unavailable: {e!s}",
        )

    settings = Settings()
    if settings.s3_endpoint and settings.s3_access_key and settings.s3_secret_key:
        try:
            from src.infrastructure.s3 import _get_client
            client = _get_client()
            client.head_bucket(Bucket=settings.s3_bucket)
            result["s3"] = "ok"
        except Exception:
            result["s3"] = "error"
    else:
        result["s3"] = "skip"

    return result


app.include_router(public_router)
app.include_router(trainers_router)
app.include_router(upload_router)
app.include_router(webapp_router)
app.include_router(webhooks_router)
