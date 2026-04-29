"""
VK Mini Apps launch parameters: HMAC-SHA256 sign check (same scheme used by MAX messenger WebView).

Reference: https://github.com/VKCOM/vk-apps-launch-params (example ``python3.py``).
"""
from __future__ import annotations

import json
from base64 import b64encode
from hashlib import sha256
from hmac import HMAC
from urllib.parse import parse_qsl, urlencode

from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.shared.telegram_webapp import InitDataAuthError


def _parse_launch_query_to_map(raw: str) -> dict[str, str]:
    """Parse ``vk_*=...&sign=...`` string; tolerate a leading ``?``."""
    s = (raw or "").strip()
    if s.startswith("?"):
        s = s[1:]
    return dict(parse_qsl(s, keep_blank_values=True))


def vk_launch_params_signature_valid(query: dict[str, str], secret: str) -> bool:
    """Return True if ``sign`` matches VK's HMAC over sorted ``vk_*`` keys."""
    if not query.get("sign"):
        return False
    vk_subset = sorted(k for k in query if k.startswith("vk_"))
    if not vk_subset:
        return False
    ordered = {k: query[k] for k in vk_subset}
    hash_code = b64encode(
        HMAC(secret.encode("utf-8"), urlencode(ordered, doseq=True).encode("utf-8"), sha256).digest()
    ).decode("utf-8")
    if hash_code.endswith("="):
        hash_code = hash_code[:-1]
    fixed_hash = hash_code.replace("+", "-").replace("/", "_")
    return query.get("sign") == fixed_hash


def vk_launch_display_user_fields(query: dict[str, str]) -> dict[str, str | None]:
    """Best-effort first/last name from optional JSON ``vk_user`` launch param."""
    raw = query.get("vk_user")
    if not raw:
        return {}
    try:
        u = json.loads(raw)
        if not isinstance(u, dict):
            return {}
        return {
            "first_name": u.get("first_name") if isinstance(u.get("first_name"), str) else None,
            "last_name": u.get("last_name") if isinstance(u.get("last_name"), str) else None,
        }
    except json.JSONDecodeError:
        return {}


def verify_vk_miniapp_launch_principal(raw_launch_query: str, protected_key: str) -> MiniAppPrincipal:
    """
    Verify launch query string and return principal with platform MAX and ``user_id`` = vk_user_id.

    Raises:
        InitDataAuthError: bad signature, missing fields, or invalid vk_user_id (maps to HTTP 401 in deps).
    """
    key = (protected_key or "").strip()
    if not key:
        raise InitDataAuthError("VK Mini App protected key not configured")
    q = _parse_launch_query_to_map(raw_launch_query)
    if not vk_launch_params_signature_valid(q, key):
        raise InitDataAuthError("Invalid or missing VK launch signature")
    uid_raw = q.get("vk_user_id")
    if uid_raw is None or str(uid_raw).strip() == "":
        raise InitDataAuthError("vk_user_id missing in launch params")
    try:
        uid = int(uid_raw)
    except (TypeError, ValueError) as e:
        raise InitDataAuthError("Invalid vk_user_id") from e
    if uid <= 0:
        raise InitDataAuthError("Invalid vk_user_id")
    return MiniAppPrincipal(platform=MiniAppPlatform.MAX, user_id=uid)
