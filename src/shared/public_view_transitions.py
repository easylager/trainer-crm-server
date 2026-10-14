"""Cross-document view-transition names for the public catalog (/, /c/, /p/)."""

from __future__ import annotations

import re

WHEN_STRIP_VT_NAME = "glide-when-strip"

_SESSION_VT_RE = re.compile(r"[^0-9]")


def session_time_vt_name(arena_id: int, clock: str) -> str:
    """Stable name for the same arena + local start time on /c/ and /p/."""
    digits = _SESSION_VT_RE.sub("", str(clock or ""))
    if not digits:
        digits = "0"
    return f"glide-s-{int(arena_id)}-t{digits}"


def session_time_vt_style(arena_id: int, clock: str) -> str:
    """Inline style for a unique ``view-transition-name`` on the time element."""
    name = session_time_vt_name(arena_id, clock)
    return f' style="view-transition-name: {name}"'
