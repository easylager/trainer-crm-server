"""Public landing: issue trainer welcome link from site CTA."""
from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_link_token_use_cases import issue_landing_trainer_link_token
from src.application.trainer_start_payload import START_JOIN_PAYLOAD
from src.shared.config import Settings

_REFERRAL_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,32}$")


def sanitize_referral_code(raw: str | None) -> str | None:
    """Keep alphanumeric referral codes only; drop invalid input."""
    if not raw:
        return None
    code = str(raw).strip()
    if not code or not _REFERRAL_CODE_RE.fullmatch(code):
        return None
    return code


def build_trainer_bot_join_deep_link(*, settings: Settings | None = None) -> str | None:
    """Permanent public entry: t.me/<bot>?start=join (shareable in Telegram)."""
    s = settings or Settings()
    uname = (s.trainer_bot_username or "").strip().lstrip("@")
    if not uname:
        return None
    return f"https://t.me/{uname}?start={START_JOIN_PAYLOAD}"


def build_trainer_bot_deep_link(
    token: str,
    *,
    referral_code: str | None = None,
    settings: Settings | None = None,
) -> str | None:
    """Assemble t.me deep link with optional referral suffix on link_ payload."""
    s = settings or Settings()
    uname = (s.trainer_bot_username or "").strip().lstrip("@")
    if not uname:
        return None
    payload = f"link_{token}"
    ref = sanitize_referral_code(referral_code)
    if ref:
        payload = f"{payload}_ref_{ref}"
    return f"https://t.me/{uname}?start={payload}"


async def issue_trainer_start_from_landing(
    session: AsyncSession,
    *,
    referral_code: str | None = None,
    settings: Settings | None = None,
) -> dict:
    """
    Issue a one-time bot token (no trainer row yet) and return redirect URL for Glide bot.

    Raises ValueError with a short code when bot username is not configured.
    """
    s = settings or Settings()
    uname = (s.trainer_bot_username or "").strip().lstrip("@")
    if not uname:
        raise ValueError("trainer_bot_username_missing")

    issued = await issue_landing_trainer_link_token(session)
    token = str(issued["token"])
    redirect_url = build_trainer_bot_deep_link(token, referral_code=referral_code, settings=s)
    if not redirect_url:
        raise ValueError("trainer_bot_username_missing")
    return {
        "trainer_id": issued.get("trainer_id"),
        "redirect_url": redirect_url,
        "start_payload": issued["start_payload"],
        "expires_at": issued["expires_at"].isoformat(),
        "referral_code": sanitize_referral_code(referral_code),
    }
