"""Add optional middle_name (отчество) on clients for trainer-editable CRM identity."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0138_clients_middle_name"
down_revision = "0137_default_hour_window_6_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("middle_name", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "middle_name")
