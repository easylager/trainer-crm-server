"""Add source_certificate_instance_id to pass_instances and amount_remaining_cents to certificate_instances."""

from alembic import op
import sqlalchemy as sa


revision = "0062_pass_instance_source"
down_revision = "0061_certificate_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PassInstance: link back to certificate, if pass created from certificate
    op.add_column(
        "pass_instances",
        sa.Column("source_certificate_instance_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_pass_instances_source_certificate_instance_id",
        "pass_instances",
        ["source_certificate_instance_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_pass_instances_source_certificate_instance_id",
        "pass_instances",
        "certificate_instances",
        ["source_certificate_instance_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # CertificateInstance: remaining balance for monetary certificates
    op.add_column(
        "certificate_instances",
        sa.Column("amount_remaining_cents", sa.Integer(), nullable=True),
    )
    # Initialize remaining balance = amount_cents for existing rows
    op.execute("UPDATE certificate_instances SET amount_remaining_cents = amount_cents")


def downgrade() -> None:
    # CertificateInstance rollback
    op.drop_column("certificate_instances", "amount_remaining_cents")

    # PassInstance rollback
    op.drop_constraint(
        "fk_pass_instances_source_certificate_instance_id",
        "pass_instances",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_pass_instances_source_certificate_instance_id",
        table_name="pass_instances",
    )
    op.drop_column("pass_instances", "source_certificate_instance_id")

