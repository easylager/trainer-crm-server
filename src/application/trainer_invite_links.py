"""
Shareable links for trainers to onboard clients from DMs into the client bot + catalog.

Deep link payload matches client_handlers: /start client_{city_id}_{service_id}_{trainer_id}.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrainerInviteLinks:
    """Production-oriented URLs: https t.me + optional HTTPS catalog page."""

    client_bot_deep_link: str
    catalog_page_url: str | None


def normalize_client_bot_username(username: str | None) -> str:
    return (username or "").strip().lstrip("@")


def build_client_start_payload(city_id: int, service_id: int, trainer_id: int) -> str:
    return f"client_{city_id}_{service_id}_{trainer_id}"


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
    - missing_city_or_service — trainer profile has no city or no service for deep link
    """
    u = normalize_client_bot_username(client_bot_username)
    if not u:
        return None, "missing_username"
    if (
        city_id is None
        or service_id is None
        or int(city_id) <= 0
        or int(service_id) <= 0
        or int(trainer_id) <= 0
    ):
        return None, "missing_city_or_service"
    cid, sid, tid = int(city_id), int(service_id), int(trainer_id)
    payload = build_client_start_payload(cid, sid, tid)
    deep = f"https://t.me/{u}?start={payload}"
    base = (webapp_base_url or "").rstrip("/")
    catalog = f"{base}/webapp/catalog" if base.lower().startswith("https://") else None
    return TrainerInviteLinks(client_bot_deep_link=deep, catalog_page_url=catalog), None
