"""Stroke-иконки публичного каталога. Линия 1.8, скруглённые концы. Emoji нет."""

from __future__ import annotations

_PATHS = {
    "skate": "M7 16c2-6 4-8 8-8 2 0 3 1 4 2M8 18h10M6 18c0 1.2.8 2 2 2h1",
    "stick": "M6 17l8-12M14 5l4 2-6 9",
    "sharpen": "M5 16l9-9 3 3-9 9H5v-3zM14 7l3 3",
    "shop": "M6 9h12l-1 10H7L6 9zM9 9V7a3 3 0 0 1 6 0v2",
    "phone": "M8 5h3l1 3-2 1a10 10 0 0 0 5 5l1-2 3 1v3a2 2 0 0 1-2 2A13 13 0 0 1 6 7a2 2 0 0 1 2-2z",
    "route": "M12 21s6-5.2 6-10a6 6 0 1 0-12 0c0 4.8 6 10 6 10zM12 11.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z",
    "invite": "M16 11v6M13 14h6M8 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM4 19c.6-2 2.2-3 4-3s3.4 1 4 3",
    "bell": "M6 16h12l-1.2-2.2A6 6 0 0 1 16 9V8a4 4 0 0 0-8 0v1a6 6 0 0 1-.8 4.8L6 16zM10 18a2 2 0 0 0 4 0",
    "parking": "M7 19V5h6a4 4 0 0 1 0 8H7",
    "person": "M12 12a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 19c.8-2.4 2.8-3.5 6-3.5s5.2 1.1 6 3.5",
}


def icon_svg(name: str) -> str:
    """Пустая строка, если имени нет в наборе — не подставляем emoji."""
    path = _PATHS.get(name)
    if not path:
        return ""
    return (
        f'<svg class="g-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        f'<path d="{path}"/></svg>'
    )


def rink_motif_svg() -> str:
    """Разметка катка: скруглённый прямоугольник, линия, круг, точки вбрасывания."""
    return (
        '<svg class="g-motif" viewBox="0 0 360 220" aria-hidden="true" focusable="false">'
        '<rect x="36" y="28" width="288" height="164" rx="78"/>'
        '<line class="g-motif__mid" x1="180" y1="28" x2="180" y2="192"/>'
        '<circle cx="180" cy="110" r="26"/>'
        '<circle class="g-motif__dot" cx="180" cy="52" r="3"/>'
        '<circle class="g-motif__dot" cx="180" cy="168" r="3"/>'
        '<circle class="g-motif__dot" cx="108" cy="110" r="3"/>'
        '<circle class="g-motif__dot" cx="252" cy="110" r="3"/>'
        "</svg>"
    )
