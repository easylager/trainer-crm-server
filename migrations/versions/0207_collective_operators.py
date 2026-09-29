"""Collective operators: org bot ownership, separate from coach trainer_id (TASK-141/EPIC5 TASK-105)."""

from alembic import op
import sqlalchemy as sa

revision = "0207_collective_operators"
down_revision = "0206_trainer_catalog_state"
branch_labels = None
depends_on = None

OPERATOR_ROLES = ("owner", "admin")
OPERATOR_STATUSES = ("active", "removed")


def upgrade() -> None:
    op.create_table(
        "collective_operators",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "collective_id",
            sa.Integer(),
            sa.ForeignKey("collectives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("collective_id", "telegram_id", name="uq_collective_operators_pair"),
        sa.CheckConstraint("role IN ('owner', 'admin')", name="ck_collective_operators_role"),
        sa.CheckConstraint("status IN ('active', 'removed')", name="ck_collective_operators_status"),
    )
    op.create_index("ix_collective_operators_collective_id", "collective_operators", ["collective_id"])
    op.create_index("ix_collective_operators_telegram_id", "collective_operators", ["telegram_id"])


def downgrade() -> None:
    op.drop_table("collective_operators")
