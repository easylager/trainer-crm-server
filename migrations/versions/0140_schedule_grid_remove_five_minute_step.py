"""Revert optional 5-minute schedule grid: CHECK + server default back to 15-only era.

Depends on ``0139_trainers_grid_step_5`` (placeholder) so Alembic can load DBs stamped with that revision.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0140_schedule_grid_remove_five"
down_revision = "0139_trainers_grid_step_5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE trainers SET schedule_grid_step_minutes = 15 WHERE schedule_grid_step_minutes = 5"
        )
    )
    op.drop_constraint("ck_trainers_schedule_grid_step_minutes", "trainers", type_="check")
    op.create_check_constraint(
        "ck_trainers_schedule_grid_step_minutes",
        "trainers",
        "schedule_grid_step_minutes IN (10, 15, 30, 60)",
    )
    op.alter_column(
        "trainers",
        "schedule_grid_step_minutes",
        existing_type=sa.SmallInteger(),
        server_default="15",
    )


def downgrade() -> None:
    op.alter_column(
        "trainers",
        "schedule_grid_step_minutes",
        existing_type=sa.SmallInteger(),
        server_default="5",
    )
    op.drop_constraint("ck_trainers_schedule_grid_step_minutes", "trainers", type_="check")
    op.create_check_constraint(
        "ck_trainers_schedule_grid_step_minutes",
        "trainers",
        "schedule_grid_step_minutes IN (5, 10, 15, 30, 60)",
    )
