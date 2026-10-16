"""Cross-document view-transition names for the public catalog (/, /c/, /p/)."""

from __future__ import annotations

import re

WHEN_STRIP_VT_NAME = "glide-when-strip"
_PLACE_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def session_time_vt_name(session_id: int) -> str:
    return f"glide-s-{int(session_id)}"


def session_time_vt_style(session_id: int) -> str:
    return f' style="view-transition-name: {session_time_vt_name(session_id)}"'


def place_vt_name(slug: str) -> str:
    """Общее имя карточки катка и героя страницы места: карточка вырастает в героя."""
    safe = _PLACE_SLUG_RE.sub("-", str(slug or "").strip().lower()).strip("-")
    return f"glide-place-{safe}" if safe else ""


def place_vt_style(slug: str) -> str:
    """Имя уже в разметке — только у героя страницы катка, он на странице один."""
    name = place_vt_name(slug)
    return f' style="view-transition-name: {name}"' if name else ""


def place_vt_attr(slug: str) -> str:
    """Список не называет все карточки сразу: имя ставит скрипт в момент открытия.

    Иначе при смене дня и при «Назад» браузер отдельно анимирует каждую карточку.
    """
    name = place_vt_name(slug)
    return f' data-place-vt="{name}"' if name else ""
