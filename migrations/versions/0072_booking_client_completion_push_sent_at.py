"""bookings.client_booking_completed_push_sent_at — retry Telegram push if send failed after auto-complete.

Revision ID: 0072_client_completion_push
Revises: 0071_cert_booking_credits
"""
from alembic import op
import sqlalchemy as sa

revision = "0072_client_completion_push"
down_revision = "0071_cert_booking_credits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column(
            "client_booking_completed_push_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Historical rows: assume client completion push was already attempted before this column existed.
    op.execute(
        """
        UPDATE bookings
        SET client_booking_completed_push_sent_at = CURRENT_TIMESTAMP
        WHERE status = 'completed' AND client_booking_completed_push_sent_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("bookings", "client_booking_completed_push_sent_at")
