"""Add certificate_instances: issued certificates with code (trainer issues, client redeems)."""

from alembic import op
import sqlalchemy as sa


revision = "0056_certificate_instances"
down_revision = "0055_pass_instances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "certificate_instances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("certificate_product_id", sa.Integer(), nullable=True),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("recipient_name", sa.Text(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["certificate_product_id"], ["trainer_certificate_products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_certificate_instances_trainer_id", "certificate_instances", ["trainer_id"], unique=False)
    op.create_index("ix_certificate_instances_client_id", "certificate_instances", ["client_id"], unique=False)
    op.create_index("uq_certificate_instances_code", "certificate_instances", ["code"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_certificate_instances_code", table_name="certificate_instances")
    op.drop_index("ix_certificate_instances_client_id", table_name="certificate_instances")
    op.drop_index("ix_certificate_instances_trainer_id", table_name="certificate_instances")
    op.drop_table("certificate_instances")
