"""TASK-213: arena follows and the notification outbox.

Revision ID: 0225_arena_follows
Revises: 0224_hockey_practice_kind
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0225_arena_follows"
down_revision = "0224_hockey_practice_kind"
branch_labels = None
depends_on = None

_EVENT_KINDS = (
    "'public_page_view', 'public_telegram_cta', 'miniapp_catalog_entry', "
    "'public_contact_click', 'follow_created', 'follow_notified', 'follow_removed'"
)
_EVENT_KINDS_PREVIOUS = (
    "'public_page_view', 'public_telegram_cta', 'miniapp_catalog_entry', 'public_contact_click'"
)


def upgrade() -> None:
    op.create_table(
        "arena_follows",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("muted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("telegram_id", "arena_id", name="uq_arena_follows_telegram_arena"),
        sa.CheckConstraint("source IN ('bot_start', 'miniapp')", name="ck_arena_follows_source"),
    )
    op.create_index("ix_arena_follows_arena_id", "arena_follows", ["arena_id"])

    op.create_table(
        "arena_follow_notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "follow_id",
            sa.BigInteger(),
            sa.ForeignKey("arena_follows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "kind IN ('schedule_changed', 'reopened')",
            name="ck_arena_follow_notifications_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed', 'muted', 'merged')",
            name="ck_arena_follow_notifications_status",
        ),
    )
    op.create_index(
        "ix_arena_follow_notifications_due",
        "arena_follow_notifications",
        ["status", "not_before"],
    )
    op.create_index(
        "uq_arena_follow_notifications_one_pending",
        "arena_follow_notifications",
        ["follow_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.drop_constraint("ck_catalog_consumer_events_kind", "catalog_consumer_events", type_="check")
    op.create_check_constraint(
        "ck_catalog_consumer_events_kind",
        "catalog_consumer_events",
        f"kind IN ({_EVENT_KINDS})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_catalog_consumer_events_kind", "catalog_consumer_events", type_="check")
    op.create_check_constraint(
        "ck_catalog_consumer_events_kind",
        "catalog_consumer_events",
        f"kind IN ({_EVENT_KINDS_PREVIOUS})",
    )
    op.drop_index("uq_arena_follow_notifications_one_pending", table_name="arena_follow_notifications")
    op.drop_index("ix_arena_follow_notifications_due", table_name="arena_follow_notifications")
    op.drop_table("arena_follow_notifications")
    op.drop_index("ix_arena_follows_arena_id", table_name="arena_follows")
    op.drop_table("arena_follows")
