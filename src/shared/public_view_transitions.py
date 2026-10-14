"""Cross-document view-transition names for the public catalog (/, /c/, /p/)."""

from __future__ import annotations

WHEN_STRIP_VT_NAME = "glide-when-strip"


def session_time_vt_name(session_id: int) -> str:
    return f"glide-s-{int(session_id)}"


def session_time_vt_style(session_id: int) -> str:
    return f' style="view-transition-name: {session_time_vt_name(session_id)}"'
