"""booking_completed_notifications.client_telegram_id nullable for clients without Telegram."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0116_bc_notif_null_client_tg"
down_revision = "0115_trainer_push_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "booking_completed_notifications",
        "client_telegram_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM booking_completed_notifications
        WHERE client_telegram_id IS NULL
        """
    )
    op.alter_column(
        "booking_completed_notifications",
        "client_telegram_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
