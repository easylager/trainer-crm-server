"""
Validate Telegram Web App initData (Mini App). Used by API to authenticate trainer.
See: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
from urllib.parse import unquote, parse_qsl


def validate_init_data(init_data: str, bot_token: str) -> bool:
    """
    Verify that init_data was sent by Telegram (HMAC-SHA256 with bot token).
    init_data: raw query string; when passed via URL query param it may be encoded once, we decode first.
    """
    if not init_data or not bot_token:
        return False
    try:
        # When init_data comes from query param it can be URL-encoded once by the client
        raw = unquote(init_data)
        pairs = parse_qsl(raw, keep_blank_values=True)
        vals = {k: unquote(v) for k, v in pairs}
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
        return hmac.compare_digest(hash_computed, hash_received)
    except Exception:
        return False


def parse_user_id_from_init_data(init_data: str) -> int | None:
    """
    Parse telegram user id from init_data. Only call after validate_init_data.
    """
    if not init_data:
        return None
    try:
        raw = unquote(init_data)
        pairs = parse_qsl(raw, keep_blank_values=True)
        vals = {k: unquote(v) for k, v in pairs}
        user_str = vals.get("user")
        if not user_str:
            return None
        import json
        user = json.loads(user_str)
        return int(user.get("id"))
    except Exception:
        return None
