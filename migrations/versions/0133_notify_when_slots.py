"""Add notify_when_slots flag to client_trainer_edges.

Clients can subscribe to "notify me when new slots appear" for a trainer.
One-shot: flag is cleared after the notification is sent.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0133_notify_when_slots"
down_revision = "0132_edge_pair_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_trainer_edges",
        sa.Column(
            "notify_when_slots",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "client_trainer_edges",
        sa.Column(
            "notify_when_slots_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_client_trainer_edges_notify_slots",
        "client_trainer_edges",
        ["trainer_id"],
        postgresql_where=sa.text("notify_when_slots = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_client_trainer_edges_notify_slots", table_name="client_trainer_edges")
    op.drop_column("client_trainer_edges", "notify_when_slots_at")
    op.drop_column("client_trainer_edges", "notify_when_slots")
