"""Add no_response_reminder_sent_at to client_requests (remind client after 2 days if no responses).

Revision ID: 0031_no_response_reminder
Revises: 0030_response_comment
"""
from alembic import op
import sqlalchemy as sa


revision = "0031_no_response_reminder"
down_revision = "0030_response_comment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_requests",
        sa.Column("no_response_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("client_requests", "no_response_reminder_sent_at")
