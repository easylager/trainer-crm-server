"""Audit trail for duplicate-client merges (trainer-typo phone, self-registered separately).

Revision ID: 0205_client_merges_audit
Revises: 0204_widen_source_id
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0205_client_merges_audit"
down_revision = "0204_widen_source_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_merges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # Not an FK: the from-client row is deleted as part of the merge it records.
        sa.Column("from_client_id", sa.Integer(), nullable=False),
        sa.Column(
            "to_client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "merged_by_trainer_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_client_merges_from_client_id", "client_merges", ["from_client_id"])
    op.create_index("ix_client_merges_to_client_id", "client_merges", ["to_client_id"])


def downgrade() -> None:
    op.drop_index("ix_client_merges_to_client_id", table_name="client_merges")
    op.drop_index("ix_client_merges_from_client_id", table_name="client_merges")
    op.drop_table("client_merges")
