"""FastAPI app: health check and API routers. No business logic here."""
import logging
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.exc import InterfaceError, OperationalError, TimeoutError as SATimeoutError
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.routes import (
    public_router,
    redirects_router,
    trainers_router,
    upload_router,
    webapp_router,
    webhooks_router,
)
from src.api.routes.public_arenas import router as public_arenas_router
from src.api.routes.webapp_trainer_profile import router as webapp_trainer_profile_router
from src.api.routes.public import issue_trainer_join_redirect
from src.application.landing_manifest import inject_landing_html
from src.infrastructure.db import async_session_factory
from src.api.middleware.http_limits import ApiRateLimitMiddleware, MaxBodySizeMiddleware
from src.api.middleware.maintenance import MaintenanceModeMiddleware
from src.api.middleware.trainer_webapp_benchmark import TrainerWebappBenchmarkMiddleware
from src.shared.catalog_entry import catalog_browse_redirect
from src.shared.outage import (
    SERVICE_UNAVAILABLE_CODE,
    service_unavailable_payload,
)
from src.api.miniapp_auth.deps import MINIAPP_AUTH_ERROR_HEADER
from src.shared.config import Settings
from src.shared.logging_redact import sanitize_validation_errors_for_log
from src.shared.sentry_init import init_sentry

_settings_for_bench = Settings()
init_sentry(_settings_for_bench, "api")

# OpenAPI UI exposes route surface area — dev only (DEBUG=true).
_api_docs_enabled = bool(_settings_for_bench.debug)
app = FastAPI(
    title="Trainer CRM API",
    docs_url="/docs" if _api_docs_enabled else None,
    redoc_url="/redoc" if _api_docs_enabled else None,
    openapi_url="/openapi.json" if _api_docs_enabled else None,
)

if _settings_for_bench.trainer_webapp_benchmark_log or _settings_for_bench.trainer_webapp_benchmark_slow_ms is not None:
    logger.info(
        "Trainer webapp benchmark enabled: log_every=%s slow_ms=%s — this API process only; "
        "set TRAINER_WEBAPP_BENCHMARK_LOG on the Uvicorn/Railway service that serves /api and /webapp, then redeploy. "
        "Lines: BENCH trainer_webapp kind=api|page|asset (grep BENCH trainer_webapp).",
        _settings_for_bench.trainer_webapp_benchmark_log,
        _settings_for_bench.trainer_webapp_benchmark_slow_ms,
    )

# Epic D: rate limit /api (except webhooks), body size when Content-Length is set (inner runs first on request).
app.add_middleware(ApiRateLimitMiddleware)
app.add_middleware(MaxBodySizeMiddleware)
# Planned maintenance: inside CORS so Mini Apps can read the 503 body.
app.add_middleware(MaintenanceModeMiddleware)

# Mini Apps open in Telegram WebView; origin may be tunnel URL or telegram.org. Allow all so fetch() works.
# SEC-G3: keep allow_credentials=False with allow_origins=["*"] — combining True + "*" is invalid per spec and unsafe.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=[MINIAPP_AUTH_ERROR_HEADER, "X-Ice-Studio-Outage"],
)
# Epic D: gzip JSON/HTML/CSS/JS when client sends Accept-Encoding: gzip (nginx can add brotli in front).
# Last added = outermost on the stack — compresses the final response body.
app.add_middleware(GZipMiddleware, minimum_size=800, compresslevel=6)
# Outermost: full wall time for trainer Mini App API (after gzip/CORS/body/rate-limit stack).
app.add_middleware(TrainerWebappBenchmarkMiddleware)


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(_request, exc: RequestValidationError):
    """Same shape as default FastAPI 422: detail = list of {loc, msg, type, ...} for clients (Mini App maps loc → fields)."""
    errs = exc.errors()
    logger.warning("Request validation failed: %s", sanitize_validation_errors_for_log(errs))
    # ctx may hold Exception instances (e.g. ValueError from Pydantic) — not JSON-serializable raw.
    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": errs}))


