"""Group slots: optional service_id on slots and schedule templates.

Revision ID: 0086
Revises: 0085
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0086"
down_revision = "0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "slots",
        sa.Column("service_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_slots_service_id_services",
        "slots",
        "services",
        ["service_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_slots_trainer_service", "slots", ["trainer_id", "service_id"])

    op.add_column(
        "trainer_schedule_templates",
        sa.Column("service_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_trainer_schedule_templates_service_id_services",
        "trainer_schedule_templates",
        "services",
        ["service_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_trainer_schedule_templates_service_id_services",
        "trainer_schedule_templates",
        type_="foreignkey",
    )
    op.drop_column("trainer_schedule_templates", "service_id")

    op.drop_index("ix_slots_trainer_service", table_name="slots")
    op.drop_constraint("fk_slots_service_id_services", "slots", type_="foreignkey")
    op.drop_column("slots", "service_id")
