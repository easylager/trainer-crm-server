"""
Validate Telegram Web App initData (Mini App). Used by API to authenticate trainer.
See: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import time
from urllib.parse import unquote, parse_qsl

from src.shared.config import Settings


class InitDataAuthError(Exception):
    """initData failed HMAC, auth_date window, or has no user id."""


def _parse_init_data_vals(init_data: str) -> dict[str, str]:
    raw = unquote(init_data)
    pairs = parse_qsl(raw, keep_blank_values=True)
    return {k: unquote(v) for k, v in pairs}


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_sec: int | None = None,
    clock_skew_sec: int | None = None,
    now: float | None = None,
) -> bool:
    """
    Verify init_data: HMAC-SHA256 with bot token, then ``auth_date`` freshness (anti-replay).

    ``init_data``: raw query string; when passed via URL query param it may be encoded once, we decode first.

    For tests, pass ``now`` (fixed Unix time) and/or ``max_age_sec`` / ``clock_skew_sec`` to avoid Settings.
    """
    if not init_data or not bot_token:
        return False
    try:
        vals = _parse_init_data_vals(init_data)
        hash_received = vals.get("hash")
        if not hash_received:
            return False
        # Data-check-string: all params except hash, sorted (official docs). Include signature if present.
        keys_for_check = [k for k in sorted(vals.keys()) if k != "hash"]
        data_check_string = "\n".join(f"{k}={vals[k]}" for k in keys_for_check)
        # Secret key: HMAC-SHA256 with "WebAppData" as KEY and bot_token as MESSAGE (per Telegram + community impls)
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256,
        ).digest()
        hash_computed = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(hash_computed, hash_received):
            return False
        # Anti-replay: reject stale or wildly future timestamps (Telegram docs recommend checking auth_date).
        auth_raw = vals.get("auth_date")
        if auth_raw is None or auth_raw == "":
            return False
        auth_ts = int(auth_raw)
        t = now if now is not None else time.time()
        max_age = max_age_sec if max_age_sec is not None else Settings().telegram_webapp_init_data_max_age_sec
        skew = clock_skew_sec if clock_skew_sec is not None else Settings().telegram_webapp_init_data_clock_skew_sec
        if auth_ts > t + skew:
            return False
        if t - auth_ts > max_age:
            return False
        return True
    except Exception:
        return False


def require_telegram_user_id(
    init_data: str,
    bot_token: str,
    *,
    max_age_sec: int | None = None,
    clock_skew_sec: int | None = None,
    now: float | None = None,
) -> int:
    """
    Validate initData (same rules as ``validate_init_data``) and return Telegram user id.
    Raises InitDataAuthError if invalid, expired, or user missing.
    """
    if not validate_init_data(
        init_data,
        bot_token,
        max_age_sec=max_age_sec,
        clock_skew_sec=clock_skew_sec,
        now=now,
    ):
        raise InitDataAuthError("invalid_or_expired")
    telegram_id = parse_user_id_from_init_data(init_data)
    if not telegram_id:
        raise InitDataAuthError("no_user")
    return telegram_id


def parse_user_id_from_init_data(init_data: str) -> int | None:
    """
    Parse telegram user id from init_data. Only call after validate_init_data.
    """
    if not init_data:
        return None
    try:
        vals = _parse_init_data_vals(init_data)
        user_str = vals.get("user")
        if not user_str:
            return None
        import json
        user = json.loads(user_str)
        return int(user.get("id"))
    except Exception:
        return None
