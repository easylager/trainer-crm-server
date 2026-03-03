"""Add trainer_comment to client_request_responses (optional message to client).

Revision ID: 0030_response_comment
Revises: 0029_declines
"""
from alembic import op
import sqlalchemy as sa


revision = "0030_response_comment"
down_revision = "0029_declines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_request_responses",
        sa.Column("trainer_comment", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("client_request_responses", "trainer_comment")