def _service_unavailable_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=service_unavailable_payload(),
        headers={
            "Retry-After": "60",
            "X-Ice-Studio-Outage": SERVICE_UNAVAILABLE_CODE,
        },
    )


@app.exception_handler(OperationalError)
@app.exception_handler(InterfaceError)
@app.exception_handler(SATimeoutError)
@app.exception_handler(ConnectionRefusedError)
async def _db_unavailable_exception_handler(_request: Request, exc: Exception):
    """Postgres down / pool exhausted → stable 503 so Mini Apps show maintenance, not empty lists."""
    logger.warning("database unavailable: %s", exc)
    return _service_unavailable_response()


# Telegram Web App: trainer schedule (Mini App)
_WEBAPP_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "webapp"
_LANDING_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "landing"
_LOGOS_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "logos"

# SEC-G2: discourage MIME sniffing on all Mini App responses using these header sets (HTML + JS/CSS).
_WEBAPP_SNIFFING = {"X-Content-Type-Options": "nosniff"}

# No-cache for Mini App HTML: one extra request per open, but users always get latest after deploy.
# Alternative: max-age=60 (cache 1 min) — faster repeat opens, may see stale version once after deploy.
# Full CSP is not applied here: pages mix inline scripts (theme, SDK) and many external script/style URLs — a safe policy would be page-specific.
_WEBAPP_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    **_WEBAPP_SNIFFING,
}

# Long-lived cache for split hub assets (HTML stays no-store).
# trainer-home.html links these with ?v=… — bump the query in HTML when the file changes so clients refresh.
_WEBAPP_IMMUTABLE_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
    **_WEBAPP_SNIFFING,
}


def _webapp_file_response(path: Path):
    return FileResponse(
        path,
        media_type="text/html",
        headers=_WEBAPP_NO_CACHE_HEADERS,
    )


def _webapp_versioned_asset_cache_headers(request: Request) -> dict[str, str]:
    """Long cache only when the client sends ?v= (version bump in HTML); else avoid stale immutable for legacy links."""
    if request.query_params.get("v"):
        return _WEBAPP_IMMUTABLE_CACHE_HEADERS
    return _WEBAPP_NO_CACHE_HEADERS


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
def webapp_catalog_page(request: Request):
    """Trainer card Mini App. Browse without trainer_id goes to Ice (TASK-084)."""
    target = catalog_browse_redirect(request.query_params)
    if target:
        return RedirectResponse(url=target, status_code=307)
    path = _WEBAPP_DIR / "catalog.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/arena")
@app.get("/webapp/arena.html")
def webapp_arena_page():
    """TASK-052: public Ice Discovery arena card Mini App."""
    path = _WEBAPP_DIR / "arena.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/ice")
@app.get("/webapp/ice.html")
def webapp_ice_tab_page():
    """TASK-053: Ice tab arena list Mini App."""
    path = _WEBAPP_DIR / "ice.html"
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


@app.get("/webapp/client-saved-trainers")
def webapp_client_saved_trainers_page():
    """Client: bookmarked trainers (same API as catalog heart / save)."""
    path = _WEBAPP_DIR / "client-saved-trainers.html"
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


@app.get("/webapp/client-family-access")
def webapp_client_family_access_page():
    """Client: invite extra Telegram accounts to share one client card (bookings, passes)."""
    path = _WEBAPP_DIR / "client-family-access.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/client-family-access-main.js")
def webapp_client_family_access_main_js(request: Request):
    path = _WEBAPP_DIR / "client-family-access-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/client-stats")
def webapp_client_stats_page():
    """Client: completed-session stats and gentle rhythm hints (motivation, no leaderboards)."""
    path = _WEBAPP_DIR / "client-stats.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/client-stats-main.js")
def webapp_client_stats_main_js(request: Request):
    """Client activity screen logic."""
    path = _WEBAPP_DIR / "client-stats-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


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
    """Serve the admin pulse Mini App (today, money, action queue, live trainers)."""
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


