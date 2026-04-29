"""
Pure helpers for client ↔ trainer relationship graph (edges) and hub primary logic.

No FastAPI imports — safe to use from multiple route modules without cycles.
"""
from __future__ import annotations

from typing import Any


def compute_primary_edge_meta(
    edges: list[dict],
    session_trainer_id: int | None = None,
) -> tuple[dict | None, str | None]:
    """
    Returns (edge, source) where source is ``booking`` | ``saved`` | ``session`` | None.

    Priority matches ``compute_primary_edge`` (booking → saved → session row).
    """
    if not edges:
        return None, None

    booked = [e for e in edges if e.get("last_booking_at")]
    if booked:
        return max(booked, key=lambda e: e["last_booking_at"]), "booking"

    saved = [e for e in edges if e.get("is_saved")]
    if saved:
        with_ts = [e for e in saved if e.get("saved_at")]
        if with_ts:
            return max(with_ts, key=lambda e: e["saved_at"]), "saved"
        return saved[0], "saved"

    if session_trainer_id is not None:
        for e in edges:
            if int(e.get("trainer_id", 0)) == session_trainer_id:
                return e, "session"

    return None, None


def compute_primary_edge(
    edges: list[dict],
    session_trainer_id: int | None = None,
) -> dict | None:
    """Derive the most intent-relevant trainer without any explicit flag."""
    edge, _ = compute_primary_edge_meta(edges, session_trainer_id)
    return edge


def resolve_primary_catalog_service_id(
    primary_edge: dict | None,
    primary_source: str | None,
    session_selected_service_id: int | None,
) -> int | None:
    """
    Pick catalog ``service_id`` using the same tier that selected ``primary_edge``.

    - booking → service from last booking on that edge
    - saved → service from catalog session at last save (like)
    - session → current ``client_sessions.selected_service_id`` while viewing that trainer
    """
    if not primary_edge or not primary_source:
        sid = session_selected_service_id
        if sid is None:
            return None
        try:
            return int(sid)
        except (TypeError, ValueError):
            return None
    if primary_source == "booking":
        raw = primary_edge.get("last_booking_service_id")
    elif primary_source == "saved":
        raw = primary_edge.get("saved_catalog_service_id")
    else:
        raw = session_selected_service_id
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def serialize_trainer_edge_row(edge: dict) -> dict:
    """Convert edge row to JSON-safe dict; datetime → ISO string."""
    out = dict(edge)
    for key in (
        "saved_at", "notify_when_slots_at",
        "last_booking_at", "last_completed_at", "last_interaction_at", "created_at",
    ):
        v = out.get(key)
        if hasattr(v, "isoformat"):
            out[key] = v.isoformat()
        elif v is not None:
            out[key] = str(v)
    return out


def edge_json_with_trainer_hints(
    edge: dict,
    hints: dict[int, dict[str, Any]],
    next_bookings: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Edge + display hints + next upcoming booking when available."""
    base = serialize_trainer_edge_row(edge)
    tid = int(edge["trainer_id"])
    h = hints.get(tid) or {}
    base["trainer_display_name"] = h.get("trainer_display_name", "Тренер")
    base["trainer_list_photo_key"] = h.get("trainer_list_photo_key")
    base["services"] = h.get("services", [])
    base["primary_arena_name"] = h.get("primary_arena_name")
    base["min_price_cents"] = h.get("min_price_cents")
    if next_bookings is not None:
        base["next_booking"] = next_bookings.get(tid)
    return base


def next_booking_per_trainer(days: list[dict]) -> dict[int, dict[str, Any]]:
    """First upcoming non-cancelled booking per trainer; days list is ascending by date already."""
    out: dict[int, dict[str, Any]] = {}
    for d in days or []:
        for b in d.get("bookings", []) or []:
            tid = b.get("trainer_id")
            if tid is None or tid in out:
                continue
            status = (b.get("status") or "").lower()
            if status in ("cancelled", "declined", "no_show"):
                continue
            out[int(tid)] = {
                "slot_date": b.get("slot_date"),
                "start_time": b.get("start_time"),
                "service_name": b.get("service_name"),
                "arena_name": b.get("arena_name"),
            }
    return out
