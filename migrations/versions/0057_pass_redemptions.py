"""Add pass_redemptions: history of pass session redemptions per booking."""

from alembic import op
import sqlalchemy as sa


revision = "0057_pass_redemptions"
down_revision = "0056_certificate_instances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pass_redemptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("pass_instance_id", sa.Integer(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pass_instance_id"], ["pass_instances.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("booking_id", name="uq_pass_redemptions_booking_id"),
    )
    op.create_index("ix_pass_redemptions_booking_id", "pass_redemptions", ["booking_id"], unique=True)
    op.create_index("ix_pass_redemptions_pass_instance_id", "pass_redemptions", ["pass_instance_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pass_redemptions_pass_instance_id", table_name="pass_redemptions")
    op.drop_index("ix_pass_redemptions_booking_id", table_name="pass_redemptions")
    op.drop_table("pass_redemptions")
