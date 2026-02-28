"""Introduce clients table; bookings and client_requests reference client_id.

Revision ID: 0026_clients
Revises: 0025_booking_completed_reviews
"""
from alembic import op
import sqlalchemy as sa


revision = "0026_clients"
down_revision = "0025_booking_completed_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("first_name", sa.String(64), nullable=True),
        sa.Column("last_name", sa.String(64), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_clients_telegram_id"), "clients", ["telegram_id"], unique=True)

    # Add nullable client_id to bookings and client_requests
    op.add_column(
        "bookings",
        sa.Column("client_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "client_requests",
        sa.Column("client_id", sa.Integer(), nullable=True),
    )

    # Backfill: one client per distinct client_telegram_id from bookings (with one phone)
    op.execute("""
        INSERT INTO clients (telegram_id, phone)
        SELECT DISTINCT ON (b.client_telegram_id) b.client_telegram_id, b.client_phone
        FROM bookings b
        ORDER BY b.client_telegram_id, b.id
        ON CONFLICT (telegram_id) DO NOTHING
    """)
    # Clients from client_requests that have no booking
    op.execute("""
        INSERT INTO clients (telegram_id)
        SELECT DISTINCT r.client_telegram_id FROM client_requests r
        WHERE NOT EXISTS (SELECT 1 FROM clients c WHERE c.telegram_id = r.client_telegram_id)
        ON CONFLICT (telegram_id) DO NOTHING
    """)
    # Link bookings and client_requests to clients
    op.execute("""
        UPDATE bookings b SET client_id = c.id FROM clients c WHERE c.telegram_id = b.client_telegram_id
    """)
    op.execute("""
        UPDATE client_requests r SET client_id = c.id FROM clients c WHERE c.telegram_id = r.client_telegram_id
    """)

    op.alter_column(
        "bookings", "client_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "client_requests", "client_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_bookings_client_id", "bookings", "clients",
        ["client_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index(op.f("ix_bookings_client_id"), "bookings", ["client_id"], unique=False)
    op.create_foreign_key(
        "fk_client_requests_client_id", "client_requests", "clients",
        ["client_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index(op.f("ix_client_requests_client_id"), "client_requests", ["client_id"], unique=False)

    op.drop_index(op.f("ix_bookings_client_telegram_id"), table_name="bookings")
    op.drop_column("bookings", "client_telegram_id")
    op.drop_column("bookings", "client_phone")

    op.drop_index(op.f("ix_client_requests_client_telegram_id"), table_name="client_requests")
    op.drop_column("client_requests", "client_telegram_id")


def downgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("client_telegram_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("client_phone", sa.String(32), nullable=True),
    )
    op.add_column(
        "client_requests",
        sa.Column("client_telegram_id", sa.BigInteger(), nullable=True),
    )

    op.execute("UPDATE bookings b SET client_telegram_id = c.telegram_id, client_phone = COALESCE(c.phone, '') FROM clients c WHERE c.id = b.client_id")
    op.execute("UPDATE client_requests r SET client_telegram_id = c.telegram_id FROM clients c WHERE c.id = r.client_id")

    op.alter_column("bookings", "client_telegram_id", nullable=False)
    op.alter_column("bookings", "client_phone", nullable=False)
    op.alter_column("client_requests", "client_telegram_id", nullable=False)

    op.drop_constraint("fk_bookings_client_id", "bookings", type_="foreignkey")
    op.drop_index(op.f("ix_bookings_client_id"), table_name="bookings")
    op.drop_column("bookings", "client_id")

    op.drop_constraint("fk_client_requests_client_id", "client_requests", type_="foreignkey")
    op.drop_index(op.f("ix_client_requests_client_id"), table_name="client_requests")
    op.drop_column("client_requests", "client_id")

    op.create_index(op.f("ix_bookings_client_telegram_id"), "bookings", ["client_telegram_id"], unique=False)
    op.create_index(op.f("ix_client_requests_client_telegram_id"), "client_requests", ["client_telegram_id"], unique=False)

    op.drop_index(op.f("ix_clients_telegram_id"), table_name="clients")
    op.drop_table("clients")
