"""Drop trainer_daily_request_reminder_sent (replaced by trainer_digest_sent + morning digest loop).

Removed in 0118: ``run_daily_request_reminder_loop`` and its once-per-2-days throttle log.
The morning digest loop now surfaces pending catalog requests as a 'lite' owed-line on days
with 0 sessions, using ``trainer_digest_sent`` for once-per-day idempotency.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0119_drop_daily_req_reminder_log"
down_revision = "0118_trainer_digest_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        op.f("ix_trainer_daily_request_reminder_sent_trainer_id"),
        table_name="trainer_daily_request_reminder_sent",
    )
    op.drop_table("trainer_daily_request_reminder_sent")


def downgrade() -> None:
    op.create_table(
        "trainer_daily_request_reminder_sent",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("sent_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_trainer_daily_request_reminder_sent_trainer_id"),
        "trainer_daily_request_reminder_sent",
        ["trainer_id"],
        unique=False,
    )
