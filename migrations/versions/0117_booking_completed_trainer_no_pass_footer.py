"""booking_completed_notifications.trainer_no_pass_footer: merge no-pass into completed message."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0117_trainer_no_pass_footer"
down_revision = "0116_bc_notif_null_client_tg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "booking_completed_notifications",
        sa.Column(
            "trainer_no_pass_footer",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute(
        "ALTER TABLE booking_completed_notifications "
        "ALTER COLUMN trainer_no_pass_footer DROP DEFAULT"
    )


def downgrade() -> None:
    op.drop_column("booking_completed_notifications", "trainer_no_pass_footer")
