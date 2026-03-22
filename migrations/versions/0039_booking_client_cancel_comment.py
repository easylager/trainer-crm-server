"""Add client_cancel_comment to bookings (reason when client cancels).

Revision ID: 0039_client_cancel_comment
Revises: 0038_request_trainer_id
"""
from alembic import op
import sqlalchemy as sa


revision = "0039_client_cancel_comment"
down_revision = "0038_request_trainer_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("client_cancel_comment", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bookings", "client_cancel_comment")
