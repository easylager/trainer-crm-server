"""Feature-adoption tracking (TASK-028): first use of each guided feature, per trainer.

One row per (trainer_id, feature), ever — append-only dedup via UNIQUE constraint, claimed
atomically with INSERT ... ON CONFLICT DO NOTHING. Feeds the admin "how many features has
this trainer touched" distribution.

Revision ID: 0184_feature_first_use
Revises: 0183_catalog_dismiss
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0184_feature_first_use"
down_revision = "0183_catalog_dismiss"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_feature_first_use",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("feature", sa.String(length=32), nullable=False),
        sa.Column(
            "first_used_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trainer_id", "feature", name="ux_feature_first_use_trainer_feature"),
    )


def downgrade() -> None:
    op.drop_table("trainer_feature_first_use")
