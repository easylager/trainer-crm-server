"""Smoke: TASK-208 ops scripts actually parse dossiers and scan public cards."""
from __future__ import annotations

import json
import uuid

import pytest

from tests.api.test_public_arenas import _insert_arena, _insert_city


def test_patch_target_fields_loads_three_dossiers() -> None:
    """_loader() must exec the dossier module (dataclass registration) and parse 29/2/6."""
    from scripts import patch_task208_dossier_opening_hours as patch_mod

    by_id = {
        arena_id: patch_mod._target_fields(patch_mod.CARDS / filename)
        for arena_id, filename in patch_mod.PATCHES
    }
    assert set(by_id) == {29, 2, 6}

    chizh = by_id[6]["opening_hours"]
    assert chizh["complex"] == {"open": "07:00", "close": "23:00"}
    assert "daily" not in chizh

    vitebsk = by_id[29]["opening_hours"]
    assert vitebsk["kassa"] == {"open": "11:00", "close": "21:00"}
    assert "daily" not in vitebsk
    assert by_id[29]["district"] is None

    note = by_id[2]["opening_hours"]["note"]
    blob = json.dumps(by_id, ensure_ascii=False).casefold()
    assert "unknown" not in blob
    assert "conflicts" not in blob
    assert "склеивать" not in blob
    assert "unknown" not in note.casefold()


@pytest.mark.asyncio
async def test_check_scan_hides_stored_dossier_markers(app_use_test_db, db_session) -> None:
    from scripts import check_public_dossier_leaks as check_mod

    city_id = await _insert_city(db_session, name=f"Утечка {uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(
        db_session,
        city_id,
        name="Каток со служебной пометкой",
        district="unknown",
        opening_hours={"note": "unknown (общий режим). см. Conflicts (не склеивать)"},
    )
    _scanned, failures, checked = await check_mod._scan(db_session)
    assert arena_id in checked
    assert failures == []
