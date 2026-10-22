"""Rink card v2: arena_profiles.visit_info (tickets, facts, services, school, passes).

Revision ID: 0257_arena_visit_info
Revises: 0256_lida_ticket_and_services
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0257_arena_visit_info"
down_revision = "0256_lida_ticket_and_services"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "arena_profiles",
        sa.Column(
            "visit_info",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("arena_profiles", "visit_info")