@app.get("/webapp/admin-money")
def webapp_admin_money_page():
    """Serve the admin Money tab Mini App (MRR/ARR, GMV, top payers, pending invoices, subscription mix)."""
    path = _WEBAPP_DIR / "admin-money.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/admin-trainers")
def webapp_admin_trainers_page():
    """Admin trainers hub — paying / trial / live / sleeping, not the empty roster dump."""
    path = _WEBAPP_DIR / "admin-trainers.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/admin-growth")
def webapp_admin_growth_page():
    """Serve the admin Growth tab Mini App (new trainer cohorts, trial→paid, referral program)."""
    path = _WEBAPP_DIR / "admin-growth.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/admin-retention")
def webapp_admin_retention_page():
    """Serve the admin Retention tab Mini App (churn, expiring subs, sleeping trainers, revival)."""
    path = _WEBAPP_DIR / "admin-retention.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/admin-engagement")
def webapp_admin_engagement_page():
    """Serve the admin Engagement tab Mini App (DAU/WAU/MAU, feature usage, top active trainers, DoW heat)."""
    path = _WEBAPP_DIR / "admin-engagement.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/admin-clients")
def webapp_admin_clients_page():
    """Serve the admin Clients tab Mini App (clients funnel, repeat rate, top cities/trainers, recent requests)."""
    path = _WEBAPP_DIR / "admin-clients.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/admin-activity")
def webapp_admin_activity_page():
    """Admin audit log timeline — trainer/client/admin actions."""
    path = _WEBAPP_DIR / "admin-activity.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/admin-product-analytics")
def webapp_admin_product_analytics_page():
    """Product analytics dashboard — activation funnel, proof-of-value, correlation table."""
    path = _WEBAPP_DIR / "admin-product-analytics.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/admin-product-analytics-main.js")
def webapp_admin_product_analytics_main_js(request: Request):
    """Product analytics page logic. Relative script URL from ``/webapp/admin-product-analytics`` resolves here."""
    path = _WEBAPP_DIR / "admin-product-analytics-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


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


@app.api_route("/webapp/trainer-onboarding", methods=["GET", "HEAD"])
def webapp_trainer_onboarding_page():
    """First run: the only setup screen a trainer ever sees — sports + weekly grid, then the link."""
    path = _WEBAPP_DIR / "trainer-onboarding.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/trainer-onboarding-main.js")
def webapp_trainer_onboarding_main_js(request: Request):
    """First-run screen logic. Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "trainer-onboarding-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.api_route("/webapp/trainer-home", methods=["GET", "HEAD"])
def webapp_trainer_home_page():
    """Trainer hub: upcoming bookings + links to schedule, clients, requests, etc."""
    path = _WEBAPP_DIR / "trainer-home.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    return _webapp_file_response(path)


@app.get("/webapp/trainer-groups")
def webapp_trainer_groups_page():
    """Trainer cohorts: groups, roster, catalog recruitment."""
    path = _WEBAPP_DIR / "trainer-groups.html"
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


@app.get("/webapp/trainer-collective")
def webapp_trainer_collective_page():
    """Collective studio admin for members/owners (Wave P1)."""
    path = _WEBAPP_DIR / "trainer-collective.html"
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


@app.get("/webapp/client-register")
def webapp_client_register_page(trainer_id: Optional[int] = Query(None)):
    """Client self-registration Mini App: collect phone + name, link to trainer roster.

    Embeds ``trainer_id`` in a meta tag so the Mini App still works when the WebView
    drops ``location.search`` (Continue would otherwise no-op with a hidden global error).
    """
    path = _WEBAPP_DIR / "client-register.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Web App not found")
    html = path.read_text(encoding="utf-8")
    tid = ""
    if trainer_id is not None and trainer_id > 0:
        tid = str(int(trainer_id))
    meta = f'  <meta name="trainer-crm-register-trainer-id" content="{tid}">\n'
    marker = "</head>"
    if marker not in html:
        raise HTTPException(status_code=500, detail="Invalid client-register template")
    html = html.replace(marker, meta + marker, 1)
    return HTMLResponse(
        content=html,
        media_type="text/html",
        headers=_WEBAPP_NO_CACHE_HEADERS,
    )


@app.get("/webapp/client-register-main.js")
def webapp_client_register_main_js(request: Request):
    """Client self-registration page logic (split from client-register.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "client-register-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


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
def webapp_theme_css(request: Request):
    """Serve theme.css for Mini Apps. Prefer ``?v=…`` in HTML for long-lived cache after deploy."""
    path = _WEBAPP_DIR / "theme.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/admin-analytics-shared.css")
