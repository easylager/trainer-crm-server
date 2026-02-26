"""Request/response notifications: notify trainers about new requests, clients about new responses.

Revision ID: 0014_request_notifications
Revises: 0013_client_request_responses
"""
from alembic import op
import sqlalchemy as sa


revision = "0014_request_notifications"
down_revision = "0013_client_request_responses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_request_notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_request_id", sa.Integer(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["client_request_id"], ["client_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_request_id", "trainer_id", name="uq_request_notif_trainer"),
    )
    op.create_index(
        op.f("ix_client_request_notifications_trainer_id"),
        "client_request_notifications",
        ["trainer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_client_request_notifications_client_request_id"),
        "client_request_notifications",
        ["client_request_id"],
        unique=False,
    )
    op.add_column(
        "client_request_responses",
        sa.Column("client_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("client_request_responses", "client_notified_at")
    op.drop_index(op.f("ix_client_request_notifications_client_request_id"), table_name="client_request_notifications")
    op.drop_index(op.f("ix_client_request_notifications_trainer_id"), table_name="client_request_notifications")
    op.drop_table("client_request_notifications")
