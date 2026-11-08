"""trainer_ratings: moderation of review texts (pending / approved / rejected).

A star rating counts at once (it feeds the profile aggregates); the *text* is shown publicly only
after an admin approves it. Rows that already carry a text are queued as ``pending`` so nothing
unreviewed stays visible once the public side filters on ``approved``.

Revision ID: 0309_review_moderation
Revises: 0308_hockey_skating_summary
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0309_review_moderation"
down_revision = "0308_hockey_skating_summary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trainer_ratings", sa.Column("review_status", sa.String(length=16), nullable=True))
    op.add_column("trainer_ratings", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("trainer_ratings", sa.Column("reviewed_by", sa.BigInteger(), nullable=True))
    op.execute(
        "UPDATE trainer_ratings SET review_status = 'pending' "
        "WHERE review_text IS NOT NULL AND btrim(review_text) <> ''"
    )
    op.create_index("ix_trainer_ratings_trainer_review", "trainer_ratings", ["trainer_id", "review_status"])


def downgrade() -> None:
    op.drop_index("ix_trainer_ratings_trainer_review", table_name="trainer_ratings")
    op.drop_column("trainer_ratings", "reviewed_by")
    op.drop_column("trainer_ratings", "reviewed_at")
    op.drop_column("trainer_ratings", "review_status")
