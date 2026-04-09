"""Schedule template rows: optional arena_id for group slots.

Revision ID: 0089
Revises: 0088
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_schedule_templates",
        sa.Column("arena_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_trainer_schedule_templates_arena_id_arenas",
        "trainer_schedule_templates",
        "arenas",
        ["arena_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_trainer_schedule_templates_arena_id_arenas",
        "trainer_schedule_templates",
        type_="foreignkey",
    )
    op.drop_column("trainer_schedule_templates", "arena_id")
