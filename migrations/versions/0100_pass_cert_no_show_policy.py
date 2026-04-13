"""Trainer pass/certificate no-show policy (P1/P2) + audit snapshot on problem reports."""

from alembic import op
import sqlalchemy as sa


revision = "0100_pass_cert_no_show_policy"
down_revision = "0099_booking_problem_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_profiles",
        sa.Column(
            "pass_cert_no_show_policy",
            sa.String(length=16),
            nullable=False,
            server_default="redeem",
        ),
    )
    op.add_column(
        "booking_problem_reports",
        sa.Column("pass_cert_no_show_policy_snapshot", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("booking_problem_reports", "pass_cert_no_show_policy_snapshot")
    op.drop_column("trainer_profiles", "pass_cert_no_show_policy")
