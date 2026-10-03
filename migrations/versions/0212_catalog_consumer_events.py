"""catalog_consumer_events: публичка, CTA в Telegram, вход в мини-апп каталога (North Star / C-B).

Revision ID: 0212_catalog_consumer_events
Revises: 0211_ice_source_state
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0212_catalog_consumer_events"
down_revision = "0211_ice_source_state"
branch_labels = None
depends_on = None

_KINDS = "('public_page_view', 'public_telegram_cta', 'miniapp_catalog_entry')"


def upgrade() -> None:
    op.create_table(
        "catalog_consumer_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("actor_hash", sa.String(length=64), nullable=True),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("start_param", sa.String(length=64), nullable=True),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint(f"kind IN {_KINDS}", name="ck_catalog_consumer_events_kind"),
    )
    op.create_index(
        "ix_catalog_consumer_events_occurred_at",
        "catalog_consumer_events",
        ["occurred_at"],
    )
    op.create_index(
        "ix_catalog_consumer_events_kind_occurred",
        "catalog_consumer_events",
        ["kind", "occurred_at"],
    )
    op.create_index(
        "ix_catalog_consumer_events_actor_week",
        "catalog_consumer_events",
        ["actor_hash", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_consumer_events_actor_week", table_name="catalog_consumer_events")
    op.drop_index("ix_catalog_consumer_events_kind_occurred", table_name="catalog_consumer_events")
    op.drop_index("ix_catalog_consumer_events_occurred_at", table_name="catalog_consumer_events")
    op.drop_table("catalog_consumer_events")
