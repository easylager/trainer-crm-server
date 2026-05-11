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


def _key_slots(trainer_id: int, min_hours: int, service_id: int | None) -> tuple:
    # v2 cache: normalized arena_id on each slot row for client payloads
    return ("slots", "v2", trainer_id, min_hours, service_id)


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


def get_slots_cached(trainer_id: int, min_hours: int, service_id: int | None = None) -> list | None:
    k = _key_slots(trainer_id, min_hours, service_id)
    entry = _CACHE.get(k)
    if not entry:
        return None
    val, expiry = entry
    if time.monotonic() > expiry:
        del _CACHE[k]
        return None
    return val


def set_slots_cached(trainer_id: int, min_hours: int, slots: list, service_id: int | None = None) -> None:
    k = _key_slots(trainer_id, min_hours, service_id)
    _CACHE[k] = (slots, time.monotonic() + _SLOTS_TTL_SEC)


def invalidate_slots_for_trainer(trainer_id: int) -> None:
    """Drop cached /client/slots lists when availability changes (slots CRUD or booking create/cancel/decline)."""
    to_del: list[tuple] = []
    for k in _CACHE:
        if not isinstance(k, tuple) or len(k) < 2 or k[0] != "slots":
            continue
        if k[1] == "v2":
            if len(k) >= 3 and k[2] == trainer_id:
                to_del.append(k)
        elif k[1] == trainer_id:
            to_del.append(k)
    for k in to_del:
        _CACHE.pop(k, None)
