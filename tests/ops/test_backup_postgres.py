from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "ops" / "backup_postgres.py"


def _load_backup_mod():
    spec = importlib.util.spec_from_file_location("backup_postgres", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sync_database_url_strips_asyncpg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKUP_DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/db")
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    mod = _load_backup_mod()
    assert mod._sync_database_url() == "postgresql://u:p@h:5432/db"


def test_assert_pg_dump_rejects_tiny(tmp_path: Path) -> None:
    mod = _load_backup_mod()
    p = tmp_path / "dump.sql"
    p.write_text("-- too small\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="suspiciously small"):
        mod._assert_pg_dump_looks_valid(p)


def test_assert_pg_dump_accepts_header(tmp_path: Path) -> None:
    mod = _load_backup_mod()
    p = tmp_path / "dump.sql"
    body = "--\n-- PostgreSQL database dump\n--\n" + ("x" * 1200)
    p.write_text(body, encoding="utf-8")
    mod._assert_pg_dump_looks_valid(p)
