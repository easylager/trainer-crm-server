"""
Simple in-memory TTL cache for catalog responses. Single process only.
Thread-safe for concurrent reads; writes are assumed from one event loop.
"""
import time
from typing import Any

_CACHE: dict[tuple, tuple[Any, float]] = {}
_TRAINERS_TTL_SEC = 90
_SLOTS_TTL_SEC = 60


def _key_trainers(limit: int, offset: int, city_id: int | None, service_id: int | None, arena_id: int | None, order_by: str) -> tuple:
    return ("trainers", limit, offset, city_id, service_id, arena_id, order_by)


def _key_slots(trainer_id: int, min_hours: int) -> tuple:
    return ("slots", trainer_id, min_hours)


def get_trainers_cached(
    limit: int,
    offset: int,
    city_id: int | None,
    service_id: int | None,
    arena_id: int | None,
    order_by: str,
) -> tuple[list, int] | None:
    k = _key_trainers(limit, offset, city_id, service_id, arena_id, order_by)
    entry = _CACHE.get(k)
    if not entry:
        return None
    val, expiry = entry
    if time.monotonic() > expiry:
        del _CACHE[k]
        return None
    return val


def set_trainers_cached(
    limit: int,
    offset: int,
    city_id: int | None,
    service_id: int | None,
    arena_id: int | None,
    order_by: str,
    items: list,
    total: int,
) -> None:
    k = _key_trainers(limit, offset, city_id, service_id, arena_id, order_by)
    _CACHE[k] = ((items, total), time.monotonic() + _TRAINERS_TTL_SEC)


def get_slots_cached(trainer_id: int, min_hours: int) -> list | None:
    k = _key_slots(trainer_id, min_hours)
    entry = _CACHE.get(k)
    if not entry:
        return None
    val, expiry = entry
    if time.monotonic() > expiry:
        del _CACHE[k]
        return None
    return val


def set_slots_cached(trainer_id: int, min_hours: int, slots: list) -> None:
    k = _key_slots(trainer_id, min_hours)
    _CACHE[k] = (slots, time.monotonic() + _SLOTS_TTL_SEC)


def invalidate_slots_for_trainer(trainer_id: int) -> None:
    """Drop cached /client/slots lists when availability changes (slots CRUD or booking create/cancel/decline)."""
    to_del = [k for k in _CACHE if isinstance(k, tuple) and k[0] == "slots" and k[1] == trainer_id]
    for k in to_del:
        _CACHE.pop(k, None)
