"""Per-trainer Telegram push window (Europe/Minsk hours); NULL = platform default 8–22."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0115_trainer_push_window"
down_revision = "0114_booking_wrapup_ts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainers",
        sa.Column("push_notification_start_hour", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "trainers",
        sa.Column("push_notification_end_hour", sa.SmallInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainers", "push_notification_end_hour")
    op.drop_column("trainers", "push_notification_start_hour")
