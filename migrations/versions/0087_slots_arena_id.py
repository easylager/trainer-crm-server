"""Slots: optional arena_id — venue fixed on slot (group lessons).

Revision ID: 0087
Revises: 0086
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: DB may already have arena_id (manual hotfix / partial apply).
    conn = op.get_bind()
    insp = sa.inspect(conn)
    col_names = {c["name"] for c in insp.get_columns("slots")}

    if "arena_id" not in col_names:
        op.add_column(
            "slots",
            sa.Column("arena_id", sa.Integer(), nullable=True),
        )

    insp = sa.inspect(conn)
    has_arena_fk = any(
        fk.get("constrained_columns") == ["arena_id"] for fk in insp.get_foreign_keys("slots")
    )
    if not has_arena_fk:
        op.create_foreign_key(
            "fk_slots_arena_id_arenas",
            "slots",
            "arenas",
            ["arena_id"],
            ["id"],
            ondelete="SET NULL",
        )

    insp = sa.inspect(conn)
    index_names = {ix["name"] for ix in insp.get_indexes("slots")}
    if "ix_slots_trainer_arena" not in index_names:
        op.create_index("ix_slots_trainer_arena", "slots", ["trainer_id", "arena_id"])

    op.execute(
        sa.text(
            """
            UPDATE slots s
            SET arena_id = COALESCE(
                (SELECT t.primary_arena_id FROM trainers t WHERE t.id = s.trainer_id),
                (SELECT MIN(ta.arena_id) FROM trainer_arenas ta WHERE ta.trainer_id = s.trainer_id)
            )
            WHERE s.arena_id IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_slots_trainer_arena", table_name="slots")
    op.drop_constraint("fk_slots_arena_id_arenas", "slots", type_="foreignkey")
    op.drop_column("slots", "arena_id")
