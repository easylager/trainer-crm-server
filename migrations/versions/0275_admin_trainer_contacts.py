"""Admin marks «написали» on a trainer in the journey list."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0275_admin_trainer_contacts"
down_revision = "0274_manual_schedule_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_trainer_contacts",
        sa.Column("trainer_id", sa.Integer(), sa.ForeignKey("trainers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("contacted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("admin_trainer_contacts")