def webapp_admin_analytics_shared_css(request: Request):
    """Admin analytics tab Mini Apps (Money, Growth, Retention, …). Use ``?v=…`` for cache after deploy."""
    path = _WEBAPP_DIR / "admin-analytics-shared.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/admin-analytics-shared.js")
def webapp_admin_analytics_shared_js():
    """Shared fetch, formatters, drilldown for /webapp/admin-* analytics pages."""
    path = _WEBAPP_DIR / "admin-analytics-shared.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_WEBAPP_NO_CACHE_HEADERS,
    )


@app.get("/webapp/mini-app-components.css")
def webapp_components_css(request: Request):
    """Serve mini-app-components.css for Mini Apps. Prefer ``?v=…`` in HTML for long-lived cache after deploy."""
    path = _WEBAPP_DIR / "mini-app-components.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-arena-ribbon.css")
def webapp_arena_ribbon_css(request: Request):
    """Arena Depth + Ribbon pilot styles (TASK-017). Prefer ``?v=…`` for long-lived cache."""
    path = _WEBAPP_DIR / "mini-app-arena-ribbon.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-trainer-hub.css")
def webapp_trainer_hub_css(request: Request):
    """Trainer hub-only styles (trainer-home.html); use ``?v=…`` for long-lived cache."""
    path = _WEBAPP_DIR / "mini-app-trainer-hub.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-trainer-pending-inbox.css")
def webapp_trainer_pending_inbox_css(request: Request):
    """Pending bookings sheet (trainer-home, schedule-editor). Use ``?v=…`` for long-lived cache."""
    path = _WEBAPP_DIR / "mini-app-trainer-pending-inbox.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-trainer-nav.css")
def webapp_trainer_nav_css(request: Request):
    """Trainer header buttons. Use ``?v=…`` for long-lived cache (schedule-editor, etc.)."""
    path = _WEBAPP_DIR / "mini-app-trainer-nav.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-schedule-editor.css")
def webapp_schedule_editor_css(request: Request):
    """Schedule editor page styles (split from schedule-editor.html). Use ``?v=…`` for cache."""
    path = _WEBAPP_DIR / "mini-app-schedule-editor.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-full-height.js")
def webapp_mini_app_full_height_js(request: Request):
    """Wait for async Telegram SDK, then ready()+expand() — entry Mini Apps (no fullscreen)."""
    path = _WEBAPP_DIR / "mini-app-full-height.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-telegram-chrome.js")
def webapp_mini_app_telegram_chrome_js():
    """Telegram WebView quirks (focus, chrome); loaded by all Mini App HTML pages."""
    path = _WEBAPP_DIR / "mini-app-telegram-chrome.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_WEBAPP_NO_CACHE_HEADERS,
    )


@app.get("/webapp/mini-app-phone-field.js")
def webapp_mini_app_phone_field_js(request: Request):
    """Shared BY/RU phone dropdown + mask; load after mini-app-telegram-chrome.js."""
    path = _WEBAPP_DIR / "mini-app-phone-field.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


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


# Trainer counterparts of client-mini-app-theme.js. Twelve trainer pages link both files,
# but no route existed, so they 404'd and the trainer palette lock never ran — Telegram's
# own themeParams leaked through instead. Same no-store policy as the client theme script:
# a stale palette lock is exactly what these files exist to prevent.
@app.get("/webapp/mini-app-trainer-theme.js")
def webapp_mini_app_trainer_theme_js():
    """Shared Telegram theme + CRM palette for trainer Mini Apps."""
    path = _WEBAPP_DIR / "mini-app-trainer-theme.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_WEBAPP_NO_CACHE_HEADERS,
    )


