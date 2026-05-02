"""Trainer CRM roster: clients linked manually without requiring a booking.

Revision ID: 0142_trainer_client_roster
Revises: 0141_client_repeat_gap_notif
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0142_trainer_client_roster"
down_revision = "0141_client_repeat_gap_notif"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_client_roster",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trainer_id", "client_id", name="uq_trainer_client_roster_trainer_client"),
    )
    op.create_index(
        "ix_trainer_client_roster_trainer_id",
        "trainer_client_roster",
        ["trainer_id"],
        unique=False,
    )
    op.create_index(
        "ix_trainer_client_roster_client_id",
        "trainer_client_roster",
        ["client_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_trainer_client_roster_client_id", table_name="trainer_client_roster")
    op.drop_index("ix_trainer_client_roster_trainer_id", table_name="trainer_client_roster")
    op.drop_table("trainer_client_roster")
