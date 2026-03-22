"""Add service_id to bookings (FK to services). Backfill from request or trainer's first service, then NOT NULL."""

from alembic import op
import sqlalchemy as sa


revision = "0050_bookings_service_id"
down_revision = "0049_trainer_telegram_username"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Add column nullable, FK to services
    op.add_column(
        "bookings",
        sa.Column("service_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_bookings_service_id_services",
        "bookings",
        "services",
        ["service_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_bookings_service_id", "bookings", ["service_id"], unique=False)

    # 2) Backfill: from client_requests where client_request_id is set
    op.execute(
        """
        UPDATE bookings b
        SET service_id = cr.service_id
        FROM client_requests cr
        WHERE b.client_request_id = cr.id AND b.service_id IS NULL
        """
    )

    # 3) Backfill: for the rest, first service of trainer (by trainer_services.service_id)
    op.execute(
        """
        UPDATE bookings b
        SET service_id = sub.service_id
        FROM (
            SELECT DISTINCT ON (ts.trainer_id) ts.trainer_id, ts.service_id
            FROM trainer_services ts
            ORDER BY ts.trainer_id, ts.service_id
        ) sub
        WHERE b.trainer_id = sub.trainer_id AND b.service_id IS NULL
        """
    )

    # 4) If any NULL left (trainer with no trainer_services), use first service id in system (fallback)
    op.execute(
        """
        UPDATE bookings b
        SET service_id = (SELECT id FROM services ORDER BY id LIMIT 1)
        WHERE b.service_id IS NULL
        """
    )

    # 5) Make column NOT NULL
    op.alter_column(
        "bookings",
        "service_id",
        existing_type=sa.Integer(),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_index("ix_bookings_service_id", table_name="bookings")
    op.drop_constraint("fk_bookings_service_id_services", "bookings", type_="foreignkey")
    op.drop_column("bookings", "service_id")
