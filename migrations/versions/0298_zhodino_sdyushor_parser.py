"""Zhodino: the rink's site now has a weekly mass-skating table — parser instead of manual.

Arena 20 had a ``manual_schedule_v1`` job (0274). Its row is switched to ``zhodino_sdyushor_v1``
with the source config. The site answers only from a Belarusian IP, so, like the other BY-only
sources, the job stays disabled on Railway and is run by ``scripts/by_ingest.sh`` (it picks jobs by
``parser_key`` regardless of ``is_enabled``).

Revision ID: 0298_zhodino_sdyushor_parser
Revises: 0297_kk_bot_default_on
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0298_zhodino_sdyushor_parser"
down_revision = "0297_kk_bot_default_on"
branch_labels = None
depends_on = None

_ARENA_ID = 20
_OLD_KEY = "manual_schedule_v1"
_NEW_KEY = "zhodino_sdyushor_v1"
_CONFIG = {
    "schedule_url": (
        "https://www.xn----8sbkhlnbugdd1c.xn--90ais/"
        "%D1%80%D0%B0%D1%81%D0%BF%D0%B8%D1%81%D0%B0%D0%BD%D0%B8%D0%B5-2/"
    ),
    "prices_url": "https://www.xn----8sbkhlnbugdd1c.xn--90ais/%D1%86%D0%B5%D0%BD%D1%8B/",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "default_duration_minutes": 45,
    "age_note": "детский до 14 лет",
    "prices_already_minor": True,
    "requires_by_egress": True,
    "arena_slug": "zhodino-sdyushor",
    "city_name": "Жодино",
}
_OLD_CONFIG = {"timezone": "Europe/Minsk", "kind": "public_skate"}


def upgrade() -> None:
    conn = op.get_bind()
    params = {"a": _ARENA_ID, "old": _OLD_KEY, "new": _NEW_KEY, "c": json.dumps(_CONFIG)}
    conn.execute(
        sa.text(
            "UPDATE ice_parser_jobs SET parser_key = :new, config = CAST(:c AS jsonb), is_enabled = false, "
            "cadence = 'daily', next_run_at = now(), notes = 'regional: zhodino_sdyushor_v1 (BY IP, by_ingest.sh)' "
            "WHERE arena_id = :a AND parser_key = :old"
        ),
        params,
    )
    conn.execute(
        sa.text(
            "INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config, notes) "
            "SELECT :a, :new, false, 'daily', now(), CAST(:c AS jsonb), "
            "'regional: zhodino_sdyushor_v1 (BY IP, by_ingest.sh)' "
            "WHERE EXISTS (SELECT 1 FROM arenas WHERE id = :a) "
            "AND NOT EXISTS (SELECT 1 FROM ice_parser_jobs WHERE arena_id = :a)"
        ),
        params,
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE ice_parser_jobs SET parser_key = :old, config = CAST(:c AS jsonb), is_enabled = true, "
            "cadence = 'weekly', notes = 'manual weekly schedule' WHERE arena_id = :a AND parser_key = :new"
        ),
        {"a": _ARENA_ID, "old": _OLD_KEY, "new": _NEW_KEY, "c": json.dumps(_OLD_CONFIG)},
    )
