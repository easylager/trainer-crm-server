"""Profile enrichment nudges after first booking: tariffs / «что не входит».

One row per (trainer_id, step) — append-only dedup. Remaining steps are never sent once
the trainer has any price on a service.

Revision ID: 0181_profile_nudges
Revises: 0180_onboarding_nudges
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa


revision = "0181_profile_nudges"
down_revision = "0180_onboarding_nudges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_profile_nudges",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("step", sa.String(length=8), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trainer_id", "step", name="ux_profile_nudges_trainer_step"),
    )


def downgrade() -> None:
    op.drop_table("trainer_profile_nudges")
