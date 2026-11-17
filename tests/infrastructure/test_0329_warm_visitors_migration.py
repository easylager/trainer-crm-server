"""TASK-428: миграция 0329 — откат и повторный накат не теряют «Не присылать», учёт сообщений и события воронки."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
KEY = 9429001


def _alembic(*args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, capture_output=True, text=True, env=os.environ.copy()
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def _counts(engine) -> tuple[int, int, int]:
    async with engine.connect() as c:
        prefs = (await c.execute(text("SELECT count(*) FROM warm_prefs WHERE telegram_id = :k"), {"k": KEY})).scalar()
        notices = (
            await c.execute(text("SELECT count(*) FROM warm_notices WHERE telegram_id = :k"), {"k": KEY})
        ).scalar()
        events = (
            await c.execute(text("SELECT count(*) FROM catalog_consumer_events WHERE actor_hash = 'mig-0329'"))
        ).scalar()
    return int(prefs or 0), int(notices or 0), int(events or 0)


@pytest.mark.asyncio
async def test_downgrade_and_upgrade_keep_warm_data() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        async with engine.begin() as c:
            await c.execute(text("DELETE FROM warm_prefs WHERE telegram_id = :k"), {"k": KEY})
            await c.execute(text("DELETE FROM warm_notices WHERE telegram_id = :k"), {"k": KEY})
            await c.execute(text("DELETE FROM catalog_consumer_events WHERE actor_hash = 'mig-0329'"))
            await c.execute(text("INSERT INTO warm_prefs (telegram_id, opted_out_at) VALUES (:k, now())"), {"k": KEY})
            await c.execute(
                text(
                    "INSERT INTO warm_notices (telegram_id, kind, ref, sent_at) VALUES (:k, 'warm_nudge', 'once', now())"
                ),
                {"k": KEY},
            )
            await c.execute(text("""INSERT INTO catalog_consumer_events (kind, surface, actor_hash)
                        VALUES ('watch_offer_shown', 'place_page', 'mig-0329')"""))
        _alembic("downgrade", "0328_kk_notify_kinds")
        assert await _counts(engine) == (1, 1, 1)  # откат ничего не удалил
        with pytest.raises(IntegrityError):  # прежний (мягкий) CHECK: старый код новые события не вставит
            async with engine.begin() as c:
                await c.execute(
                    text("INSERT INTO catalog_consumer_events (kind, surface) VALUES ('watch_offer_click', 'x')")
                )
        _alembic("upgrade", "head")
        assert await _counts(engine) == (1, 1, 1)
        async with engine.begin() as c:
            await c.execute(text("""INSERT INTO catalog_consumer_events (kind, surface, actor_hash)
                        VALUES ('watch_offer_click', 'place_page', 'mig-0329')"""))
    finally:
        _alembic("upgrade", "head")
        async with engine.begin() as c:
            await c.execute(text("DELETE FROM warm_prefs WHERE telegram_id = :k"), {"k": KEY})
            await c.execute(text("DELETE FROM warm_notices WHERE telegram_id = :k"), {"k": KEY})
            await c.execute(text("DELETE FROM catalog_consumer_events WHERE actor_hash = 'mig-0329'"))
        await engine.dispose()
