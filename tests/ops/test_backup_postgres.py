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


def test_resolve_pg_dump_prefers_versioned_debian_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_backup_mod()
    pg_root = tmp_path / "postgresql"
    old16 = pg_root / "16" / "bin"
    new18 = pg_root / "18" / "bin"
    old16.mkdir(parents=True)
    new18.mkdir(parents=True)
    (old16 / "pg_dump").write_text("#!/bin/sh\n", encoding="utf-8")
    (new18 / "pg_dump").write_text("#!/bin/sh\n", encoding="utf-8")
    (old16 / "pg_dump").chmod(0o755)
    (new18 / "pg_dump").chmod(0o755)

    monkeypatch.delenv("BACKUP_PG_DUMP", raising=False)
    monkeypatch.setenv("BACKUP_PG_MAJOR", "18")

    real_path = Path

    def fake_path(p):
        if p == "/usr/lib/postgresql":
            return pg_root
        return real_path(p)

    monkeypatch.setattr(mod, "Path", fake_path)
    assert mod._resolve_pg_dump() == str(new18 / "pg_dump")


def test_resolve_pg_dump_honors_explicit_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mod = _load_backup_mod()
    tool = tmp_path / "pg_dump"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("BACKUP_PG_DUMP", str(tool))
    assert mod._resolve_pg_dump() == str(tool)
