"""FastAPI app: health check and API routers. No business logic here."""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)

from sqlalchemy import text

from src.api.routes import (
    public_router,
    trainers_router,
    upload_router,
    webapp_router,
    webhooks_router,
)
from src.api.routes.webapp_trainer_profile import router as webapp_trainer_profile_router
from src.infrastructure.db import async_session_factory
from src.api.middleware.http_limits import ApiRateLimitMiddleware, MaxBodySizeMiddleware
from src.shared.config import Settings
from src.shared.logging_redact import sanitize_validation_errors_for_log
from src.shared.sentry_init import init_sentry

init_sentry(Settings(), "api")

app = FastAPI(title="Trainer CRM API")

# Epic D: rate limit /api (except webhooks), body size when Content-Length is set (inner runs first on request).
app.add_middleware(ApiRateLimitMiddleware)
app.add_middleware(MaxBodySizeMiddleware)

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
    """Same shape as default FastAPI 422: detail = list of {loc, msg, type, ...} for clients (Mini App maps loc → fields)."""
    errs = exc.errors()
    logger.warning("Request validation failed: %s", sanitize_validation_errors_for_log(errs))
    # ctx may hold Exception instances (e.g. ValueError from Pydantic) — not JSON-serializable raw.
    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": errs}))


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
def webapp_schedule_page(request: Request):
    """Legacy URL: единый экран расписания — редактор (вкладки + записи)."""
    q = request.url.query
    target = "/webapp/schedule-editor" + (f"?{q}" if q else "")
    return RedirectResponse(url=target, status_code=302)


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
def webapp_trainer_bookings_page(request: Request):
    """Legacy URL: bookings merged into schedule editor Mini App."""
    q = request.url.query
    target = "/webapp/schedule-editor" + (f"?{q}" if q else "")
    return RedirectResponse(url=target, status_code=302)


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


@app.get("/webapp/client-home")
def webapp_client_home_page():
    """Client hub: contextual hero, upcoming bookings, links to catalog / bookings / requests / passes."""
    path = _WEBAPP_DIR / "client-home.html"
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


@app.get("/webapp/admin-subscription-tiers")
def webapp_admin_subscription_tiers_page():
    """Serve the admin subscription tiers Mini App (pricing for CRM/Online/Analytics)."""
    path = _WEBAPP_DIR / "admin-subscription-tiers.html"
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


@app.get("/webapp/trainer-subscription")
def webapp_trainer_subscription_page():
    """Serve the trainer 'Subscription tiers' Mini App: CRM/Online/Analytics tier selection."""
    path = _WEBAPP_DIR / "trainer-subscription.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/trainer-profile")
def webapp_trainer_profile_page():
    """Trainer profile editor (single Mini App): анкета, фото, услуги, модерация."""
    path = _WEBAPP_DIR / "trainer-profile.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/trainer-faq")
def webapp_trainer_faq_page():
    """Trainer FAQ Mini App: частые вопросы и ответы в едином визуальном стиле CRM."""
    path = _WEBAPP_DIR / "trainer-faq.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/trainer-profile.html")
def webapp_trainer_profile_html_alias():
    """Bookmark/typo alias: canonical URL has no .html (same file as /webapp/trainer-profile)."""
    return RedirectResponse(url="/webapp/trainer-profile", status_code=302)


@app.get("/webapp/trainer-profile-readiness")
def webapp_trainer_profile_readiness_legacy():
    """Legacy URL: same Mini App, anchor to блоку модерации (was separate HTML + meta refresh)."""
    return RedirectResponse(url="/webapp/trainer-profile#moderation", status_code=302)


@app.get("/webapp/trainer-clients")
def webapp_trainer_clients_page():
    """Serve the trainer 'Clients' Mini App: list of clients with at least one booking."""
    path = _WEBAPP_DIR / "trainer-clients.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/trainer-home")
