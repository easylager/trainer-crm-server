"""
Shareable links for trainers to onboard clients from DMs into the client bot + catalog.

Deep link payload matches client_handlers:
  /start client_{city_id}_{service_id_or_0}_{trainer_id}  — trainer onboarding
  /start share_ref_{trainer_id}                            — client→friend recommendation share
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrainerInviteLinks:
    """Production-oriented URLs: https t.me + optional HTTPS catalog page."""

    client_bot_deep_link: str
    catalog_page_url: str | None


@dataclass(frozen=True)
class TrainerShareLink:
    """Deep link for client→friend trainer recommendation (trust-based share, not referral)."""

    bot_deep_link: str


def normalize_client_bot_username(username: str | None) -> str:
    return (username or "").strip().lstrip("@")


# --- Share ref: client recommends a trainer to a friend ---

SHARE_REF_PREFIX = "share_ref_"
WELCOME_REF_PREFIX = "welcome_ref_"


def build_welcome_ref_payload(trainer_id: int) -> str:
    """Permanent hub invite payload: welcome_ref_{trainer_id}."""
    return f"{WELCOME_REF_PREFIX}{int(trainer_id)}"


def build_trainer_universal_invite_link(
    *,
    client_bot_username: str | None,
    trainer_id: int,
) -> tuple[str | None, str | None]:
    """
    Same link as hub paperclip (GET /trainer/hub/universal-invite-link).
    Returns (https t.me URL, error) where error is missing_username or invalid_trainer_id.
    """
    u = normalize_client_bot_username(client_bot_username)
    if not u:
        return None, "missing_username"
    if int(trainer_id) <= 0:
        return None, "invalid_trainer_id"
    payload = build_welcome_ref_payload(int(trainer_id))
    return f"https://t.me/{u}?start={payload}", None


def build_share_ref_payload(trainer_id: int) -> str:
    """Produces the /start payload for a shared trainer link: share_ref_{trainer_id}."""
    return f"{SHARE_REF_PREFIX}{int(trainer_id)}"


def build_trainer_share_link(
    *,
    webapp_base_url: str,
    client_bot_username: str | None,
    trainer_id: int,
) -> tuple[TrainerShareLink | None, str | None]:
    """
    Build a deep link for sharing a trainer profile (client→friend recommendation).
    Returns (link, error) where error is one of: missing_username, invalid_trainer_id.
    """
    u = normalize_client_bot_username(client_bot_username)
    if not u:
        return None, "missing_username"
    if int(trainer_id) <= 0:
        return None, "invalid_trainer_id"
    payload = build_share_ref_payload(int(trainer_id))
    return TrainerShareLink(bot_deep_link=f"https://t.me/{u}?start={payload}"), None


def build_client_start_payload(
    city_id: int, service_id: int | None, trainer_id: int
) -> str:
    sid = int(service_id) if service_id is not None and int(service_id) > 0 else 0
    return f"client_{city_id}_{sid}_{trainer_id}"


def build_trainer_invite_links(
    *,
    webapp_base_url: str,
    client_bot_username: str | None,
    city_id: int | None,
    service_id: int | None,
    trainer_id: int,
) -> tuple[TrainerInviteLinks | None, str | None]:
    """
    Returns (links, error) where error is None or:
    - missing_username — CLIENT_BOT_USERNAME not set
    - missing_city_or_service — no valid city_id or trainer_id for deep link (service optional → 0 in payload)
    """
    u = normalize_client_bot_username(client_bot_username)
    if not u:
        return None, "missing_username"
    if city_id is None or int(city_id) <= 0 or int(trainer_id) <= 0:
        return None, "missing_city_or_service"
    cid, tid = int(city_id), int(trainer_id)
    sid = int(service_id) if service_id is not None and int(service_id) > 0 else None
    payload = build_client_start_payload(cid, sid, tid)
    deep = f"https://t.me/{u}?start={payload}"
    base = (webapp_base_url or "").rstrip("/")
    catalog = f"{base}/webapp/catalog" if base.lower().startswith("https://") else None
    return TrainerInviteLinks(client_bot_deep_link=deep, catalog_page_url=catalog), None
