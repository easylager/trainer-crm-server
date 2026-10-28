"""Скрипт ручного прогона источников с белорусским IP: выбор заданий и защита от неверного IP."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "ingest_by_local", Path(__file__).resolve().parents[2] / "scripts" / "ingest_by_local.py"
)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


def test_default_selection_covers_every_by_only_source() -> None:
    keys = mod.select_keys(None)
    for needed in (
        "ledlife_origin_html_v1",  # СДЮШОР
        "gorki_lds_v1",
        "bobruisk_arena_v1",
        "minskarena_speed_oval_v1",  # Конькобежный стадион
        "soligorsk_szk_v1",
    ):
        assert needed in keys


def test_only_filters_and_dedups_and_rejects_unknown() -> None:
    assert mod.select_keys(["gorki_lds_v1", "gorki_lds_v1"]) == ["gorki_lds_v1"]
    with pytest.raises(SystemExit):
        mod.select_keys(["no_such_parser"])


def test_every_listed_key_is_a_registered_parser() -> None:
    from src.ingestion.parsers import default_registry

    registry = default_registry()
    for key in mod.BY_ONLY_SOURCES:
        assert registry.get(key) is not None, key


def test_dry_run_reports_results_without_touching_the_store(capsys) -> None:
    import asyncio
    from datetime import date
    from types import SimpleNamespace

    class Store:
        written = False

        async def list_due(self, now):
            return [SimpleNamespace(arena_id=32, parser_key="gorki_lds_v1")]

        async def mark_attempted(self, *a, **k):  # не должен вызываться
            Store.written = True

    class Scheduler:
        _store = Store()

        async def _run_one(self, job, now):
            rec = SimpleNamespace(status="ok", http_status=200, error_code=None, error_message=None)
            drafts = [SimpleNamespace(local_date=date(2026, 10, 30)), SimpleNamespace(local_date=date(2026, 11, 2))]
            return rec, drafts, []

    out = asyncio.run(mod._dry_run(Scheduler(), ["gorki_lds_v1", "bobruisk_arena_v1"]))
    text = capsys.readouterr().out
    assert out == [] and Store.written is False
    assert "OK" in text and "слотов=2" in text and "30.10–02.11" in text
    assert "нет задания bobruisk_arena_v1" in text
    assert "База не менялась" in text
