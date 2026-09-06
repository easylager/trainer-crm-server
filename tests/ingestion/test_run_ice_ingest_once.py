"""Local-DB guard for the one-shot ice ingest runner."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "run_ice_ingest_once.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location("run_ice_ingest_once", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_mod()


def test_refuses_cloud_and_non_local_database(runner) -> None:
    with pytest.raises(runner.ProdDatabaseError):
        runner._assert_local_database(
            "postgresql://u:p@prod.railway.app:5432/trainer_crm", apply=True
        )
    with pytest.raises(runner.ProdDatabaseError):
        runner._assert_local_database(
            "postgresql://u:p@db.example.com:5432/trainer_crm_test", apply=True
        )
    runner._assert_local_database(
        "postgresql+asyncpg://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm",
        apply=True,
    )
    runner._assert_local_database(
        "postgresql://trainer_crm:trainer_crm_dev@127.0.0.1:5432/trainer_crm_test",
        apply=True,
    )
    with pytest.raises(runner.ProdDatabaseError):
        runner._assert_local_database(
            "postgresql://trainer_crm:x@localhost:5432/postgres", apply=True
        )


def test_one_shot_only_bumps_merged_minsk_mk_keys(runner) -> None:
    assert "junost_origin_html_v1" not in runner.MINSK_MK_PARSER_KEYS
    assert "ledlife_origin_html_v1" not in runner.MINSK_MK_PARSER_KEYS
    assert runner.MINSK_MK_PARSER_KEYS == {
        "minskarena_saleframe_v1",
        "zamok_html_v1",
        "chizhovka_html_v1",
        "ledby_html_v1",
        "diamond_html_v1",
    }
