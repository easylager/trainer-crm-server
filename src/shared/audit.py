"""
Structured audit log: one JSON line per event (ts, event, actor_type, actor_id, payload).
Use for incident review and analytics; no PII in payload by default.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any

# Dedicated logger; apps can set level via logging.getLogger("audit").setLevel(...)
logger = logging.getLogger("audit")

# Canonical actor types for filtering in log aggregators
ACTOR_API = "api"
ACTOR_CLIENT_BOT = "client_bot"
ACTOR_TRAINER_BOT = "trainer_bot"
ACTOR_ADMIN_BOT = "admin_bot"


def audit_log(
    event: str,
    actor_type: str,
    actor_id: str | int,
    payload: dict[str, Any] | None = None,
) -> None:
    """
    Emit one audit record as JSON to the audit logger (INFO).
    payload: only JSON-serializable values (ids, statuses); no PII.
    """
    payload = payload or {}
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "payload": payload,
    }
    try:
        line = json.dumps(record, ensure_ascii=False)
    except (TypeError, ValueError):
        # Fallback: drop non-serializable values
        safe_payload = {k: v for k, v in payload.items() if _json_serializable(v)}
        record["payload"] = safe_payload
        line = json.dumps(record, ensure_ascii=False)
    logger.info(line)
    try:
        from src.application.platform_audit_use_cases import schedule_audit_persist

        schedule_audit_persist(record)
    except Exception:
        pass  # audit stdout must never break business flow


def _json_serializable(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_json_serializable(x) for x in value)
    if isinstance(value, dict):
        return all(_json_serializable(k) and _json_serializable(v) for k, v in value.items())
    return False