@app.get("/webapp/mini-app-trainer-theme.css")
def webapp_mini_app_trainer_theme_css():
    """Trainer theme overrides (nav buttons, canvas lock); load after theme.css."""
    path = _WEBAPP_DIR / "mini-app-trainer-theme.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_WEBAPP_NO_CACHE_HEADERS,
    )


@app.get("/webapp/mini-app-client-theme.css")
def webapp_mini_app_client_theme_css():
    """Client theme overrides (tab bar, canvas lock); load after theme.css. Was also missing a route."""
    path = _WEBAPP_DIR / "mini-app-client-theme.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
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


@app.get("/webapp/trainer-home-main.js")
def webapp_trainer_home_main_js(request: Request):
    """Trainer hub page logic (split from trainer-home.html for cache + smaller HTML parse). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "trainer-home-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-trainer-pending-inbox.js")
def webapp_trainer_pending_inbox_js(request: Request):
    """Shared pending bookings sheet + batch confirm (trainer-home, schedule-editor). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-trainer-pending-inbox.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/trainer-client-relay-ui.js")
def webapp_trainer_client_relay_ui_js(request: Request):
    """Relay message sheet → POST relay-messages; trainer-home, schedule-editor, trainer-clients."""
    path = _WEBAPP_DIR / "trainer-client-relay-ui.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/trainer-relay-helpers.js")
def webapp_trainer_relay_helpers_js(request: Request):
    """DM vs relay eligibility; loaded with trainer-client-relay-ui on trainer-facing pages."""
    path = _WEBAPP_DIR / "trainer-relay-helpers.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/trainer-booking-context.js")
def webapp_trainer_booking_context_js(request: Request):
    """Shared booking-context picker; trainer-home, trainer-clients, schedule-editor."""
    path = _WEBAPP_DIR / "trainer-booking-context.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/schedule-editor-main.js")
def webapp_schedule_editor_main_js(request: Request):
    """Schedule editor page logic (split from schedule-editor.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "schedule-editor-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-catalog.css")
def webapp_catalog_css(request: Request):
    """Client catalog Mini App styles (split from catalog.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-catalog.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/catalog-main.js")
def webapp_catalog_main_js(request: Request):
    """Client catalog page logic (split from catalog.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "catalog-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/arena-card.css")
def webapp_arena_card_css(request: Request):
    """TASK-052 arena card styles. Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "arena-card.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/arena-card-model.js")
def webapp_arena_card_model_js(request: Request):
    """TASK-052 arena card view-model (pure). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "arena-card-model.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/arena-card.js")
def webapp_arena_card_js(request: Request):
    """TASK-052 arena card page logic. Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "arena-card.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/ice-tab.css")
def webapp_ice_tab_css(request: Request):
    """TASK-053 Ice tab styles. Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "ice-tab.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/ice-tab-model.js")
def webapp_ice_tab_model_js(request: Request):
    """TASK-053 Ice tab view-model (pure). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "ice-tab-model.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/ice-tab.js")
def webapp_ice_tab_js(request: Request):
    """TASK-053 Ice tab page logic. Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "ice-tab.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/ice-map-model.js")
def webapp_ice_map_model_js(request: Request):
    """TASK-054 Ice map view-model (pure). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "ice-map-model.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/ice-map.js")
def webapp_ice_map_js(request: Request):
    """TASK-054 Ice map (Yandex). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "ice-map.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/ice-teaser-model.js")
def webapp_ice_teaser_model_js(request: Request):
    """TASK-055 hub teaser view-model (pure). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "ice-teaser-model.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/trainer-arena-chips-model.js")
