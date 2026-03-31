"""Client inactive notifications: 10-day and 30-day 'we miss you' push (once per client per kind).

Revision ID: 0037_client_inactive
Revises: 0036_trainer_min_hours
"""

from alembic import op
import sqlalchemy as sa


revision = "0037_client_inactive"
down_revision = "0036_trainer_min_hours"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_inactive_notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),  # '10_days' | '30_days'
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "kind", name="uq_client_inactive_client_kind"),
    )
    op.create_index(
        op.f("ix_client_inactive_notifications_client_id"),
        "client_inactive_notifications",
        ["client_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_client_inactive_notifications_client_id"),
        table_name="client_inactive_notifications",
    )
    op.drop_table("client_inactive_notifications")
