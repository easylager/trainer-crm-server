"""Build map URLs for Belarus (Yandex.by)."""
from urllib.parse import quote_plus


def build_yandex_by_map_url(arena: dict) -> str | None:
    """
    Yandex.by map URL for an arena. Prefer coordinates (exact pin), else search by address.
    pt parameter: longitude,latitude (Yandex order).
    """
    lat = arena.get("latitude")
    lon = arena.get("longitude")
    if lat is not None and lon is not None:
        return f"https://yandex.by/maps/?pt={lon},{lat}&z=16"
    address = (arena.get("address") or "").strip()
    if address:
        return f"https://yandex.by/maps/?text={quote_plus(address)}"
    return None


def build_yandex_by_map_url_all_arenas(arenas: list[dict]) -> str | None:
    """
    One Yandex.by map URL with all arenas that have coordinates (multiple markers).
    User can view all locations first, then return to bot and tap «Выбрать».
    """
    points = []
    for a in arenas or []:
        lat, lon = a.get("latitude"), a.get("longitude")
        if lat is not None and lon is not None:
            points.append(f"{lon},{lat}")
    if not points:
        return None
    # Yandex: multiple pt=lon,lat (comma-separated in one pt or repeated pt)
    pt_param = "&".join(f"pt={p}" for p in points[:20])  # limit 20 to avoid huge URL
    return f"https://yandex.by/maps/?{pt_param}&z=12"
