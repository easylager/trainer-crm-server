"""Collective overlay foundation: studios, members, claim/invite tokens (Wave P0)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0163_collectives_foundation"
down_revision = "0162_group_classes_dflt_false"
branch_labels = None
depends_on = None

COLLECTIVE_STATUSES = ("draft", "active", "suspended")
MEMBER_ROLES = ("owner", "member")
MEMBER_STATUSES = ("invited", "active", "left")
TOKEN_KINDS = ("claim", "invite")


def upgrade() -> None:
    op.create_table(
        "collectives",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("tagline", sa.Text(), nullable=True),
        sa.Column("logo_key", sa.String(256), nullable=True),
        sa.Column("primary_arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("owner_trainer_id", sa.Integer(), sa.ForeignKey("trainers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("brand_tokens", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("seat_limit", sa.Integer(), nullable=False, server_default="5"),
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
        sa.UniqueConstraint("slug", name="uq_collectives_slug"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'suspended')",
            name="ck_collectives_status",
        ),
    )
    op.create_index("ix_collectives_owner_trainer_id", "collectives", ["owner_trainer_id"])
    op.create_index("ix_collectives_status", "collectives", ["status"])

    op.create_table(
        "collective_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "collective_id",
            sa.Integer(),
            sa.ForeignKey("collectives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trainer_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="invited"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("collective_id", "trainer_id", name="uq_collective_members_pair"),
        sa.CheckConstraint("role IN ('owner', 'member')", name="ck_collective_members_role"),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'left')",
            name="ck_collective_members_status",
        ),
    )
    op.create_index("ix_collective_members_trainer_id", "collective_members", ["trainer_id"])
    op.create_index("ix_collective_members_collective_id", "collective_members", ["collective_id"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_collective_members_one_active_per_trainer
        ON collective_members (trainer_id)
        WHERE status = 'active'
        """
    )

    op.create_table(
        "collective_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column(
            "collective_id",
            sa.Integer(),
            sa.ForeignKey("collectives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "invited_trainer_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("token", name="uq_collective_tokens_token"),
        sa.CheckConstraint("kind IN ('claim', 'invite')", name="ck_collective_tokens_kind"),
    )
    op.create_index("ix_collective_tokens_collective_id", "collective_tokens", ["collective_id"])


def downgrade() -> None:
    op.drop_table("collective_tokens")
    op.execute("DROP INDEX IF EXISTS uq_collective_members_one_active_per_trainer")
    op.drop_table("collective_members")
    op.drop_table("collectives")
