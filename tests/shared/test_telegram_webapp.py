"""Telegram Web App initData: HMAC + auth_date (anti-replay)."""
import hashlib
import hmac
import json
from urllib.parse import quote

import pytest

from src.shared.telegram_webapp import (
    InitDataAuthError,
    require_telegram_user_id,
    validate_init_data,
)


def _build_signed_init_data(bot_token: str, *, user_id: int, auth_date: int) -> str:
    """Build query string with valid Web App hash (same algorithm as server)."""
    user_json = json.dumps({"id": user_id}, separators=(",", ":"))
    fields = {
        "auth_date": str(auth_date),
        "user": user_json,
    }
    keys_sorted = sorted(fields.keys())
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in keys_sorted)
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    hash_hex = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    pairs = [f"{quote(k, safe='')}={quote(fields[k], safe='')}" for k in keys_sorted]
    pairs.append(f"hash={hash_hex}")
    return "&".join(pairs)


def test_validate_init_data_accepts_fresh_auth_date():
    token = "123456:ABC-DEF"
    now = 1_700_000_000
    raw = _build_signed_init_data(token, user_id=42, auth_date=now)
    assert validate_init_data(raw, token, now=now, max_age_sec=86_400, clock_skew_sec=300) is True


def test_validate_init_data_rejects_stale_auth_date():
    token = "123456:ABC-DEF"
    now = 1_700_000_000
    old = now - 100_000  # well outside 1h window
    raw = _build_signed_init_data(token, user_id=42, auth_date=old)
    assert validate_init_data(raw, token, now=now, max_age_sec=3600, clock_skew_sec=300) is False


def test_validate_init_data_rejects_missing_auth_date():
    token = "123456:ABC-DEF"
    user_json = json.dumps({"id": 42}, separators=(",", ":"))
    fields = {"user": user_json}
    keys_sorted = sorted(fields.keys())
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in keys_sorted)
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    hash_hex = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"user={quote(user_json, safe='')}&hash={hash_hex}"
    assert validate_init_data(raw, token, now=1_700_000_000, max_age_sec=86_400) is False


def test_require_telegram_user_id_returns_id():
    token = "999888:ZZZ-YYY"
    now = 1_701_000_000
    raw = _build_signed_init_data(token, user_id=777, auth_date=now)
    assert require_telegram_user_id(raw, token, now=now, max_age_sec=86_400) == 777


def test_require_telegram_user_id_raises_when_stale():
    token = "999888:ZZZ-YYY"
    now = 1_701_000_000
    raw = _build_signed_init_data(token, user_id=777, auth_date=now - 200_000)
    with pytest.raises(InitDataAuthError):
        require_telegram_user_id(raw, token, now=now, max_age_sec=3600)
