"""Add optional trainer_id to client_requests for personalized requests.

Revision ID: 0038_request_trainer_id
Revises: 0037_client_inactive
"""
from alembic import op
import sqlalchemy as sa


revision = "0038_request_trainer_id"
down_revision = "0037_client_inactive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_requests",
        sa.Column("trainer_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_client_requests_trainer_id",
        "client_requests",
        "trainers",
        ["trainer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_client_requests_trainer_id"),
        "client_requests",
        ["trainer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_client_requests_trainer_id"), table_name="client_requests")
    op.drop_constraint("fk_client_requests_trainer_id", "client_requests", type_="foreignkey")
    op.drop_column("client_requests", "trainer_id")
