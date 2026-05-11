"""Trainer pass products: multiple services via junction table (empty = all services).

Revision ID: 0147_pass_product_multi_service
Revises: 0146_recurring_materialization
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0147_pass_product_multi_service"
down_revision = "0146_recurring_materialization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_pass_product_services",
        sa.Column("pass_product_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["pass_product_id"],
            ["trainer_pass_products.id"],
            name="fk_tpp_services_pass_product",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            name="fk_tpp_services_service",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("pass_product_id", "service_id"),
    )
    op.create_index(
        "ix_tpp_services_pass_product_id",
        "trainer_pass_product_services",
        ["pass_product_id"],
        unique=False,
    )
    op.create_index(
        "ix_tpp_services_service_id",
        "trainer_pass_product_services",
        ["service_id"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO trainer_pass_product_services (pass_product_id, service_id)
        SELECT id, service_id FROM trainer_pass_products WHERE service_id IS NOT NULL
        """
    )

    op.drop_constraint(
        "trainer_pass_products_service_id_fkey",
        "trainer_pass_products",
        type_="foreignkey",
    )
    op.drop_index("ix_trainer_pass_products_service_id", table_name="trainer_pass_products")
    op.drop_column("trainer_pass_products", "service_id")


def downgrade() -> None:
    op.add_column(
        "trainer_pass_products",
        sa.Column("service_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "trainer_pass_products_service_id_fkey",
        "trainer_pass_products",
        "services",
        ["service_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_trainer_pass_products_service_id",
        "trainer_pass_products",
        ["service_id"],
        unique=False,
    )

    op.execute(
        """
        UPDATE trainer_pass_products AS p
        SET service_id = x.service_id
        FROM (
            SELECT pass_product_id AS pid, MIN(service_id) AS service_id
            FROM trainer_pass_product_services
            GROUP BY pass_product_id
            HAVING COUNT(*) = 1
        ) AS x
        WHERE p.id = x.pid
        """
    )

    op.drop_index("ix_tpp_services_service_id", table_name="trainer_pass_product_services")
    op.drop_index("ix_tpp_services_pass_product_id", table_name="trainer_pass_product_services")
    op.drop_table("trainer_pass_product_services")
