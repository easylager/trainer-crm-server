"""TASK-187: unique parser-owned slots per arena/start/kind."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0218_ice_sessions_parser_unique"
down_revision = "0217_catalog_consumer_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_ice_sessions_parser_slot",
        "ice_sessions",
        ["arena_id", "starts_at_utc", "kind"],
        unique=True,
        postgresql_where=sa.text(
            "source_id IS NOT NULL AND source_id <> 'admin' AND source_id NOT LIKE 'etalon_%'"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_ice_sessions_parser_slot", table_name="ice_sessions")
