"""
Shared outage / maintenance contract for API, bots, and Mini Apps.

Users should never see empty Mini App lists or a silent bot when Postgres is down.
"""
from __future__ import annotations

from typing import Any, Mapping

SERVICE_UNAVAILABLE_CODE = "service_unavailable"

# Shown in Mini Apps, bots, and API JSON. Neutral — covers planned work and hardware failure.
SERVICE_UNAVAILABLE_MESSAGE_RU = (
    "Сейчас ведутся технические работы. Попробуйте через несколько минут — "
    "записи и расписание на месте."
)

_DB_EXC_NAMES = frozenset(
    {
        "OperationalError",
        "InterfaceError",
        "PostgresConnectionError",
        "CannotConnectNowError",
        "ConnectionDoesNotExistError",
        "TooManyConnectionsError",
        "CannotConnectNowError",
    }
)

_DB_MESSAGE_MARKERS = (
    "connection refused",
    "could not connect",
    "connection reset",
    "server closed the connection",
    "the database system is shutting down",
    "the database system is starting up",
    "too many connections",
    "connect call failed",
    "connection does not exist",
    "error connecting to unix socket",
    "timeout expired: connection",
    "could not translate host name",
    "name or service not known",
    "network is unreachable",
    "no route to host",
)


def service_unavailable_payload(*, db: str = "error") -> dict[str, str]:
    """JSON body Mini Apps recognize (code + detail)."""
    msg = SERVICE_UNAVAILABLE_MESSAGE_RU
    return {
        "status": "degraded",
        "db": db,
        "code": SERVICE_UNAVAILABLE_CODE,
        "message": msg,
        "detail": msg,
    }


def is_db_unavailable(exc: BaseException | None) -> bool:
    """True when the failure is 'cannot talk to Postgres', not a business IntegrityError."""
    if exc is None:
        return False
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        ident = id(current)
        if ident in seen:
            continue
        seen.add(ident)
        name = type(current).__name__
        module = type(current).__module__ or ""
        if name in _DB_EXC_NAMES:
            return True
        if name == "TimeoutError" and "sqlalchemy" in module:
            return True
        if isinstance(current, ConnectionRefusedError):
            return True
        if isinstance(current, OSError):
            errno = getattr(current, "errno", None)
            # ECONNREFUSED: Linux 111, macOS 61; ENETUNREACH 101; EHOSTUNREACH 113/65
            if errno in {61, 65, 101, 111, 113}:
                return True
        lowered = str(current).lower()
        if any(marker in lowered for marker in _DB_MESSAGE_MARKERS):
            return True
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None and current.__context__ is not current.__cause__:
            stack.append(current.__context__)
    return False


def payload_looks_like_outage(body: Mapping[str, Any] | None) -> bool:
    if not body:
        return False
    code = str(body.get("code") or "").strip().lower()
    if code == SERVICE_UNAVAILABLE_CODE:
        return True
    detail = body.get("detail")
    if isinstance(detail, str) and "database unavailable" in detail.lower():
        return True
    return False
