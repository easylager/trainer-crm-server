"""
Restrict price variants to adult/child tier_kind; snapshot price_tier_kind on bookings.

Revision ID: 0080
Revises: 0079
"""
from alembic import op
import sqlalchemy as sa


revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Add tier_kind nullable, backfill, enforce
    op.add_column(
        "trainer_service_price_variants",
        sa.Column("tier_kind", sa.String(length=16), nullable=True),
    )

    op.execute(
        """
        DELETE FROM trainer_service_price_variants v
        USING (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY trainer_id, service_id
                           ORDER BY sort_order, id
                       ) AS rn
                FROM trainer_service_price_variants
            ) x
            WHERE x.rn > 2
        ) d
        WHERE v.id = d.id
        """
    )

    op.execute(
        """
        UPDATE trainer_service_price_variants v
        SET tier_kind = sub.tk
        FROM (
            SELECT id,
                   CASE ROW_NUMBER() OVER (
                       PARTITION BY trainer_id, service_id
                       ORDER BY sort_order, id
                   )
                       WHEN 1 THEN 'adult'
                       WHEN 2 THEN 'child'
                       ELSE 'adult'
                   END AS tk
            FROM trainer_service_price_variants
        ) sub
        WHERE v.id = sub.id
        """
    )

    op.execute(
        """
        UPDATE trainer_service_price_variants
        SET label = CASE tier_kind
            WHEN 'adult' THEN 'Взрослый'
            WHEN 'child' THEN 'Детский'
            ELSE COALESCE(label, 'Взрослый')
        END
        """
    )

    op.alter_column(
        "trainer_service_price_variants",
        "tier_kind",
        existing_type=sa.String(length=16),
        nullable=False,
        server_default="adult",
    )

    op.drop_constraint(
        "uq_trainer_service_price_variant_order",
        "trainer_service_price_variants",
        type_="unique",
    )

    op.create_unique_constraint(
        "uq_trainer_service_price_tier_kind",
        "trainer_service_price_variants",
        ["trainer_id", "service_id", "tier_kind"],
    )

    op.create_index(
        op.f("ix_trainer_service_price_variants_tier_kind"),
        "trainer_service_price_variants",
        ["tier_kind"],
        unique=False,
    )

    # 2) Booking snapshot
    op.add_column(
        "bookings",
        sa.Column("price_tier_kind", sa.String(length=16), nullable=True),
    )

    op.execute(
        """
        UPDATE bookings b
        SET price_tier_kind = v.tier_kind
        FROM trainer_service_price_variants v
        WHERE b.service_price_variant_id = v.id
          AND b.price_tier_kind IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("bookings", "price_tier_kind")

    op.drop_index(
        op.f("ix_trainer_service_price_variants_tier_kind"),
        table_name="trainer_service_price_variants",
    )
    op.drop_constraint(
        "uq_trainer_service_price_tier_kind",
        "trainer_service_price_variants",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_trainer_service_price_variant_order",
        "trainer_service_price_variants",
        ["trainer_id", "service_id", "sort_order"],
    )

    op.drop_column("trainer_service_price_variants", "tier_kind")
