"""Client bot session: one row per telegram_id, state + city_id + selected_trainer_id + payload.

Revision ID: 0008_client_sessions
Revises: 0007_trainer_status_enum
"""
from alembic import op
import sqlalchemy as sa


revision = "0008_client_sessions"
down_revision = "0007_trainer_status_enum"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_sessions",
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="idle"),
        sa.Column("city_id", sa.Integer(), nullable=True),
        sa.Column("selected_trainer_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["selected_trainer_id"], ["trainers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("telegram_id"),
    )
    op.create_index(
        op.f("ix_client_sessions_updated_at"), "client_sessions", ["updated_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_client_sessions_updated_at"), table_name="client_sessions")
    op.drop_table("client_sessions")
