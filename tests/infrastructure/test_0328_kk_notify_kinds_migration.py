"""TASK-426: миграция 0328 — откат и повторный накат не теряют ответ «Не присылать» и защиту от дублей."""

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
KEY = 9428001


def _alembic(*args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, capture_output=True, text=True, env=os.environ.copy()
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_downgrade_and_upgrade_keep_consent_answers_and_notice_rows() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        async with engine.begin() as c:
            await c.execute(text("DELETE FROM hockey_players WHERE player_key = :k"), {"k": KEY})
            await c.execute(text("DELETE FROM hockey_matches WHERE source_match_id = 'kk426-mig'"))
            await c.execute(text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, 'М')"), {"k": KEY})
            await c.execute(text("INSERT INTO hockey_player_prefs (player_key, notify_consent) VALUES (:k, false)"), {"k": KEY})
            mid = (
                await c.execute(
                    text("""INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at)
                            VALUES ('hockeyby', 'extraliga', 'kk426-mig', 'Юность', 'Шахтер', now()) RETURNING id""")
                )
            ).scalar_one()
            await c.execute(
                text("INSERT INTO hockey_notices (player_key, match_id, kind, sent_at) VALUES (:k, :m, 'week', now())"),
                {"k": KEY, "m": mid},
            )
        _alembic("downgrade", "-1")
        async with engine.connect() as c:
            kept = (await c.execute(text("SELECT notify_consent FROM hockey_player_prefs WHERE player_key = :k"), {"k": KEY})).scalar_one()
            rows = (await c.execute(text("SELECT count(*) FROM hockey_notices WHERE player_key = :k AND kind = 'week'"), {"k": KEY})).scalar_one()
        assert kept is False and rows == 1  # ничего не потеряно при откате
        # прежний (мягкий) CHECK: новые виды старый код вставить не сможет
        with pytest.raises(IntegrityError):
            async with engine.begin() as c:
                await c.execute(text("INSERT INTO hockey_notices (player_key, match_id, kind) VALUES (:k, :m, 'invite')"), {"k": KEY, "m": mid})
        _alembic("upgrade", "head")
        async with engine.connect() as c:
            again = (await c.execute(text("SELECT notify_consent FROM hockey_player_prefs WHERE player_key = :k"), {"k": KEY})).scalar_one()
            rows = (await c.execute(text("SELECT count(*) FROM hockey_notices WHERE player_key = :k AND kind = 'week'"), {"k": KEY})).scalar_one()
        assert again is False and rows == 1  # «Не присылать» пережило накат, защита от дублей на месте
        async with engine.begin() as c:  # новые виды снова принимаются
            await c.execute(text("INSERT INTO hockey_notices (player_key, match_id, kind) VALUES (:k, :m, 'invite')"), {"k": KEY, "m": mid})
    finally:
        _alembic("upgrade", "head")  # что бы ни случилось в тесте, база остаётся на голове
        async with engine.begin() as c:
            await c.execute(text("DELETE FROM hockey_players WHERE player_key = :k"), {"k": KEY})
            await c.execute(text("DELETE FROM hockey_matches WHERE source_match_id = 'kk426-mig'"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_upgrade_backfill_fills_only_unanswered_players() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    keys = {"null": KEY + 1, "true": KEY + 2, "false": KEY + 3, "off": KEY + 4}
    try:
        async with engine.begin() as c:
            await c.execute(text("DELETE FROM hockey_players WHERE player_key = ANY(:k)"), {"k": list(keys.values())})
            await c.execute(text("DELETE FROM hockey_matches WHERE source_match_id = 'kk426-mig2'"))
            mid = (
                await c.execute(
                    text("""INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at)
                            VALUES ('hockeyby', 'extraliga', 'kk426-mig2', 'Юность', 'Шахтер', now() + interval '1 day') RETURNING id""")
                )
            ).scalar_one()
            for name, key in keys.items():
                await c.execute(text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, 'М')"), {"k": key})
                await c.execute(text("INSERT INTO hockey_picks (match_id, player_key, side) VALUES (:m, :k, 'home')"), {"m": mid, "k": key})
            await c.execute(text("INSERT INTO hockey_player_prefs (player_key, notify_consent) VALUES (:k, true)"), {"k": keys["true"]})
            await c.execute(text("INSERT INTO hockey_player_prefs (player_key, notify_consent) VALUES (:k, false)"), {"k": keys["false"]})
            await c.execute(text("INSERT INTO hockey_player_prefs (player_key, remind) VALUES (:k, false)"), {"k": keys["off"]})
        _alembic("downgrade", "-1")
        _alembic("upgrade", "head")
        async with engine.connect() as c:
            got = {
                r.player_key: r.notify_consent
                for r in (await c.execute(text("SELECT player_key, notify_consent FROM hockey_player_prefs WHERE player_key = ANY(:k)"), {"k": list(keys.values())})).all()
            }
        assert got == {keys["null"]: True, keys["true"]: True, keys["false"]: False, keys["off"]: None}
    finally:
        _alembic("upgrade", "head")
        async with engine.begin() as c:
            await c.execute(text("DELETE FROM hockey_players WHERE player_key = ANY(:k)"), {"k": list(keys.values())})
            await c.execute(text("DELETE FROM hockey_matches WHERE source_match_id = 'kk426-mig2'"))
        await engine.dispose()
