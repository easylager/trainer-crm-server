"""Trainer no-show mark for PASS/CERT without booking_problem_reports."""

from alembic import op
import sqlalchemy as sa


revision = "0102_booking_client_no_show"
down_revision = "0101_problem_policy_breach"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "booking_client_no_show",
        sa.Column("booking_id", sa.BigInteger(), nullable=False),
        sa.Column("trainer_id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("payment_class", sa.String(length=16), nullable=False),
        sa.Column("deduct_resolution", sa.String(length=16), nullable=False),
        sa.Column(
            "completed_at_submit",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="mini_app"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("booking_id"),
    )
    op.create_index(
        "ix_booking_client_no_show_trainer_id",
        "booking_client_no_show",
        ["trainer_id"],
    )
    op.create_index(
        "ix_booking_client_no_show_created_at",
        "booking_client_no_show",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_booking_client_no_show_created_at", table_name="booking_client_no_show")
    op.drop_index("ix_booking_client_no_show_trainer_id", table_name="booking_client_no_show")
    op.drop_table("booking_client_no_show")
