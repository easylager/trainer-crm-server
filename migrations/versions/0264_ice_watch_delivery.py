"""Ice watch delivery: subscription baseline, delivery journal, deactivation reason (TASK-328).

- ``client_ice_watches.baseline_horizon_date`` — the latest ``local_date`` of the rink's
  future public sessions at subscription time. A reminder fires only for sessions past it,
  so a subscription made on a non-empty card no longer fires at once.
- ``client_ice_watches.failed_attempts`` / ``deactivated_reason`` — transient send failures
  are retried; after five, or at once when the chat is unreachable, the watch is switched
  off with a reason instead of retrying forever.
- ``client_ice_watch_deliveries`` — one row per send attempt (ids only, no message text).

Active watches get the baseline backfilled from today's sessions: otherwise the first pass
after deploy would send «новое расписание» for sessions that were already on the card.

Revision ID: 0264_ice_watch_delivery
Revises: 0263_arena_profile_facts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0264_ice_watch_delivery"
down_revision = "0263_arena_profile_facts"
branch_labels = None
depends_on = None

_REASONS = ("unreachable", "failed")


def upgrade() -> None:
    op.add_column("client_ice_watches", sa.Column("baseline_horizon_date", sa.Date(), nullable=True))
    op.add_column(
        "client_ice_watches",
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("client_ice_watches", sa.Column("deactivated_reason", sa.String(16), nullable=True))
    op.create_check_constraint(
        "ck_client_ice_watches_deactivated_reason",
        "client_ice_watches",
        f"deactivated_reason IS NULL OR deactivated_reason IN ({', '.join(repr(r) for r in _REASONS)})",
    )

    op.create_table(
        "client_ice_watch_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "watch_id",
            sa.BigInteger(),
            sa.ForeignKey("client_ice_watches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("arena_id", sa.Integer(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(200), nullable=True),
    )
    op.create_index(
        "ix_client_ice_watch_deliveries_watch",
        "client_ice_watch_deliveries",
        ["watch_id", "attempted_at"],
    )
    op.create_index(
        "ix_client_ice_watch_deliveries_attempted",
        "client_ice_watch_deliveries",
        ["attempted_at"],
    )

    op.execute("""
        UPDATE client_ice_watches w
        SET baseline_horizon_date = h.horizon
        FROM (
            SELECT arena_id, MAX(local_date) AS horizon
            FROM ice_sessions
            WHERE status = 'active'
              AND starts_at_utc > now()
              AND kind IN ('public_skate', 'open_ice')
            GROUP BY arena_id
        ) h
        WHERE w.arena_id = h.arena_id
          AND w.active = true
          AND w.watch_kind IN ('sessions', 'schedule_fresh')
        """)


def downgrade() -> None:
    op.drop_index("ix_client_ice_watch_deliveries_attempted", table_name="client_ice_watch_deliveries")
    op.drop_index("ix_client_ice_watch_deliveries_watch", table_name="client_ice_watch_deliveries")
    op.drop_table("client_ice_watch_deliveries")
    op.drop_constraint("ck_client_ice_watches_deactivated_reason", "client_ice_watches", type_="check")
    op.drop_column("client_ice_watches", "deactivated_reason")
    op.drop_column("client_ice_watches", "failed_attempts")
    op.drop_column("client_ice_watches", "baseline_horizon_date")
