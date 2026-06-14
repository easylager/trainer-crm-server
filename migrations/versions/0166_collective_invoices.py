"""Collective pool subscription invoices (Wave P2.1 self-service billing)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0166_collective_invoices"
down_revision = "0165_collective_brand_kit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collective_invoices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "collective_id",
            sa.Integer(),
            sa.ForeignKey("collectives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_trainer_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("period_months", sa.Integer(), nullable=False),
        sa.Column(
            "modules",
            JSONB(),
            nullable=False,
            server_default=sa.text(
                "(jsonb_build_object('online', true, 'analytics', true, 'groups', true))"
            ),
        ),
        sa.Column("seat_limit", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="sent"),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_external_id", sa.String(256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('sent', 'paid', 'overdue', 'cancelled')",
            name="ck_collective_invoices_status",
        ),
    )
    op.create_index(
        "ix_collective_invoices_collective_id",
        "collective_invoices",
        ["collective_id"],
    )
    op.create_index(
        "ix_collective_invoices_status",
        "collective_invoices",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("collective_invoices")
