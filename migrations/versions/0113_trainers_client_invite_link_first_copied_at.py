"""Trainer: first time they copied a client-facing invite/booking link (activation funnel)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0113_invite_copy_ts"
down_revision = "0112_zamok_hourly_15_from_1015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainers",
        sa.Column("client_invite_link_first_copied_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainers", "client_invite_link_first_copied_at")
