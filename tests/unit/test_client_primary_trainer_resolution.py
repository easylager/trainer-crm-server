"""Strict client «primary trainer» tier: upcoming booking → saved → session."""
from __future__ import annotations

from datetime import datetime, timezone

from src.application.client_trainer_primary_graph import compute_primary_edge_meta


def test_primary_booking_overrides_saved_and_session() -> None:
    edges = [
        {
            "trainer_id": 1,
            "is_saved": True,
            "saved_at": datetime(2025, 1, 2, tzinfo=timezone.utc),
            "created_at": None,
        },
    ]
    edge, src = compute_primary_edge_meta(
        edges,
        session_trainer_id=9,
        booking_primary_trainer_id=2,
        booking_primary_service_id=88,
    )
    assert src == "booking"
    assert edge is not None
    assert int(edge["trainer_id"]) == 2
    assert int(edge["last_booking_service_id"]) == 88


def test_primary_saved_newest_when_no_booking() -> None:
    edges = [
        {
            "trainer_id": 1,
            "is_saved": True,
            "saved_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "created_at": None,
        },
        {
            "trainer_id": 2,
            "is_saved": True,
            "saved_at": datetime(2025, 2, 1, tzinfo=timezone.utc),
            "created_at": None,
        },
    ]
    edge, src = compute_primary_edge_meta(
        edges,
        session_trainer_id=99,
        booking_primary_trainer_id=None,
        booking_primary_service_id=None,
    )
    assert src == "saved"
    assert edge is not None
    assert int(edge["trainer_id"]) == 2


def test_primary_session_when_no_booking_no_saved() -> None:
    edges = [{"trainer_id": 5, "is_saved": False}]
    edge, src = compute_primary_edge_meta(
        edges,
        session_trainer_id=5,
        booking_primary_trainer_id=None,
        booking_primary_service_id=None,
    )
    assert src == "session"
    assert edge is not None
    assert int(edge["trainer_id"]) == 5


def test_primary_session_synthetic_when_not_in_edges() -> None:
    edge, src = compute_primary_edge_meta(
        [],
        session_trainer_id=7,
        booking_primary_trainer_id=None,
        booking_primary_service_id=None,
    )
    assert src == "session"
    assert edge is not None
    assert int(edge["trainer_id"]) == 7


def test_primary_none_when_only_past_booking_signal_would_be_suppressed() -> None:
    """Hub passes upcoming booking id only; past-only history must not set primary via booking tier."""
    edge, src = compute_primary_edge_meta(
        [],
        session_trainer_id=None,
        booking_primary_trainer_id=None,
        booking_primary_service_id=None,
    )
    assert edge is None
    assert src is None


def test_primary_none_when_no_signals() -> None:
    edges = [{"trainer_id": 5, "is_saved": False}]
    edge, src = compute_primary_edge_meta(
        edges,
        session_trainer_id=None,
        booking_primary_trainer_id=None,
        booking_primary_service_id=None,
    )
    assert edge is None
    assert src is None
