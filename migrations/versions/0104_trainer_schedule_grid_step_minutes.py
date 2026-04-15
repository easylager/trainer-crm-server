"""Trainer preference for schedule start grid when primary arena has no schedule preset."""

from alembic import op
import sqlalchemy as sa


revision = "0104_trainer_schedule_grid_step"
down_revision = "0103_trainer_first_booking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainers",
        sa.Column(
            "schedule_grid_step_minutes",
            sa.SmallInteger(),
            nullable=False,
            server_default="15",
        ),
    )
    op.create_check_constraint(
        "ck_trainers_schedule_grid_step_minutes",
        "trainers",
        "schedule_grid_step_minutes IN (10, 15, 30, 60)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_trainers_schedule_grid_step_minutes", "trainers", type_="check")
    op.drop_column("trainers", "schedule_grid_step_minutes")
