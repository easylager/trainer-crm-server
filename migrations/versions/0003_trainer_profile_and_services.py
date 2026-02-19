"""Trainer profile, services catalog, trainer–services link.

Revision ID: 0003_profile_services
Revises: 0002_trainers
Create Date: trainer_profiles, services, trainer_services

"""
from alembic import op
import sqlalchemy as sa


revision = "0003_profile_services"
down_revision = "0002_trainers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Catalog of services (admin fills; trainer picks from list)
    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_services_sort_order"), "services", ["sort_order"], unique=False)

    # Trainer profile: one-to-one with trainers
    op.create_table(
        "trainer_profiles",
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("contacts", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("trainer_id"),
    )

    # Many-to-many: which services a trainer offers
    op.create_table(
        "trainer_services",
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("trainer_id", "service_id"),
    )


def downgrade() -> None:
    op.drop_table("trainer_services")
    op.drop_table("trainer_profiles")
    op.drop_index(op.f("ix_services_sort_order"), table_name="services")
    op.drop_table("services")
