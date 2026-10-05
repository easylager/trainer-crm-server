"""Несколько ролей специалиста (TASK-169).

``trainer_profiles.specialist_roles`` — JSON-массив строк; ``specialist_role``
остаётся кэшем для каталога («Тренер · ОФП-тренер»), расширен до 200 символов.

Revision ID: 0213_trainer_specialist_roles
Revises: 0212_catalog_consumer_events
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0213_trainer_specialist_roles"
down_revision = "0212_catalog_consumer_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_profiles",
        sa.Column("specialist_roles", JSONB, nullable=True),
    )
    op.execute(
        """
        UPDATE trainer_profiles
        SET specialist_roles = jsonb_build_array(specialist_role)
        WHERE specialist_role IS NOT NULL AND specialist_role <> ''
        """
    )
    op.alter_column(
        "trainer_profiles",
        "specialist_role",
        existing_type=sa.String(64),
        type_=sa.String(200),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "trainer_profiles",
        "specialist_role",
        existing_type=sa.String(200),
        type_=sa.String(64),
        existing_nullable=True,
    )
    op.drop_column("trainer_profiles", "specialist_roles")
