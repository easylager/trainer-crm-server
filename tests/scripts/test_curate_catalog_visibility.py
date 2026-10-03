import asyncio
import sys

import pytest

from scripts import curate_catalog_visibility as visibility


def test_show_requires_explicit_ids_before_database_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["curate_catalog_visibility.py", "--show"])
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        visibility.main()

    assert exc_info.value.code == 2


def test_cli_passes_the_reviewed_show_ids_to_run(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def capture_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(visibility, "run", capture_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["curate_catalog_visibility.py", "--show", "--show-ids", "42", "43"],
    )

    visibility.main()

    assert captured["show"] is True
    assert captured["show_ids"] == (42, 43)


class _Result:
    def __init__(self, rows: list[tuple] | None = None, row: tuple | None = None) -> None:
        self.rows = rows or []
        self.row = row

    def fetchall(self) -> list[tuple]:
        return self.rows

    def fetchone(self) -> tuple | None:
        return self.row


class _Session:
    def __init__(self, arenas: dict[int, str]) -> None:
        self.arenas = arenas
        self.queries: list[tuple[str, dict | None]] = []
        self.commits = 0

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, query: object, params: dict | None = None) -> _Result:
        sql = str(query)
        self.queries.append((sql, params))
        if "SELECT id, name FROM arenas WHERE id = ANY(:ids)" in sql:
            ids = params["ids"] if params else []
            return _Result(rows=[(arena_id, self.arenas[arena_id]) for arena_id in ids if arena_id in self.arenas])
        if "SELECT status FROM arena_profiles WHERE arena_id = :id" in sql:
            return _Result()
        raise AssertionError(f"unexpected query: {sql}")

    async def commit(self) -> None:
        self.commits += 1


class _Engine:
    async def dispose(self) -> None:
        return None


def _patch_run_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    session: _Session,
    writes: list[tuple[int, str, dict]],
) -> None:
    monkeypatch.setattr(visibility, "_db_url", lambda: "postgresql://localhost/trainer_crm_test")
    monkeypatch.setattr(visibility, "create_async_engine", lambda _url: _Engine())
    monkeypatch.setattr(visibility, "async_sessionmaker", lambda *_args, **_kwargs: lambda: session)

    async def record_patch(_session: _Session, arena_id: int, patch: dict) -> None:
        writes.append((arena_id, patch["status"], patch))

    monkeypatch.setattr(visibility, "apply_admin_arena_profile_patch", record_patch)


def test_show_restores_only_explicit_ids_and_never_runs_hide_selectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session({42: "Reviewed venue", 43: "Gym / Немига"})
    writes: list[tuple[int, str, dict]] = []
    _patch_run_dependencies(monkeypatch, session, writes)

    asyncio.run(
        visibility.run(
            apply=True,
            show=True,
            show_ids=(42,),
            i_know_this_is_prod=False,
        )
    )

    assert [arena_id for arena_id, _status, _patch in writes] == [42]
    assert all("ILIKE" not in sql and "venue_type" not in sql for sql, _params in session.queries)
    assert session.commits == 1


def test_missing_show_ids_abort_before_any_database_write(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session({42: "Existing venue"})
    writes: list[tuple[int, str, dict]] = []
    _patch_run_dependencies(monkeypatch, session, writes)

    with pytest.raises(SystemExit, match="43"):
        asyncio.run(
            visibility.run(
                apply=True,
                show=True,
                show_ids=(42, 43),
                i_know_this_is_prod=False,
            )
        )

    assert writes == []
    assert session.commits == 0
