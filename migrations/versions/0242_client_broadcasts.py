"""Клиентские рассылки: лог отправки и отписка от прогноза льда.

Revision ID: 0242_client_broadcasts
Revises: 0241_ice_company_core
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0242_client_broadcasts"
down_revision = "0241_ice_company_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_broadcast_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_key", sa.String(length=64), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('sent', 'failed')",
            name="ck_client_broadcast_log_status",
        ),
        sa.UniqueConstraint(
            "telegram_id",
            "campaign_key",
            name="uq_client_broadcast_log_telegram_campaign",
        ),
    )
    op.create_index(
        "ix_client_broadcast_log_campaign",
        "client_broadcast_log",
        ["campaign_key"],
    )
    op.create_table(
        "client_broadcast_optouts",
        sa.Column("telegram_id", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('ice_forecast')",
            name="ck_client_broadcast_optouts_kind",
        ),
    )


def downgrade() -> None:
    op.drop_table("client_broadcast_optouts")
    op.drop_index("ix_client_broadcast_log_campaign", table_name="client_broadcast_log")
    op.drop_table("client_broadcast_log")
