"""booking_problem_reports audit + clients.problematic flag."""

from alembic import op
import sqlalchemy as sa


revision = "0099_booking_problem_reports"
down_revision = "0098_ts_group_price_cents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("problematic", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_table(
        "booking_problem_reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.BigInteger(), nullable=False),
        sa.Column("trainer_id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("preset_id", sa.String(length=32), nullable=False),
        sa.Column("payment_class", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="mini_app"),
        sa.Column("blacklist_candidate", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id", name="uq_booking_problem_reports_booking_id"),
    )
    op.create_index("ix_booking_problem_reports_trainer_id", "booking_problem_reports", ["trainer_id"])
    op.create_index("ix_booking_problem_reports_client_id", "booking_problem_reports", ["client_id"])
    op.create_index("ix_booking_problem_reports_created_at", "booking_problem_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_booking_problem_reports_created_at", table_name="booking_problem_reports")
    op.drop_index("ix_booking_problem_reports_client_id", table_name="booking_problem_reports")
    op.drop_index("ix_booking_problem_reports_trainer_id", table_name="booking_problem_reports")
    op.drop_table("booking_problem_reports")
    op.drop_column("clients", "problematic")
