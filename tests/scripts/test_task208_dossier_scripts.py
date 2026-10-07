"""Smoke: TASK-208 ops scripts import and run read-only against the test DB."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from src.shared.config import Settings


@pytest.mark.asyncio
async def test_check_public_dossier_leaks_smoke(app_use_test_db, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", Settings().database_url)
    from scripts import check_public_dossier_leaks as check_mod

    code = await check_mod._run(allow_prod=False)
    assert code in (0, 1)


@pytest.mark.asyncio
async def test_patch_task208_dossier_opening_hours_smoke(app_use_test_db, db_session) -> None:
    has_prod_targets = (
        await db_session.execute(
            text("SELECT 1 FROM arena_profiles WHERE arena_id IN (29, 2, 6) LIMIT 1")
        )
    ).scalar_one_or_none()
    if not has_prod_targets:
        pytest.skip("TASK-208 patch targets (arenas 29/2/6) not in test DB")
    from scripts import patch_task208_dossier_opening_hours as patch_mod

    await patch_mod.run(apply=False, allow_prod=False)
