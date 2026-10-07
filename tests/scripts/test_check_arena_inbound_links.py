"""scripts/check_arena_inbound_links.py — сироты на тестовых данных."""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.api.test_public_arenas import _insert_arena, _insert_city

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_arena_inbound_links.py"


@pytest.mark.asyncio
async def test_inbound_links_script_finds_no_orphans_for_city_listed_arena(
    app_use_test_db, db_session, monkeypatch
) -> None:
    monkeypatch.setenv("ICE_DISCOVERY_COUNTRIES", "BY")
    name = f"Ссылкоград {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name, country="BY")
    aid = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    await db_session.commit()
    slug = (
        await db_session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id = :id"), {"id": aid})
    ).scalar_one()

    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"orphans=0" in proc.stdout
    assert f"/p/" in proc.stdout or "arenas_checked=" in proc.stdout
