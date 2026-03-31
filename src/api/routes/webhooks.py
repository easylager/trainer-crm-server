"""
Webhooks from external services (payment gateway, etc.).

bePaid: HTTP Basic (shop id + secret) when credentials are configured; idempotent invoice handling
in subscription use cases.
"""
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.bepaid_webhook_auth import verify_bepaid_webhook_http_basic
from src.api.deps import get_session
from src.application.subscription_use_cases import confirm_subscription_invoice_after_payment
from src.shared.config import Settings

logger = logging.getLogger(__name__)

TRACKING_PREFIX_INVOICE = "inv_"

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/bepaid")
async def bepaid_webhook(request: Request, session: AsyncSession = Depends(get_session)):
    """bePaid notification: transaction status updates for trainer subscription invoices."""
    settings = Settings()
    verify_bepaid_webhook_http_basic(request, settings.bepaid_shop_id, settings.bepaid_secret_key)
    try:
        body = await request.json()
    except Exception as e:
        logger.warning("bepaid webhook: invalid JSON %s", e)
        return {}

    transaction = body.get("transaction") if isinstance(body, dict) else None
    if not transaction or not isinstance(transaction, dict):
        logger.warning("bepaid webhook: missing transaction")
        return {}

    tracking_id = transaction.get("tracking_id")
    status = (transaction.get("status") or "").lower()
    uid = transaction.get("uid")

    if not tracking_id:
        logger.warning("bepaid webhook: missing tracking_id")
        return {}

    if status != "successful":
        logger.debug("bepaid webhook: status=%s tracking_id=%s, skipping", status, tracking_id)
        return {}

    payment_external_id = str(uid)[:256] if uid is not None else f"bepaid-{tracking_id}"

    # Subscription invoice: tracking_id = "inv_{invoice_id}"
    if isinstance(tracking_id, str) and tracking_id.startswith(TRACKING_PREFIX_INVOICE):
        try:
            invoice_id = int(tracking_id[len(TRACKING_PREFIX_INVOICE) :])
        except ValueError:
            logger.warning("bepaid webhook: invalid invoice tracking_id %s", tracking_id)
            return {}
        ok = await confirm_subscription_invoice_after_payment(
            session, invoice_id, payment_external_id
        )
        if ok:
            logger.info("bepaid webhook: confirmed subscription invoice_id=%s", invoice_id)
        else:
            logger.warning("bepaid webhook: confirm subscription failed invoice_id=%s", invoice_id)
        return {}

    # Unknown tracking_id: currently only invoices are supported.
    logger.warning("bepaid webhook: unknown tracking_id %s (no handler)", tracking_id)
    return {}
