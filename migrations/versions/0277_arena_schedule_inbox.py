"""Admin inbox: schedule screenshots uploaded from the phone, parsed and published after approval."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0277_arena_schedule_inbox"
down_revision = "0276_arena_schedule_sources"
branch_labels = None
depends_on = None

_STATUSES = ("pending", "parsed", "published", "rejected")


def upgrade() -> None:
    op.create_table(
        "arena_schedule_inbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_key", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("parsed", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_count", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in _STATUSES)})", name="ck_arena_schedule_inbox_status"
        ),
    )
    op.create_index("ix_arena_schedule_inbox_status", "arena_schedule_inbox", ["status", "uploaded_at"])


def downgrade() -> None:
    op.drop_index("ix_arena_schedule_inbox_status", table_name="arena_schedule_inbox")
    op.drop_table("arena_schedule_inbox")
