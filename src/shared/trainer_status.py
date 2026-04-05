"""Normalize trainers.status from PostgreSQL enum / DB drivers to canonical lowercase strings."""
from __future__ import annotations

from enum import Enum
from typing import Any


def normalize_trainer_status_value(raw: Any) -> str:
    """
    Raw SQL may return str, or a driver-specific Enum-like object where str(x) != 'active'.
    Ensures comparisons with TRAINER_STATUS_* constants work reliably.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip().lower()
    if isinstance(raw, Enum):
        v = raw.value
        if isinstance(v, str):
            return v.strip().lower()
        return str(v).strip().lower() if v is not None else ""
    v = getattr(raw, "value", None)
    if isinstance(v, str):
        return v.strip().lower()
    return str(raw).strip().lower()
