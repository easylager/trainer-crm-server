"""Add pass_instances: client-owned pass (issued by trainer after external payment)."""

from alembic import op
import sqlalchemy as sa


revision = "0055_pass_instances"
down_revision = "0054_fix_cities_arenas_sequences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pass_instances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("pass_product_id", sa.Integer(), nullable=False),
        sa.Column("sessions_remaining", sa.Integer(), nullable=False),
        sa.Column("sessions_total", sa.Integer(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pass_product_id"], ["trainer_pass_products.id"], ondelete="RESTRICT"),
    )
    op.create_index(op.f("ix_pass_instances_client_id"), "pass_instances", ["client_id"], unique=False)
    op.create_index(op.f("ix_pass_instances_pass_product_id"), "pass_instances", ["pass_product_id"], unique=False)
    op.create_index(op.f("ix_pass_instances_status"), "pass_instances", ["status"], unique=False)
    op.create_index(
        op.f("ix_pass_instances_client_status"),
        "pass_instances",
        ["client_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pass_instances_client_status"), table_name="pass_instances")
    op.drop_index(op.f("ix_pass_instances_status"), table_name="pass_instances")
    op.drop_index(op.f("ix_pass_instances_pass_product_id"), table_name="pass_instances")
    op.drop_index(op.f("ix_pass_instances_client_id"), table_name="pass_instances")
    op.drop_table("pass_instances")
