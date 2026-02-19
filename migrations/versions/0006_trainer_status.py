"""Add trainer status: pending_profile, pending_contract, pending_payment, active, deactivated.

Revision ID: 0006_trainer_status
Revises: 0005_profile_name_age
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_trainer_status"
down_revision = "0005_profile_name_age"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainers",
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_profile"),
    )


def downgrade() -> None:
    op.drop_column("trainers", "status")
