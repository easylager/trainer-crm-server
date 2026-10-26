"""Zhodino and Bereza: weekly manual schedule, so the card can wait for it.

Neither rink publishes a parsable source (Bereza — a weekly Instagram post, Zhodino — nothing
yet). An enabled ``manual_schedule_v1`` job puts the arena under watch: with no sessions the
card shows the «waiting for the schedule» block with the Telegram bell, and sessions entered by
hand reach the subscribers.

Revision ID: 0274_manual_schedule_jobs
Revises: 0273_mogilev_bycard_source
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0274_manual_schedule_jobs"
down_revision = "0273_mogilev_bycard_source"
branch_labels = None
depends_on = None

_PARSER_KEY = "manual_schedule_v1"
_ARENAS = (20, 26)  # Жодино (СДЮШОР), Берёза (Ледовая арена)
_CONFIG = {"timezone": "Europe/Minsk", "kind": "public_skate"}


def upgrade() -> None:
    conn = op.get_bind()
    for arena_id in _ARENAS:
        conn.execute(
            sa.text(
                "INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config, notes) "
                "SELECT :a, :k, true, 'weekly', now(), CAST(:c AS jsonb), 'manual weekly schedule' "
                "WHERE EXISTS (SELECT 1 FROM arenas WHERE id = :a) "
                "AND NOT EXISTS (SELECT 1 FROM ice_parser_jobs WHERE arena_id = :a)"
            ),
            {"a": arena_id, "k": _PARSER_KEY, "c": json.dumps(_CONFIG)},
        )
    # Берёза: строку задания завели заранее выключенной (для записи прогона до выкатки парсера).
    conn.execute(
        sa.text(
            "UPDATE ice_parser_jobs SET is_enabled = true, next_run_at = now() "
            "WHERE parser_key = :k AND arena_id = ANY(:a) AND NOT is_enabled"
        ),
        {"k": _PARSER_KEY, "a": list(_ARENAS)},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM ice_parser_jobs WHERE parser_key = :k AND arena_id = ANY(:a)"),
        {"k": _PARSER_KEY, "a": list(_ARENAS)},
    )
