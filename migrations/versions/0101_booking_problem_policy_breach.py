"""Policy breach audit code on booking_problem_reports (E4 B-path skip)."""

from alembic import op
import sqlalchemy as sa


revision = "0101_problem_policy_breach"
down_revision = "0100_pass_cert_no_show_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "booking_problem_reports",
        sa.Column("policy_breach_code", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("booking_problem_reports", "policy_breach_code")
