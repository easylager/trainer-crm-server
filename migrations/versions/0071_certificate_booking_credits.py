"""certificate_booking_credits: amount of certificate balance applied per completed booking (accounting).

Revision ID: 0071_cert_booking_credits
Revises: 0070_trainer_sub_billing_months
"""
from alembic import op
import sqlalchemy as sa

revision = "0071_cert_booking_credits"
down_revision = "0070_trainer_sub_billing_months"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "certificate_booking_credits",
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("certificate_instance_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["certificate_instance_id"],
            ["certificate_instances.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("booking_id"),
        sa.CheckConstraint("amount_cents > 0", name="ck_certificate_booking_credits_amount_positive"),
    )
    op.create_index(
        "ix_certificate_booking_credits_certificate_instance_id",
        "certificate_booking_credits",
        ["certificate_instance_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_certificate_booking_credits_certificate_instance_id",
        table_name="certificate_booking_credits",
    )
    op.drop_table("certificate_booking_credits")
