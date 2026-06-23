"""Gate dev-only REST surfaces that lack Mini App initData auth."""
from __future__ import annotations

from fastapi import HTTPException

from src.shared.config import Settings


def require_legacy_trainers_api() -> None:
    """404 when legacy /api/trainers/* is disabled (production default)."""
    if not Settings().legacy_trainers_api_enabled:
        raise HTTPException(status_code=404, detail="Not found")
