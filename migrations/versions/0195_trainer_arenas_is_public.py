"""trainer_arenas.is_public: vitrine vs schedule eligibility (TASK-057).

Existing links stay public (DEFAULT true). New auto-created schedule links
set is_public=false in application code.

Revision ID: 0195_trainer_arenas_is_public
Revises: 0194_ice_sessions
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0195_trainer_arenas_is_public"
down_revision = "0194_ice_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_arenas",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("trainer_arenas", "is_public")
