"""Arenas (venues) per city; slot.arena_id, client_sessions.selected_arena_id for filter.

Revision ID: 0021_arenas
Revises: 0020_booking_cancel_notifications
"""
from alembic import op
import sqlalchemy as sa


revision = "0021_arenas"
down_revision = "0020_bk_cancel_notif"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "arenas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_arenas_city_id"), "arenas", ["city_id"], unique=False)

    op.add_column("slots", sa.Column("arena_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_slots_arena_id", "slots", "arenas", ["arena_id"], ["id"], ondelete="SET NULL"
    )

    op.add_column("client_sessions", sa.Column("selected_arena_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_client_sessions_arena_id",
        "client_sessions",
        "arenas",
        ["selected_arena_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_client_sessions_arena_id", "client_sessions", type_="foreignkey")
    op.drop_column("client_sessions", "selected_arena_id")
    op.drop_constraint("fk_slots_arena_id", "slots", type_="foreignkey")
    op.drop_column("slots", "arena_id")
    op.drop_index(op.f("ix_arenas_city_id"), table_name="arenas")
    op.drop_table("arenas")
