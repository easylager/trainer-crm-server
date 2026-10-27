"""Admin-managed schedule source per arena: link, how we collect it, when the rink posts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0276_arena_schedule_sources"
down_revision = "0275_admin_trainer_contacts"
branch_labels = None
depends_on = None

_MODES = ("server", "byip", "manual", "none")


def upgrade() -> None:
    op.create_table(
        "arena_schedule_sources",
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_url", sa.String(512), nullable=True),
        sa.Column("source_kind", sa.String(16), nullable=True),
        sa.Column("fetch_mode", sa.String(16), nullable=False),
        sa.Column(
            "publish_days",
            postgresql.ARRAY(sa.SmallInteger()),
            nullable=False,
            server_default=sa.text("'{}'::smallint[]"),
        ),
        sa.Column("remind", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            f"fetch_mode IN ({', '.join(repr(m) for m in _MODES)})", name="ck_arena_schedule_sources_mode"
        ),
    )


def downgrade() -> None:
    op.drop_table("arena_schedule_sources")
