"""Ops scripts refuse cloud DBs unless --i-know-this-is-prod is set."""
from __future__ import annotations

import argparse

import pytest

from src.shared.ops_db_guard import (
    ProdDatabaseError,
    add_i_know_this_is_prod_argument,
    assert_database_url,
)


_RAILWAY = "postgresql://u:p@postgres.railway.internal:5432/railway"
_RLWY_PUBLIC = "postgresql://u:p@maglev.proxy.rlwy.net:12345/trainer_crm"
_LOCAL_TEST = "postgresql+asyncpg://trainer_crm:x@localhost:5432/trainer_crm_test"
_LOCAL_DEV = "postgresql://trainer_crm:x@127.0.0.1:5432/trainer_crm"
_REMOTE_NONCLOUD = "postgresql://u:p@db.example.com:5432/trainer_crm_test"


def test_refuses_railway_and_public_proxy_by_default() -> None:
    with pytest.raises(ProdDatabaseError, match="cloud/prod"):
        assert_database_url(_RAILWAY, apply=True)
    with pytest.raises(ProdDatabaseError, match="non-local"):
        assert_database_url(_RLWY_PUBLIC, apply=True)
    with pytest.raises(ProdDatabaseError, match="non-local"):
        assert_database_url(_REMOTE_NONCLOUD, apply=True)


def test_local_apply_allowed_on_known_db_names() -> None:
    assert_database_url(_LOCAL_TEST, apply=True)
    assert_database_url(_LOCAL_DEV, apply=True)
    with pytest.raises(ProdDatabaseError, match="apply is limited"):
        assert_database_url(
            "postgresql://trainer_crm:x@localhost:5432/postgres", apply=True
        )


def test_load_cards_style_requires_allow_local_dev_for_trainer_crm() -> None:
    assert_database_url(
        _LOCAL_TEST,
        apply=True,
        allowed_apply_db_names=frozenset({"trainer_crm_test"}),
    )
    with pytest.raises(ProdDatabaseError, match="apply is limited"):
        assert_database_url(
            _LOCAL_DEV,
            apply=True,
            allowed_apply_db_names=frozenset({"trainer_crm_test"}),
        )
    assert_database_url(
        _LOCAL_DEV,
        apply=True,
        allowed_apply_db_names=frozenset({"trainer_crm_test", "trainer_crm"}),
    )


def test_i_know_this_is_prod_allows_railway_apply() -> None:
    assert_database_url(_RAILWAY, apply=True, allow_prod=True)
    assert_database_url(_RLWY_PUBLIC, apply=True, allow_prod=True)
    assert_database_url(_RAILWAY, apply=False, allow_prod=True)


def test_allow_prod_does_not_skip_when_false() -> None:
    with pytest.raises(ProdDatabaseError):
        assert_database_url(_RAILWAY, apply=True, allow_prod=False)


def test_cli_flag_wires_dest() -> None:
    parser = argparse.ArgumentParser()
    add_i_know_this_is_prod_argument(parser)
    assert parser.parse_args([]).i_know_this_is_prod is False
    assert parser.parse_args(["--i-know-this-is-prod"]).i_know_this_is_prod is True
