"""Add client_request_declines: trainer declined request, hidden from their list.

Revision ID: 0029_declines
Revises: 0028_seed_services
"""
from alembic import op
import sqlalchemy as sa


revision = "0029_declines"
down_revision = "0028_seed_services"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_request_declines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_request_id", sa.Integer(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["client_request_id"], ["client_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_request_id", "trainer_id", name="uq_request_decline_trainer"),
    )
    op.create_index(
        op.f("ix_client_request_declines_client_request_id"),
        "client_request_declines",
        ["client_request_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_client_request_declines_trainer_id"),
        "client_request_declines",
        ["trainer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_client_request_declines_trainer_id"), table_name="client_request_declines")
    op.drop_index(op.f("ix_client_request_declines_client_request_id"), table_name="client_request_declines")
    op.drop_table("client_request_declines")
