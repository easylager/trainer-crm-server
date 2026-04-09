"""Per-row capacity on weekly schedule template (group vs individual hours).

Revision ID: 0085
Revises: 0084
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_schedule_templates",
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("trainer_schedule_templates", "capacity")
