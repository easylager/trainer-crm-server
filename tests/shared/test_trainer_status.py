"""Normalize trainer status values from DB/drivers."""
from enum import Enum

import pytest

from src.shared.trainer_status import normalize_trainer_status_value


class _PgLike(str, Enum):
    """Simulate PostgreSQL/asyncpg enum label storage."""

    active = "active"
    pending_profile = "pending_profile"


def test_normalize_plain_str() -> None:
    assert normalize_trainer_status_value("ACTIVE") == "active"
    assert normalize_trainer_status_value(" active ") == "active"


def test_normalize_str_subclass_enum() -> None:
    assert normalize_trainer_status_value(_PgLike.active) == "active"


@pytest.mark.parametrize("raw", [None, ""])
def test_normalize_empty(raw: str | None) -> None:
    assert normalize_trainer_status_value(raw) == ""
