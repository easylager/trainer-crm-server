"""
Strict client «primary trainer» tier:
booking (upcoming or latest) → explicit pin → ever-booked → saved → session.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.application.client_trainer_primary_graph import (
    compute_primary_edge_meta,
    hub_booking_primary_ids,
    resolve_primary_catalog_service_id,
)


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


def test_hub_booking_primary_ids_upcoming_over_latest() -> None:
    assert hub_booking_primary_ids(5, 6, 7, 8) == (5, 6)


def test_hub_booking_primary_ids_latest_when_no_upcoming() -> None:
    assert hub_booking_primary_ids(None, None, 7, 8) == (7, 8)


def test_explicit_primary_beats_latest_booking() -> None:
    """Invite / user pin: is_primary row wins over past bookings, not over booking tier input."""
    edges = [
        {"trainer_id": 9, "is_primary": True, "is_saved": False},
        {"trainer_id": 1, "is_saved": True, "saved_at": datetime(2025, 2, 1, tzinfo=timezone.utc)},
    ]
    explicit = {"trainer_id": 9, "is_primary": True, "is_saved": False}
    edge, src = compute_primary_edge_meta(
        edges,
        session_trainer_id=1,
        booking_primary_trainer_id=2,
        booking_primary_service_id=10,
        explicit_primary_edge=explicit,
    )
    assert src == "booking"
    assert int(edge["trainer_id"]) == 2

    edge2, src2 = compute_primary_edge_meta(
        edges,
        session_trainer_id=1,
        booking_primary_trainer_id=None,
        booking_primary_service_id=None,
        explicit_primary_edge=explicit,
    )
    assert src2 == "primary"
    assert edge2 is not None
    assert int(edge2["trainer_id"]) == 9


def test_primary_latest_booking_beats_newer_saved() -> None:
    """Hub merges upcoming+latest; without upcoming, last visit wins over last heart."""
    edges = [
        {
            "trainer_id": 1,
            "is_saved": True,
            "saved_at": datetime(2025, 2, 1, tzinfo=timezone.utc),
            "created_at": None,
        },
    ]
    edge, src = compute_primary_edge_meta(
        edges,
        session_trainer_id=None,
        booking_primary_trainer_id=2,
        booking_primary_service_id=10,
    )
    assert src == "booking"
    assert edge is not None
    assert int(edge["trainer_id"]) == 2
    assert int(edge["last_booking_service_id"]) == 10


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


def test_ever_booked_beats_saved_and_session() -> None:
    """
    Запись, выпавшая из живых тиров (слот отменён / занятие снято тренером), всё равно
    сильнее лайка в каталоге и последнего просмотра: клиент реально был у этого тренера.
    """
    edges = [
        {
            "trainer_id": 7,
            "is_saved": True,
            "saved_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        }
    ]
    edge, src = compute_primary_edge_meta(
        edges,
        session_trainer_id=8,
        booking_primary_trainer_id=None,
        booking_primary_service_id=None,
        ever_booked_trainer_id=3,
        ever_booked_service_id=42,
    )
    assert src == "ever_booked"
    assert edge is not None
    assert int(edge["trainer_id"]) == 3
    assert int(edge["last_booking_service_id"]) == 42
    assert resolve_primary_catalog_service_id(edge, src, None) == 42


def test_live_booking_and_explicit_pin_still_beat_ever_booked() -> None:
    """Новый тир — только страховка: он не должен перебивать живую запись или явный выбор клиента."""
    edges = [{"trainer_id": 9, "is_primary": True, "is_saved": False}]
    edge, src = compute_primary_edge_meta(
        edges,
        session_trainer_id=None,
        booking_primary_trainer_id=2,
        booking_primary_service_id=10,
        explicit_primary_edge={"trainer_id": 9},
        ever_booked_trainer_id=3,
    )
    assert src == "booking"
    assert int(edge["trainer_id"]) == 2

    edge2, src2 = compute_primary_edge_meta(
        edges,
        session_trainer_id=None,
        booking_primary_trainer_id=None,
        booking_primary_service_id=None,
        explicit_primary_edge={"trainer_id": 9},
        ever_booked_trainer_id=3,
    )
    assert src2 == "primary"
    assert int(edge2["trainer_id"]) == 9
