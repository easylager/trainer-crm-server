"""
Pure helpers for client ↔ trainer relationship graph (edges) and hub primary logic.

No FastAPI imports — safe to use from multiple route modules without cycles.

Primary trainer resolution (strict product contract):
  1. Latest booking by slot start time (past or future), from DB bookings — not edge timestamps.
  2. Else latest «saved» (catalog heart), by saved_at (fallback edge created_at).
  3. Else client_sessions.selected_trainer_id (last catalog browse context).
  4. Else no primary.

Synthetic edge rows fill gaps when booking/session trainer_id has no client_trainer_edges row yet.
"""
from __future__ import annotations

from typing import Any


def synthetic_client_trainer_edge_placeholder(
    trainer_id: int,
    *,
    last_booking_service_id: int | None = None,
    saved_catalog_service_id: int | None = None,
) -> dict[str, Any]:
    """Minimal edge-shaped dict for serialization when no CRM edge row exists."""
    tid = int(trainer_id)
    return {
        "id": None,
        "telegram_id": None,
        "trainer_id": tid,
        "is_saved": False,
        "is_primary": False,
        "notify_when_slots": False,
        "completed_count": 0,
        "saved_at": None,
        "notify_when_slots_at": None,
        "last_booking_at": None,
        "last_completed_at": None,
        "last_interaction_at": None,
        "last_booking_service_id": last_booking_service_id,
        "saved_catalog_service_id": saved_catalog_service_id,
        "context_type": None,
        "context_id": None,
        "created_at": None,
    }


def edge_row_for_primary_trainer(
    edges: list[dict],
    trainer_id: int,
    *,
    last_booking_service_id: int | None = None,
    saved_catalog_service_id: int | None = None,
) -> dict[str, Any]:
    """Prefer real CRM edge; otherwise synthetic placeholder carrying optional service hints."""
    tid = int(trainer_id)
    for e in edges:
        if int(e.get("trainer_id", 0)) == tid:
            return dict(e)
    return synthetic_client_trainer_edge_placeholder(
        tid,
        last_booking_service_id=last_booking_service_id,
        saved_catalog_service_id=saved_catalog_service_id,
    )


def _saved_recency_sort_key(edge: dict) -> tuple[float, float, int]:
    """Higher tuple compares greater — newest bookmark wins."""

    def ts(v: object) -> float:
        if v is None:
            return -1.0
        if hasattr(v, "timestamp"):
            try:
                return float(v.timestamp())  # type: ignore[arg-type]
            except Exception:
                return -1.0
        return -1.0

    sa = edge.get("saved_at")
    ca = edge.get("created_at")
    tid = int(edge.get("trainer_id") or 0)
    return (ts(sa), ts(ca), tid)


def resolve_primary_trainer_strict(
    edges: list[dict],
    *,
    booking_primary_trainer_id: int | None,
    booking_primary_service_id: int | None,
    session_trainer_id: int | None,
) -> tuple[dict | None, str | None]:
    """
    Strict tier order for «основной тренер» across mini-app + dependent APIs.

    booking_primary_* comes from SQL over bookings/slots (caller-supplied).
    """
    if booking_primary_trainer_id is not None:
        tid = int(booking_primary_trainer_id)
        sid = booking_primary_service_id
        svc: int | None
        try:
            svc = int(sid) if sid is not None else None
        except (TypeError, ValueError):
            svc = None
        row = edge_row_for_primary_trainer(
            edges,
            tid,
            last_booking_service_id=svc,
        )
        if svc is not None:
            row = dict(row)
            row["last_booking_service_id"] = svc
        return row, "booking"

    saved_edges = [e for e in edges if e.get("is_saved")]
    if saved_edges:
        best = max(saved_edges, key=_saved_recency_sort_key)
        tid = int(best["trainer_id"])
        return edge_row_for_primary_trainer(edges, tid), "saved"

    if session_trainer_id is not None:
        tid = int(session_trainer_id)
        return edge_row_for_primary_trainer(edges, tid), "session"

    return None, None


def compute_primary_edge_meta(
    edges: list[dict],
    session_trainer_id: int | None = None,
    *,
    booking_primary_trainer_id: int | None = None,
    booking_primary_service_id: int | None = None,
) -> tuple[dict | None, str | None]:
    """
    Returns (edge, source) where source is ``booking`` | ``saved`` | ``session`` | None.

    Booking tier uses authoritative rows from ``client_latest_booking_primary_candidate`` —
    never ``last_booking_at`` on edges (avoids drift vs CRM bookings).
    """
    return resolve_primary_trainer_strict(
        edges,
        booking_primary_trainer_id=booking_primary_trainer_id,
        booking_primary_service_id=booking_primary_service_id,
        session_trainer_id=session_trainer_id,
    )


def compute_primary_edge(
    edges: list[dict],
    session_trainer_id: int | None = None,
    *,
    booking_primary_trainer_id: int | None = None,
    booking_primary_service_id: int | None = None,
) -> dict | None:
    """Derive primary trainer edge dict under strict tier rules."""
    edge, _ = compute_primary_edge_meta(
        edges,
        session_trainer_id,
        booking_primary_trainer_id=booking_primary_trainer_id,
        booking_primary_service_id=booking_primary_service_id,
    )
    return edge


def resolve_primary_catalog_service_id(
    primary_edge: dict | None,
    primary_source: str | None,
    session_selected_service_id: int | None,
) -> int | None:
    """
    Pick catalog ``service_id`` using the same tier that selected ``primary_edge``.

    - booking → ``last_booking_service_id`` on edge (including synthetic booking-primary rows)
    - saved → ``saved_catalog_service_id``
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
        "saved_at",
        "notify_when_slots_at",
        "last_booking_at",
        "last_completed_at",
        "last_interaction_at",
        "created_at",
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
