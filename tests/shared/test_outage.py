from __future__ import annotations

from sqlalchemy.exc import IntegrityError, OperationalError

from src.shared.outage import is_db_unavailable, payload_looks_like_outage, service_unavailable_payload


def test_is_db_unavailable_operational_error() -> None:
    err = OperationalError("SELECT 1", {}, Exception("connection refused"))
    assert is_db_unavailable(err) is True


def test_is_db_unavailable_ignores_integrity_error() -> None:
    err = IntegrityError("INSERT", {}, Exception("duplicate key"))
    assert is_db_unavailable(err) is False


def test_is_db_unavailable_walks_cause() -> None:
    wrapped = RuntimeError("failed")
    wrapped.__cause__ = ConnectionRefusedError("postgres")
    assert is_db_unavailable(wrapped) is True


def test_service_unavailable_payload_contract() -> None:
    body = service_unavailable_payload()
    assert body["code"] == "service_unavailable"
    assert body["detail"] == body["message"]
    assert payload_looks_like_outage(body) is True
    assert payload_looks_like_outage({"detail": "database unavailable"}) is True
    assert payload_looks_like_outage({"detail": "not found"}) is False
