"""Clients: telegram_id nullable, phone_normalized unique for identity by phone.

Revision ID: 0041_phone_normalized
Revises: 0040_pass_products
"""
from alembic import op
import sqlalchemy as sa


revision = "0041_phone_normalized"
down_revision = "0040_pass_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add normalized phone (digits only) for unique lookup
    op.add_column(
        "clients",
        sa.Column("phone_normalized", sa.String(32), nullable=True),
    )
    # Backfill from phone: digits only (empty -> NULL)
    op.execute("""
        UPDATE clients
        SET phone_normalized = NULLIF(trim(regexp_replace(COALESCE(phone, ''), '\\D', '', 'g')), '')
        WHERE phone IS NOT NULL AND trim(phone) <> ''
    """)
    # Unique index: one client per phone number (only where normalized is non-empty)
    op.create_index(
        "ix_clients_phone_normalized",
        "clients",
        ["phone_normalized"],
        unique=True,
        postgresql_where=sa.text("phone_normalized IS NOT NULL AND phone_normalized <> ''"),
    )
    # Allow clients without Telegram (e.g. added by trainer by phone)
    op.alter_column(
        "clients",
        "telegram_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )


def downgrade() -> None:
    # Fails if any row has telegram_id NULL (e.g. trainer-created clients)
    op.alter_column(
        "clients",
        "telegram_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.drop_index("ix_clients_phone_normalized", table_name="clients")
    op.drop_column("clients", "phone_normalized")
