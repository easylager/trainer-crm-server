"""Фича включена только для city_id из ICE_COMPANY_CITY_IDS. Пусто — выключена везде."""

from __future__ import annotations

from src.shared.config import Settings


def enabled_city_ids(settings: Settings | None = None) -> set[int]:
    raw = (settings or Settings()).ice_company_city_ids or ""
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit() and int(part) > 0:
            out.add(int(part))
    return out


def city_enabled(city_id: int | None, settings: Settings | None = None) -> bool:
    if city_id is None or int(city_id) <= 0:
        return False
    return int(city_id) in enabled_city_ids(settings)
