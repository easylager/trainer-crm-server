"""Catalog publication state for collectives (schools) — TASK-141 S5.

Parallel to ``trainers.catalog_state`` (0206), not an extension of it: a school has no
moderator queue (owner decision — self-publish once the profile checklist clears, see
TASK-141 S5 scope note), so this is a 3-state model (draft/published/hidden) without the
moderation states trainer cards carry. Keeping it a separate table/columns avoids coupling
the school's simpler flow to the trainer state machine's transition table and notification
path, which assume a moderator actor that doesn't exist here.

Backfill: an already-``active`` collective is reachable today at its public landing page
(``GET /api/public/collectives/{slug}``, gated only on ``status``) — this migration adds a
second gate on ``catalog_state`` to that endpoint (see the S5 route change), so an existing
active school must be backfilled to ``published`` or its live page would 404 the moment this
ships. A ``draft``/``suspended`` collective has nothing to preserve.

Revision ID: 0209_collective_catalog_state
Revises: 0208_certificate_fixed_amount
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0209_collective_catalog_state"
down_revision = "0208_certificate_fixed_amount"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collectives",
        sa.Column("catalog_state", sa.String(24), nullable=False, server_default="draft"),
    )
    op.add_column(
        "collectives", sa.Column("catalog_state_reason", sa.String(64), nullable=True)
    )
    op.add_column(
        "collectives",
        sa.Column("catalog_state_changed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "collective_catalog_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "collective_id",
            sa.Integer(),
            sa.ForeignKey("collectives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_state", sa.String(24), nullable=True),
        sa.Column("to_state", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column("reason_detail", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_collective_catalog_events_collective",
        "collective_catalog_events",
        ["collective_id", sa.text("created_at DESC")],
    )

    op.execute(
        """
        UPDATE collectives SET
            catalog_state = 'published',
            catalog_state_changed_at = now()
        WHERE status = 'active'
        """
    )
    op.execute(
        """
        INSERT INTO collective_catalog_events (
            collective_id, from_state, to_state, reason, reason_detail, actor_type, actor_id
        )
        SELECT id, NULL, 'published', 'backfill_0209',
               'Состояние восстановлено из status=active при переходе на явную модель (0209).',
               'system', 'migration'
        FROM collectives
        WHERE status = 'active'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_collective_catalog_events_collective", table_name="collective_catalog_events"
    )
    op.drop_table("collective_catalog_events")
    op.drop_column("collectives", "catalog_state_changed_at")
    op.drop_column("collectives", "catalog_state_reason")
    op.drop_column("collectives", "catalog_state")
