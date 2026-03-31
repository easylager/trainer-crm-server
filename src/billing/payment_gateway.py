"""
Payment gateway adapter: create checkout session and get redirect URL.
bePaid: POST to checkout API, return redirect_url for client.
When credentials not set, returns stub URL for testing (no real charge).
"""
import base64
import logging
from typing import Any

import httpx

from src.shared.config import Settings

logger = logging.getLogger(__name__)


def _auth_header(shop_id: str, secret_key: str) -> str:
    raw = f"{shop_id}:{secret_key}"
    return "Basic " + base64.b64encode(raw.encode()).decode()


async def create_checkout(
    amount_cents: int,
    currency: str,
    description: str,
    tracking_id: str,
    return_url: str,
    notification_url: str,
    *,
    success_url: str | None = None,
    decline_url: str | None = None,
    fail_url: str | None = None,
    cancel_url: str | None = None,
    test: bool | None = None,
) -> dict[str, Any]:
    """
    Create checkout session at provider. Returns {"payment_url": str, "transaction_id": str | None}.
    If credentials not set, returns payment_url = return_url with ?payment_stub=1&tracking_id=... for testing.
    """
    settings = Settings()
    shop_id = settings.bepaid_shop_id
    secret_key = settings.bepaid_secret_key
    base_url = (settings.bepaid_checkout_base_url or "").rstrip("/")
    sandbox = test if test is not None else settings.payment_sandbox

    if not shop_id or not secret_key or not base_url:
        # Stub: no real payment, client can redirect to return_url and we'll simulate success in tests
        stub_url = return_url + ("&" if "?" in return_url else "?") + f"payment_stub=1&tracking_id={tracking_id}"
        logger.info("Payment gateway: no credentials, returning stub payment_url")
        return {"payment_url": stub_url, "transaction_id": None}

    url = f"{base_url}/ctp/api/checkouts"
    payload = {
        "checkout": {
            "test": sandbox,
            "transaction_type": "payment",
            "order": {
                "amount": amount_cents,
                "currency": currency,
                "description": description[:255] if description else "Оплата",
                "tracking_id": tracking_id,
            },
            "settings": {
                "return_url": return_url,
                "success_url": success_url or return_url,
                "decline_url": decline_url or return_url,
                "fail_url": fail_url or return_url,
                "cancel_url": cancel_url or return_url,
                "notification_url": notification_url,
                "language": "ru",
            },
        }
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-API-Version": "2",
        "Authorization": _auth_header(shop_id, secret_key),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code != 201 and resp.status_code != 200:
        logger.warning("bePaid checkout failed: %s %s", resp.status_code, resp.text[:500])
        raise ValueError(f"Payment gateway error: {resp.status_code}")
    data = resp.json()
    checkout = data.get("checkout") or {}
    redirect_url = checkout.get("redirect_url") or ""
    token = checkout.get("token")
    if not redirect_url:
        logger.warning("bePaid response missing redirect_url: %s", data)
        raise ValueError("Payment gateway: no redirect_url in response")
    return {"payment_url": redirect_url, "transaction_id": token or tracking_id}
