"""Города, созданные тренером на онбординге (TASK-170).

``cities.created_by_trainer_id`` — кто предложил город; ``is_active=false`` до
модерации. Тренер видит свой город в селекте; публичный каталог — только ``is_active``.

Revision ID: 0214_trainer_created_cities
Revises: 0213_trainer_specialist_roles
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0214_trainer_created_cities"
down_revision = "0213_trainer_specialist_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cities",
        sa.Column(
            "created_by_trainer_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_cities_created_by_trainer_id",
        "cities",
        ["created_by_trainer_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cities_created_by_trainer_id", table_name="cities")
    op.drop_column("cities", "created_by_trainer_id")
