"""Optional per-trainer-per-service description (trainer_services.description).

Revision ID: 0091
Revises: 0090
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0091"
down_revision = "0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_services",
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_services", "description")
