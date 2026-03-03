"""Add session_duration_minutes to trainer_profiles (universal session length for catalog and reminders).

Revision ID: 0027_session_duration
Revises: 0026_clients
"""
from alembic import op
import sqlalchemy as sa


revision = "0027_session_duration"
down_revision = "0026_clients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_profiles",
        sa.Column("session_duration_minutes", sa.Integer(), nullable=True, server_default="45"),
    )


def downgrade() -> None:
    op.drop_column("trainer_profiles", "session_duration_minutes")
