"""Collective subscription pool for member entitlement merge (Wave P1)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0164_collective_subscriptions"
down_revision = "0163_collectives_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collective_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "collective_id",
            sa.Integer(),
            sa.ForeignKey("collectives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tier", sa.String(20), nullable=True),
        sa.Column(
            "modules",
            JSONB(),
            nullable=False,
            server_default=sa.text(
                "(jsonb_build_object('online', false, 'analytics', false, 'groups', false))"
            ),
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('trial', 'active', 'past_due', 'cancelled')",
            name="ck_collective_subscriptions_status",
        ),
    )
    op.create_index(
        "ix_collective_subscriptions_collective_id",
        "collective_subscriptions",
        ["collective_id"],
    )
    op.create_index(
        "ix_collective_subscriptions_expires_at",
        "collective_subscriptions",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_table("collective_subscriptions")
