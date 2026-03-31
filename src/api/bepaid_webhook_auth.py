"""
bePaid webhook: HTTP Basic auth (Shop ID + Secret Key).

https://docs.bepaid.by/en/using_api/webhooks/ — notifications use Basic auth with shop credentials.
Optional RSA verification via Content-Signature + shop public key can be added if required by policy.
"""
import base64
import binascii
import logging
import secrets

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


def verify_bepaid_webhook_http_basic(
    request: Request,
    shop_id: str | None,
    secret_key: str | None,
) -> None:
    """
    When both shop_id and secret_key are configured, require valid Authorization: Basic.

    If either is unset (local dev / payments disabled), skip verification so tests and manual
    calls work without gateway credentials.
    """
    sid = (shop_id or "").strip()
    sk = (secret_key or "").strip()
    if not sid or not sk:
        return

    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Basic "):
        logger.warning("bepaid webhook: missing or non-Basic Authorization")
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        raw = base64.b64decode(auth[6:].strip(), validate=True)
        decoded = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if ":" not in decoded:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user, pwd = decoded.split(":", 1)
    if not secrets.compare_digest(user, sid) or not secrets.compare_digest(pwd, sk):
        logger.warning("bepaid webhook: Basic auth mismatch")
        raise HTTPException(status_code=401, detail="Unauthorized")
