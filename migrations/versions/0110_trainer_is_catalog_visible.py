"""trainers.is_catalog_visible: gate public catalog without new lifecycle status."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0110_trainer_is_catalog_visible"
down_revision = "0109_trainer_client_season_goal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainers",
        sa.Column(
            "is_catalog_visible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("trainers", "is_catalog_visible")
