"""Family access: extra Telegram accounts share one primary clients row (bookings, passes).

Revision ID: 0148_client_family_access
Revises: 0147_pass_product_multi_service
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0148_client_family_access"
down_revision = "0147_pass_product_multi_service"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_family_access_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("primary_client_id", sa.Integer(), nullable=False),
        sa.Column("member_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_username", sa.String(length=64), nullable=True),
        sa.Column("invited_by_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["primary_client_id"],
            ["clients.id"],
            name="fk_cfam_primary_client",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("member_telegram_id", name="uq_cfam_member_telegram"),
    )
    op.create_index(
        "ix_cfam_primary_client_id",
        "client_family_access_members",
        ["primary_client_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cfam_primary_client_id", table_name="client_family_access_members")
    op.drop_table("client_family_access_members")
