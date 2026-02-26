"""Add cities table, city_id to trainer_profiles, selected_service_id to client_sessions.

Revision ID: 0009_cities_service
Revises: 0008_client_sessions
"""
from alembic import op
import sqlalchemy as sa


revision = "0009_cities_service"
down_revision = "0008_client_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cities_sort_order"), "cities", ["sort_order"], unique=False)

    op.add_column(
        "trainer_profiles",
        sa.Column("city_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_trainer_profiles_city_id",
        "trainer_profiles",
        "cities",
        ["city_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_client_sessions_city_id",
        "client_sessions",
        "cities",
        ["city_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "client_sessions",
        sa.Column("selected_service_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_client_sessions_selected_service_id",
        "client_sessions",
        "services",
        ["selected_service_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_client_sessions_selected_service_id", "client_sessions", type_="foreignkey")
    op.drop_column("client_sessions", "selected_service_id")
    op.drop_constraint("fk_client_sessions_city_id", "client_sessions", type_="foreignkey")
    op.drop_constraint("fk_trainer_profiles_city_id", "trainer_profiles", type_="foreignkey")
    op.drop_column("trainer_profiles", "city_id")
    op.drop_index(op.f("ix_cities_sort_order"), table_name="cities")
    op.drop_table("cities")
