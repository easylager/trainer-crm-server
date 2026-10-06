"""TASK-189: dedup_key + indexes for catalog_consumer_events.

Недельный уникальный больше не зашивает день в хэш актёра, а дедуп события
включает арену. Уникальный индекс закрывает гонку SELECT-then-INSERT.
Индексы по городу и арене — для отчёта спроса.

Revision ID: 0220_catalog_consumer_dedup
Revises: 0219_ice_sessions_parser_unique
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0220_catalog_consumer_dedup"
down_revision = "0219_ice_sessions_parser_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("catalog_consumer_events", sa.Column("dedup_key", sa.String(length=64), nullable=True))
    op.create_index(
        "uq_catalog_consumer_events_dedup_key",
        "catalog_consumer_events",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )
    op.create_index(
        "ix_catalog_consumer_events_city_occurred",
        "catalog_consumer_events",
        ["city_id", "occurred_at"],
    )
    op.create_index(
        "ix_catalog_consumer_events_arena_occurred",
        "catalog_consumer_events",
        ["arena_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_consumer_events_arena_occurred", table_name="catalog_consumer_events")
    op.drop_index("ix_catalog_consumer_events_city_occurred", table_name="catalog_consumer_events")
    op.drop_index("uq_catalog_consumer_events_dedup_key", table_name="catalog_consumer_events")
    op.drop_column("catalog_consumer_events", "dedup_key")
