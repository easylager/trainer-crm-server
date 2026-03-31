"""Add telegram_username to clients.

Revision ID: 0048_client_telegram_username
Revises: 0047_trainer_client_notes
"""
from alembic import op
import sqlalchemy as sa


revision = "0048_client_telegram_username"
down_revision = "0047_trainer_client_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
  op.add_column("clients", sa.Column("telegram_username", sa.String(length=64), nullable=True))
  op.create_index(
      "ix_clients_telegram_username",
      "clients",
      ["telegram_username"],
      unique=False,
  )


def downgrade() -> None:
  op.drop_index("ix_clients_telegram_username", table_name="clients")
  op.drop_column("clients", "telegram_username")

