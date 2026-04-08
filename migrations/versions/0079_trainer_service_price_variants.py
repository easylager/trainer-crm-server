"""
Trainer service price variants: multiple tariffs per (trainer, service) + booking price snapshot.

Revision ID: 0079
Revises: 0078
"""
from alembic import op
import sqlalchemy as sa


revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None

DEFAULT_TIER_LABEL = "Основной"


def upgrade() -> None:
    op.create_table(
        "trainer_service_price_variants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["trainer_id", "service_id"],
            ["trainer_services.trainer_id", "trainer_services.service_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trainer_id", "service_id", "sort_order", name="uq_trainer_service_price_variant_order"),
    )
    op.create_index(
        op.f("ix_trainer_service_price_variants_trainer_service"),
        "trainer_service_price_variants",
        ["trainer_id", "service_id"],
        unique=False,
    )

    lbl = DEFAULT_TIER_LABEL.replace("'", "''")
    op.execute(
        f"""
        INSERT INTO trainer_service_price_variants (trainer_id, service_id, label, price_cents, sort_order)
        SELECT trainer_id, service_id, '{lbl}', price_cents, 0
        FROM trainer_services
        WHERE price_cents IS NOT NULL
        """
    )

    op.add_column(
        "bookings",
        sa.Column("service_price_variant_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column("booking_price_cents", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_bookings_service_price_variant_id",
        "bookings",
        "trainer_service_price_variants",
        ["service_price_variant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_bookings_service_price_variant_id"),
        "bookings",
        ["service_price_variant_id"],
        unique=False,
    )

    op.execute(
        """
        UPDATE bookings b
        SET booking_price_cents = ts.price_cents
        FROM trainer_services ts
        WHERE ts.trainer_id = b.trainer_id
          AND ts.service_id = b.service_id
          AND b.booking_price_cents IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_bookings_service_price_variant_id"), table_name="bookings")
    op.drop_constraint("fk_bookings_service_price_variant_id", "bookings", type_="foreignkey")
    op.drop_column("bookings", "booking_price_cents")
    op.drop_column("bookings", "service_price_variant_id")
    op.drop_index(op.f("ix_trainer_service_price_variants_trainer_service"), table_name="trainer_service_price_variants")
    op.drop_table("trainer_service_price_variants")
