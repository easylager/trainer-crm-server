"""Client requests: city + service + comment when client leaves demand (no trainer found).

Revision ID: 0012_client_requests
Revises: 0011_bookings
"""
from alembic import op
import sqlalchemy as sa


revision = "0012_client_requests"
down_revision = "0011_bookings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_client_requests_client_telegram_id"), "client_requests", ["client_telegram_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_client_requests_client_telegram_id"), table_name="client_requests")
    op.drop_table("client_requests")
