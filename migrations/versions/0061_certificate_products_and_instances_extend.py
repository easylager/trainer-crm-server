"""Extend trainer_certificate_products and certificate_instances for new certificate flow.

- Add name and expires_in_days to trainer_certificate_products.
- Add purchased_by_name, activated_client_id, expires_at, file_url to certificate_instances.
"""

from alembic import op
import sqlalchemy as sa


revision = "0061_certificate_products"
down_revision = "0060_welcome_link_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # trainer_certificate_products: name + expires_in_days
    op.add_column(
        "trainer_certificate_products",
        sa.Column("name", sa.String(length=128), nullable=False, server_default="Подарочный сертификат"),
    )
    op.add_column(
        "trainer_certificate_products",
        sa.Column("expires_in_days", sa.Integer(), nullable=True),
    )
    # Remove server_default so future inserts rely on application-level default
    op.alter_column(
        "trainer_certificate_products",
        "name",
        server_default=None,
        existing_type=sa.String(length=128),
    )

    # certificate_instances: purchased_by_name, activated_client_id, expires_at, file_url
    op.add_column(
        "certificate_instances",
        sa.Column("purchased_by_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "certificate_instances",
        sa.Column("activated_client_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "certificate_instances",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "certificate_instances",
        sa.Column("file_url", sa.String(length=512), nullable=True),
    )
    op.create_index(
        "ix_certificate_instances_activated_client_id",
        "certificate_instances",
        ["activated_client_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_certificate_instances_activated_client_id_clients",
        "certificate_instances",
        "clients",
        ["activated_client_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # certificate_instances rollback
    op.drop_constraint(
        "fk_certificate_instances_activated_client_id_clients",
        "certificate_instances",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_certificate_instances_activated_client_id",
        table_name="certificate_instances",
    )
    op.drop_column("certificate_instances", "file_url")
    op.drop_column("certificate_instances", "expires_at")
    op.drop_column("certificate_instances", "activated_client_id")
    op.drop_column("certificate_instances", "purchased_by_name")

    # trainer_certificate_products rollback
    op.drop_column("trainer_certificate_products", "expires_in_days")
    op.drop_column("trainer_certificate_products", "name")

