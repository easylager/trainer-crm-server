"""Компания на лёд: ядро без порога, confirmed, напоминаний.

Revision ID: 0241_ice_company_core
Revises: 0240_ice_sales_snapshots
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0241_ice_company_core"
down_revision = "0240_ice_sales_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE ice_companies SET status = 'open' WHERE status = 'confirmed'")
    op.drop_index("ix_ice_company_reminders_due", table_name="ice_company_reminders")
    op.drop_table("ice_company_reminders")

    op.drop_constraint("ck_ice_companies_status", "ice_companies", type_="check")
    op.drop_constraint("ck_ice_companies_min_people", "ice_companies", type_="check")
    op.drop_constraint("ck_ice_companies_max_people", "ice_companies", type_="check")

    op.drop_column("ice_companies", "min_people")
    op.drop_column("ice_companies", "max_people")
    op.drop_column("ice_companies", "weekly_in_chat")
    op.drop_column("ice_companies", "confirm_notified_at")
    op.drop_column("ice_companies", "schedule_notice_pending")
    op.drop_column("ice_companies", "cancel_notice_pending")

    op.create_check_constraint(
        "ck_ice_companies_status",
        "ice_companies",
        "status IN ('open', 'cancelled', 'expired')",
    )

    op.drop_column("ice_company_events", "previous_starts_at")

    op.drop_column("ice_company_responses", "attended")
    op.drop_column("ice_company_responses", "reminders_enabled")
    op.drop_column("ice_company_responses", "needs_reconfirm")
    op.drop_column("ice_company_responses", "departing")
    op.drop_column("ice_company_responses", "join_notified_at")


def downgrade() -> None:
    op.add_column(
        "ice_company_responses",
        sa.Column("join_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ice_company_responses",
        sa.Column("departing", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "ice_company_responses",
        sa.Column("needs_reconfirm", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "ice_company_responses",
        sa.Column("reminders_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("ice_company_responses", sa.Column("attended", sa.Boolean(), nullable=True))

    op.add_column(
        "ice_company_events",
        sa.Column("previous_starts_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.drop_constraint("ck_ice_companies_status", "ice_companies", type_="check")
    op.add_column(
        "ice_companies",
        sa.Column("cancel_notice_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "ice_companies",
        sa.Column("schedule_notice_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("ice_companies", sa.Column("confirm_notified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ice_companies",
        sa.Column("weekly_in_chat", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("ice_companies", sa.Column("max_people", sa.Integer(), nullable=True))
    op.add_column("ice_companies", sa.Column("min_people", sa.Integer(), nullable=False, server_default="3"))

    op.create_check_constraint(
        "ck_ice_companies_max_people",
        "ice_companies",
        "max_people IS NULL OR max_people >= min_people",
    )
    op.create_check_constraint(
        "ck_ice_companies_min_people",
        "ice_companies",
        "min_people BETWEEN 1 AND 30",
    )
    op.create_check_constraint(
        "ck_ice_companies_status",
        "ice_companies",
        "status IN ('open', 'confirmed', 'cancelled', 'expired')",
    )

    op.create_table(
        "ice_company_reminders",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "company_id",
            sa.BigInteger(),
            sa.ForeignKey("ice_companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.UniqueConstraint("company_id", "kind", name="uq_ice_company_reminders_kind"),
        sa.CheckConstraint(
            "kind IN ('day', 'hour', 'organizer_followup', 'after', 'weekly')",
            name="ck_ice_company_reminders_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'skipped')",
            name="ck_ice_company_reminders_status",
        ),
    )
    op.create_index("ix_ice_company_reminders_due", "ice_company_reminders", ["status", "due_at"])