def webapp_trainer_home_page():
    """Trainer hub: upcoming bookings + links to schedule, clients, requests, etc."""
    path = _WEBAPP_DIR / "trainer-home.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/trainer-referral")
def webapp_trainer_referral_page():
    """B2B referral program: link, balance, invited trainers."""
    path = _WEBAPP_DIR / "trainer-referral.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/referral-rules")
def webapp_referral_rules_page():
    """Public referral program rules (BY)."""
    path = _WEBAPP_DIR / "referral-rules.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/palette-ice-reference")
@app.get("/webapp/palette-ice-reference.html")
def webapp_palette_ice_reference():
    """Static design reference: ice palette variants (browser preview, not a Mini App entry)."""
    path = _WEBAPP_DIR / "palette-ice-reference.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
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


@app.get("/webapp/client-passes-certificates")
def webapp_client_passes_certificates_page():
    """Serve combined client Mini App: passes + certificates (tabbed)."""
    path = _WEBAPP_DIR / "client-passes-certificates.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/theme.css")
def webapp_theme_css():
    """Serve theme.css for Mini Apps."""
    path = _WEBAPP_DIR / "theme.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(path, media_type="text/css")


@app.get("/webapp/mini-app-components.css")
def webapp_components_css():
    """Serve mini-app-components.css for Mini Apps."""
    path = _WEBAPP_DIR / "mini-app-components.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(path, media_type="text/css")


@app.get("/webapp/mini-app-trainer-nav.css")
def webapp_trainer_nav_css():
    """Trainer header buttons — must load after per-page <style> (mobile WebView)."""
    path = _WEBAPP_DIR / "mini-app-trainer-nav.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(path, media_type="text/css")


@app.get("/webapp/client-mini-app-theme.js")
def webapp_client_mini_app_theme_js():
    """Shared Telegram theme + CRM palette for client Mini Apps."""
    path = _WEBAPP_DIR / "client-mini-app-theme.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_WEBAPP_NO_CACHE_HEADERS,
    )


@app.get("/webapp/mini-app-trainer-home.js")
def webapp_mini_app_trainer_home_js():
    """Trainer hub navigation (init_data preserved); loaded by trainer Mini App pages."""
    path = _WEBAPP_DIR / "mini-app-trainer-home.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_WEBAPP_NO_CACHE_HEADERS,
    )


@app.get("/webapp/mini-app-trainer-gate.js")
def webapp_mini_app_trainer_gate_js():
    """Trainer Mini App access gate; loaded by trainer hub, subscription, schedule, etc."""
    path = _WEBAPP_DIR / "mini-app-trainer-gate.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_WEBAPP_NO_CACHE_HEADERS,
    )


@app.get("/webapp/mini-app-trainer-celebration.js")
def webapp_mini_app_trainer_celebration_js():
    """Post-purchase hub banner (sessionStorage helpers); loaded by trainer-home and subscription pages."""
    path = _WEBAPP_DIR / "mini-app-trainer-celebration.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_WEBAPP_NO_CACHE_HEADERS,
    )


@app.get("/webapp/mini-app-client-home.js")
def webapp_mini_app_client_home_js():
    """Client hub navigation (init_data preserved); loaded by client Mini App pages."""
    path = _WEBAPP_DIR / "mini-app-client-home.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_WEBAPP_NO_CACHE_HEADERS,
    )


@app.get("/webapp/mini-app-client-nav.css")
def webapp_mini_app_client_nav_css():
    """Client header — Главная button; load after page inline styles."""
    path = _WEBAPP_DIR / "mini-app-client-nav.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(path, media_type="text/css")


@app.get("/webapp/mini-app-confirm.js")
def webapp_mini_app_confirm_js():
    """Themed confirm dialog; used by schedule-editor, trainer-requests, etc."""
    path = _WEBAPP_DIR / "mini-app-confirm.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_WEBAPP_NO_CACHE_HEADERS,
    )


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
webapp_router.include_router(webapp_trainer_profile_router)
app.include_router(webapp_router)
app.include_router(webhooks_router)
