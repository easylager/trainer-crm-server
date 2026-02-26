"""Link booking to client request and archive request when client books from it.

Revision ID: 0015_booking_request_link
Revises: 0014_request_notifications
"""
from alembic import op
import sqlalchemy as sa


revision = "0015_booking_request_link"
down_revision = "0014_request_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("client_request_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_bookings_client_request_id",
        "bookings",
        "client_requests",
        ["client_request_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_bookings_client_request_id"),
        "bookings",
        ["client_request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_bookings_client_request_id"), table_name="bookings")
    op.drop_constraint("fk_bookings_client_request_id", "bookings", type_="foreignkey")
    op.drop_column("bookings", "client_request_id")
