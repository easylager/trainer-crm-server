"""Add vk_user_id for MAX / VK Mini Apps linkage (parallel to telegram_id)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0134_vk_user_id_clients_trainers"
down_revision = "0133_notify_when_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("vk_user_id", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_clients_vk_user_id", "clients", ["vk_user_id"], unique=True)

    op.add_column(
        "trainers",
        sa.Column("vk_user_id", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_trainers_vk_user_id", "trainers", ["vk_user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_trainers_vk_user_id", table_name="trainers")
    op.drop_column("trainers", "vk_user_id")
    op.drop_index("ix_clients_vk_user_id", table_name="clients")
    op.drop_column("clients", "vk_user_id")
