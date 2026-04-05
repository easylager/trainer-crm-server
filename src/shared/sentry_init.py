"""Sentry SDK bootstrap: FastAPI (ASGI) or asyncio workers (aiogram bots, notification service)."""
from __future__ import annotations

import logging
from typing import Any, Literal

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from src.shared.config import Settings

logger = logging.getLogger(__name__)

SentryComponent = Literal[
    "api",
    "bot-client",
    "bot-trainer",
    "bot-admin",
    "notification-service",
]


def init_sentry(settings: Settings, component: SentryComponent) -> None:
    """No-op when ``sentry_dsn`` is empty. Tags each event with ``component`` for filtering in Sentry."""
    dsn = settings.sentry_dsn
    if not dsn:
        return

    def _before_send(event: dict, hint: object) -> dict | None:
        tags = event.setdefault("tags", {})
        tags["component"] = component
        return event

    integrations: list[Any]
    if component == "api":
        integrations = [StarletteIntegration(), FastApiIntegration()]
    else:
        integrations = [AsyncioIntegration()]

    kwargs: dict = {
        "dsn": dsn,
        "integrations": integrations,
        "traces_sample_rate": settings.sentry_traces_sample_rate,
        "send_default_pii": False,
        "before_send": _before_send,
    }
    if settings.sentry_environment:
        kwargs["environment"] = settings.sentry_environment
    if settings.sentry_release:
        kwargs["release"] = settings.sentry_release
    # Profiling requires tracing; avoid invalid SDK combo when traces_sample_rate is 0.
    if settings.sentry_traces_sample_rate > 0 and settings.sentry_profiles_sample_rate > 0:
        kwargs["profiles_sample_rate"] = settings.sentry_profiles_sample_rate

    sentry_sdk.init(**kwargs)
    logger.info("Sentry initialized (component=%s)", component)
