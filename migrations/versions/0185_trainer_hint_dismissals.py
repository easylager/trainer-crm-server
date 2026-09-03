"""Server-side «Не сейчас» for hub rhythm hints (TASK-029).

One row per (trainer_id, hint_id), upserted — dismissing the same hint again after it
returned moves snooze_until forward. Replaces the client-only localStorage snooze so the
answer survives a device change / cache clear and is visible to push cycles.

Revision ID: 0185_hint_dismissals
Revises: 0184_feature_first_use
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0185_hint_dismissals"
down_revision = "0184_feature_first_use"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_hint_dismissals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("hint_id", sa.String(length=32), nullable=False),
        sa.Column(
            "dismissed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trainer_id", "hint_id", name="ux_hint_dismissals_trainer_hint"),
    )


def downgrade() -> None:
    op.drop_table("trainer_hint_dismissals")