def webapp_trainer_arena_chips_model_js(request: Request):
    """TASK-055 trainer-card arena chips view-model (pure). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "trainer-arena-chips-model.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-trainer-groups.css")
def webapp_trainer_groups_css(request: Request):
    """Trainer training-groups Mini App styles (split from trainer-groups.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-trainer-groups.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/trainer-groups-main.js")
def webapp_trainer_groups_main_js(request: Request):
    """Trainer training-groups page logic (split from trainer-groups.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "trainer-groups-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-trainer-stats.css")
def webapp_trainer_stats_css(request: Request):
    """Trainer stats Mini App styles (split from trainer-stats.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-trainer-stats.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/trainer-stats-main.js")
def webapp_trainer_stats_main_js(request: Request):
    """Trainer stats page logic (split from trainer-stats.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "trainer-stats-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-trainer-clients.css")
def webapp_trainer_clients_css(request: Request):
    """Trainer clients list styles (split from trainer-clients.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-trainer-clients.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/trainer-clients-main.js")
def webapp_trainer_clients_main_js(request: Request):
    """Trainer clients list logic (split from trainer-clients.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "trainer-clients-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-trainer-pass-products.css")
def webapp_trainer_pass_products_css(request: Request):
    """Trainer pass products styles (split from trainer-pass-products.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-trainer-pass-products.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/trainer-pass-products-main.js")
def webapp_trainer_pass_products_main_js(request: Request):
    """Trainer pass products logic (split from trainer-pass-products.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "trainer-pass-products-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-client-requests.css")
def webapp_client_requests_css(request: Request):
    """Client requests page styles (split from client-requests.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-client-requests.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/client-requests-main.js")
def webapp_client_requests_main_js(request: Request):
    """Client requests page logic (split from client-requests.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "client-requests-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-client-home.css")
def webapp_client_home_page_css(request: Request):
    """Client hub page styles (split from client-home.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-client-home.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/client-home-main.js")
def webapp_client_home_main_js(request: Request):
    """Client hub page logic (split from client-home.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "client-home-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/client-profile-switcher.js")
def webapp_client_profile_switcher_js(request: Request):
    """EPIC1: profile chip + «Добавить ребёнка» (+ X-Profile-Id fetch patch)."""
    path = _WEBAPP_DIR / "client-profile-switcher.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-trainer-profile.css")
def webapp_trainer_profile_css(request: Request):
    """Trainer profile page styles (split from trainer-profile.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-trainer-profile.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/trainer-profile-main.js")
def webapp_trainer_profile_main_js(request: Request):
    """Trainer profile page logic (split from trainer-profile.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "trainer-profile-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
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
def webapp_mini_app_client_nav_css(request: Request):
    """Client header — Главная button. Use ``?v=…`` for long-lived cache (catalog, etc.)."""
    path = _WEBAPP_DIR / "mini-app-client-nav.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-client-shell.css")
def webapp_mini_app_client_shell_css(request: Request):
    """Client shell — bottom tab bar, more sheet, empty/skeleton. Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-client-shell.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-client-shell.js")
def webapp_mini_app_client_shell_js(request: Request):
    """Client shell — tab navigation, more sheet, navigate helpers. Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-client-shell.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-trainer-shell.css")
def webapp_mini_app_trainer_shell_css(request: Request):
    """Trainer shell — bottom tab bar + more sheet. Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-trainer-shell.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-trainer-shell.js")
def webapp_mini_app_trainer_shell_js(request: Request):
    """Trainer shell — tab navigation, more sheet, drill-down observer. Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-trainer-shell.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/mini-app-client-bookings.css")
def webapp_mini_app_client_bookings_css(request: Request):
    """Client bookings list/detail styles (split from client-bookings.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "mini-app-client-bookings.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/booking-client.js")
def webapp_booking_client_js(request: Request):
    """Shared client booking module (session, slots, submit, success). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "booking-client.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/booking-client.css")
def webapp_booking_client_css(request: Request):
    """Shared client booking styles (success, skeleton, sticky CTA). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "booking-client.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSS file not found")
    return FileResponse(
        path,
        media_type="text/css",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/booking-deeplink.js")
def webapp_booking_deeplink_js(request: Request):
    """Booking URL normalizer + book→catalog strangler shim. Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "booking-deeplink.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


@app.get("/webapp/client-saved-trainers-main.js")
def webapp_client_saved_trainers_main_js(request: Request):
    """Client saved-trainers page logic (split from client-saved-trainers.html). Use ``?v=…`` for long cache."""
    path = _WEBAPP_DIR / "client-saved-trainers-main.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="JS file not found")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers=_webapp_versioned_asset_cache_headers(request),
    )


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


_LANDING_ASSET_MEDIA = {
    ".css": "text/css",
    ".js": "application/javascript",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".json": "application/json",
}


@app.get("/")
def landing_page():
    """Glide marketing landing — vertical entry for trainers."""
    path = _LANDING_DIR / "index.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Landing not found")
    html = path.read_text(encoding="utf-8")
    try:
        html = inject_landing_html(html)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return HTMLResponse(content=html, media_type="text/html", headers=_WEBAPP_NO_CACHE_HEADERS)


@app.get("/join")
async def trainer_public_join(
    request: Request,
    ref: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Shareable public entry for trainers (social bio, QR). Mints one-time token → Telegram."""
    return await issue_trainer_join_redirect(request, session, referral_code=ref)


@app.get("/landing/{asset_path:path}")
def landing_asset(asset_path: str, request: Request):
    """Static assets for Glide landing (CSS/JS/images). Use ``?v=`` for long cache."""
    if ".." in asset_path or asset_path.startswith("/"):
        raise HTTPException(status_code=404, detail="Not found")
    path = (_LANDING_DIR / asset_path).resolve()
    try:
        path.relative_to(_LANDING_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    suffix = path.suffix.lower()
    media = _LANDING_ASSET_MEDIA.get(suffix, "application/octet-stream")
    cache = _webapp_versioned_asset_cache_headers(request)
    return FileResponse(path, media_type=media, headers=cache)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    """
    Process liveness only — no Postgres.

    Point the Railway HTTP healthcheck here. If the probe stays on ``/health``
    (which requires DB), a Postgres outage takes the API out of rotation and
    Mini Apps cannot even load the maintenance screen.
    """
    return {"status": "live"}


@app.get("/health")
@app.get("/health/ready")
async def health():
    """
    Readiness: DB must be reachable for 200.
    Optional S3: reported as ok/skip/error; 503 only on DB failure or MAINTENANCE_MODE.
    """
    if Settings().maintenance_mode:
        payload = service_unavailable_payload(db="skip")
        payload["status"] = "maintenance"
        payload["s3"] = "skip"
        return JSONResponse(
            status_code=503,
            content=payload,
            headers={"Retry-After": "60", "X-Ice-Studio-Outage": SERVICE_UNAVAILABLE_CODE},
        )

    result: dict[str, str] = {"status": "ok", "db": "ok"}

    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        logger.warning("health check: database unavailable: %s", e)
        payload = service_unavailable_payload(db="error")
        payload["s3"] = "skip"
        return JSONResponse(
            status_code=503,
            content=payload,
            headers={"Retry-After": "60", "X-Ice-Studio-Outage": SERVICE_UNAVAILABLE_CODE},
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
app.include_router(public_arenas_router)
app.include_router(redirects_router)
app.include_router(trainers_router)
app.include_router(upload_router)
webapp_router.include_router(webapp_trainer_profile_router)
app.include_router(webapp_router)
app.include_router(webhooks_router)


@app.middleware("http")
async def _static_webapp_cache_align(request: Request, call_next):
    """
    Epic C: same Cache-Control as explicit /webapp/<file> handlers — immutable when ``?v=`` is set,
    else no-store. Without this, Starlette StaticFiles default differs from versioned FileResponse routes.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/webapp"):
        for k, v in _webapp_versioned_asset_cache_headers(request).items():
            response.headers[k] = v
    return response


# Alias for repo path static/webapp — same files as explicit /webapp/* routes above (cache via middleware).
app.mount("/static/webapp", StaticFiles(directory=str(_WEBAPP_DIR)), name="static_webapp")
if _LOGOS_DIR.is_dir():
    app.mount("/logos", StaticFiles(directory=str(_LOGOS_DIR)), name="logos")
