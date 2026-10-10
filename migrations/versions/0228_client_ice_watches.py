"""Client ice watches: notify when sessions appear or schedule becomes fresh again."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0228_client_ice_watches"
down_revision = "0227_platform_services_venue"
branch_labels = None
depends_on = None

_WATCH_KINDS = ("sessions", "schedule_fresh")


def upgrade() -> None:
    op.create_table(
        "client_ice_watches",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "telegram_id",
            sa.BigInteger(),
            sa.ForeignKey("client_sessions.telegram_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("watch_kind", sa.String(32), nullable=False),
        sa.Column(
            "filter_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"watch_kind IN ({', '.join(repr(k) for k in _WATCH_KINDS)})",
            name="ck_client_ice_watches_kind",
        ),
        sa.UniqueConstraint(
            "client_id",
            "arena_id",
            "watch_kind",
            name="uq_client_ice_watch_client_arena_kind",
        ),
    )
    op.create_index(
        "ix_client_ice_watches_arena_active",
        "client_ice_watches",
        ["arena_id"],
        postgresql_where=sa.text("active = true"),
    )
    op.create_index(
        "ix_client_ice_watches_client_active",
        "client_ice_watches",
        ["client_id"],
        postgresql_where=sa.text("active = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_client_ice_watches_client_active", table_name="client_ice_watches")
    op.drop_index("ix_client_ice_watches_arena_active", table_name="client_ice_watches")
    op.drop_table("client_ice_watches")
