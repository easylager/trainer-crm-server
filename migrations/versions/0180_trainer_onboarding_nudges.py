"""Onboarding reactivation: idempotency log for D+1/D+3/D+7 nudges to stalled onboarding.

One row per (trainer_id, step) — append-only, used purely as a dedup boundary so the reactivation
loop never sends the same step twice. Implicit cancel-on-progress: once a trainer leaves the
onboarding segment (submits profile / gets their first booking), the loop stops listing them as a
candidate, and remaining steps are never inserted.

Revision ID: 0180_onboarding_nudges
Revises: 0179_moderation_ready_notify
Create Date: 2026-08-31
"""
from alembic import op
import sqlalchemy as sa


revision = "0180_onboarding_nudges"
down_revision = "0179_moderation_ready_notify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_onboarding_nudges",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        # step: 'd1' | 'd3' | 'd7' — open string, validated in app layer.
        sa.Column("step", sa.String(8), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Stage id at the moment the step was sent — audit which nudge copy the trainer received.
        sa.Column("stage_anchor", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Idempotency boundary — one step per trainer, ever.
    op.create_index(
        "ux_onboarding_nudges_trainer_step",
        "trainer_onboarding_nudges",
        ["trainer_id", "step"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_onboarding_nudges_trainer_step", table_name="trainer_onboarding_nudges")
    op.drop_table("trainer_onboarding_nudges")
