"""Lead Mode recovery: idempotency log for D+0..D+30 reactivation nudges.

One row per (trainer_id, step) — append-only, used purely as a dedup boundary so the recovery
loop never sends the same step twice. Cancel-on-payment is implicit: once a trainer leaves
LEAD_MODE, the loop simply stops listing them as candidates, and remaining steps are never inserted.

Revision ID: 0125_recovery_nudges
Revises: 0124_demand_events
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa


revision = "0125_recovery_nudges"
down_revision = "0124_demand_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_recovery_nudges",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        # step: 'd0' | 'd3' | 'd14' | 'd30' — open string, validated in app layer.
        sa.Column("step", sa.String(8), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Anchor: last_subscription_expires_at at the moment the step was sent. Lets us audit
        # why this step fired (e.g., "27 days into lead mode").
        sa.Column("expires_at_anchor", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Idempotency boundary — one step per trainer, ever.
    op.create_index(
        "ux_recovery_nudges_trainer_step",
        "trainer_recovery_nudges",
        ["trainer_id", "step"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_recovery_nudges_trainer_step", table_name="trainer_recovery_nudges")
    op.drop_table("trainer_recovery_nudges")
