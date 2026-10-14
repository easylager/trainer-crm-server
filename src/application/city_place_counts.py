"""Счётчики мест города по типам — одна правда для хаба, og, шера и «Все места · N»."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.application.ice_city_day import plural_ru
from src.shared.venue_types import VENUE_TYPE_ICE, VENUE_TYPE_OUTDOOR, VENUE_TYPE_SHOP

RINK_VENUE_TYPES = frozenset({VENUE_TYPE_ICE, VENUE_TYPE_OUTDOOR})


@dataclass(frozen=True, slots=True)
class CityPlaceCounts:
    total: int
    rinks: int
    shops: int
    other: int

    def as_dict(self) -> dict[str, int]:
        return {"total": self.total, "rinks": self.rinks, "shops": self.shops, "other": self.other}


def _venue_type(place: Mapping[str, Any]) -> str:
    return str(place.get("venue_type") or VENUE_TYPE_ICE)


def city_place_counts_from_places(places: Sequence[Mapping[str, Any]]) -> CityPlaceCounts:
    rinks = shops = other = 0
    for place in places:
        vt = _venue_type(place)
        if vt in RINK_VENUE_TYPES:
            rinks += 1
        elif vt == VENUE_TYPE_SHOP:
            shops += 1
        else:
            other += 1
    return CityPlaceCounts(total=len(places), rinks=rinks, shops=shops, other=other)


def city_place_counts_from_facets(facets: Sequence[Mapping[str, Any]]) -> CityPlaceCounts:
    by_key: dict[str, int] = {}
    for facet in facets:
        key = str(facet.get("key") or "")
        if key:
            by_key[key] = int(facet.get("count") or 0)
    rinks = sum(by_key.get(k, 0) for k in RINK_VENUE_TYPES)
    shops = int(by_key.get(VENUE_TYPE_SHOP, 0))
    other = sum(n for key, n in by_key.items() if key not in RINK_VENUE_TYPES and key != VENUE_TYPE_SHOP)
    total = rinks + shops + other
    return CityPlaceCounts(total=total, rinks=rinks, shops=shops, other=other)


def city_place_count_noun(counts: CityPlaceCounts) -> tuple[str, str, str]:
    if counts.total <= 0:
        return ("место", "места", "мест")
    if counts.rinks == counts.total:
        return ("каток", "катка", "катков")
    return ("место", "места", "мест")


def city_place_inventory_line(counts: CityPlaceCounts, session_count: int) -> str:
    """Строка «N катков/мест · M сеансов» для og:description и текста шера."""
    n = counts.total
    bits = [f"{n} {plural_ru(n, *city_place_count_noun(counts))}"]
    sessions = int(session_count or 0)
    if sessions:
        bits.append(f"{sessions} {plural_ru(sessions, 'сеанс', 'сеанса', 'сеансов')}")
    return " · ".join(bits)


def city_hub_place_groups(
    places: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, list[Mapping[str, Any]]], ...]:
    """Катки / магазины / прочее — для блока «Все места города» без смены вёрстки."""
    rinks = [p for p in places if _venue_type(p) in RINK_VENUE_TYPES]
    shops = [p for p in places if _venue_type(p) == VENUE_TYPE_SHOP]
    other = [p for p in places if _venue_type(p) not in RINK_VENUE_TYPES and _venue_type(p) != VENUE_TYPE_SHOP]
    groups: list[tuple[str, list[Mapping[str, Any]]]] = []
    if rinks:
        groups.append(("Катки", rinks))
    if shops:
        groups.append(("Магазины и сервисы", shops))
    if other:
        groups.append(("Прочее", other))
    return tuple(groups)
