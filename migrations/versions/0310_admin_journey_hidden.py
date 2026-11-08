"""Admin hides a trainer from the «Путь тренеров» list (the trainer is untouched).

A pure list-hygiene mark, same shape as ``admin_trainer_contacts``: one row = hidden for the admin list.

Revision ID: 0310_admin_journey_hidden
Revises: 0309_review_moderation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0310_admin_journey_hidden"
down_revision = "0309_review_moderation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_trainer_journey_hidden",
        sa.Column("trainer_id", sa.Integer(), sa.ForeignKey("trainers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("hidden_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("admin_trainer_journey_hidden")
