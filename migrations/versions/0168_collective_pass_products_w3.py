"""Collective center pass products, instances, redemptions (ADR-003 W3)."""

from alembic import op
import sqlalchemy as sa

revision = "0168_collective_pass_products_w3"
down_revision = "0167_collective_sessions_w2"
branch_labels = None
depends_on = None

PASS_KINDS = ("lane", "coach")
INSTANCE_STATUSES = ("active", "used_up", "expired", "cancelled")


def upgrade() -> None:
    op.create_table(
        "collective_pass_products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "collective_id",
            sa.Integer(),
            sa.ForeignKey("collectives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pass_kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sessions_total", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            f"pass_kind IN ({', '.join(repr(k) for k in PASS_KINDS)})",
            name="ck_collective_pass_products_kind",
        ),
        sa.CheckConstraint(
            "sessions_total >= 1 AND sessions_total <= 500",
            name="ck_collective_pass_products_sessions",
        ),
        sa.CheckConstraint("price_cents >= 0", name="ck_collective_pass_products_price"),
    )
    op.create_index(
        "ix_collective_pass_products_collective_id",
        "collective_pass_products",
        ["collective_id"],
    )

    op.create_table(
        "collective_pass_instances",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "collective_id",
            sa.Integer(),
            sa.ForeignKey("collectives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collective_pass_product_id",
            sa.Integer(),
            sa.ForeignKey("collective_pass_products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sessions_total", sa.Integer(), nullable=False),
        sa.Column("sessions_remaining", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in INSTANCE_STATUSES)})",
            name="ck_collective_pass_instances_status",
        ),
    )
    op.create_index(
        "ix_collective_pass_instances_client_collective",
        "collective_pass_instances",
        ["client_id", "collective_id"],
    )
    op.create_index(
        "ix_collective_pass_instances_product_id",
        "collective_pass_instances",
        ["collective_pass_product_id"],
    )

    op.create_table(
        "collective_pass_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "collective_pass_instance_id",
            sa.Integer(),
            sa.ForeignKey("collective_pass_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collective_session_booking_id",
            sa.Integer(),
            sa.ForeignKey("collective_session_bookings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("credits_debited", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("guest_surcharge_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "collective_session_booking_id",
            name="uq_collective_pass_redemptions_booking",
        ),
    )

    op.add_column(
        "collective_session_bookings",
        sa.Column(
            "collective_pass_instance_id",
            sa.Integer(),
            sa.ForeignKey("collective_pass_instances.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "collective_session_bookings",
        sa.Column("pass_credits_reserved", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("collective_session_bookings", "pass_credits_reserved")
    op.drop_column("collective_session_bookings", "collective_pass_instance_id")
    op.drop_table("collective_pass_redemptions")
    op.drop_table("collective_pass_instances")
    op.drop_table("collective_pass_products")
