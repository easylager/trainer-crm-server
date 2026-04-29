"""client_trainer_edges: service context for primary-trainer / primary-service matching."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0135_edge_booking_saved_service"
down_revision = "0134_vk_user_id_clients_trainers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_trainer_edges",
        sa.Column(
            "last_booking_service_id",
            sa.Integer(),
            sa.ForeignKey("services.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "client_trainer_edges",
        sa.Column(
            "saved_catalog_service_id",
            sa.Integer(),
            sa.ForeignKey("services.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE client_trainer_edges e
            SET last_booking_service_id = x.service_id
            FROM (
              SELECT DISTINCT ON (c.telegram_id, b.trainer_id)
                c.telegram_id AS telegram_id,
                b.trainer_id AS trainer_id,
                b.service_id AS service_id
              FROM bookings b
              INNER JOIN clients c ON c.id = b.client_id AND c.telegram_id IS NOT NULL
              INNER JOIN slots s ON s.id = b.slot_id
              WHERE b.status NOT IN ('cancelled', 'declined')
              ORDER BY c.telegram_id, b.trainer_id,
                s.slot_date DESC, s.start_time DESC NULLS LAST, b.id DESC
            ) x
            WHERE e.telegram_id = x.telegram_id AND e.trainer_id = x.trainer_id
            """
        )
    )


def downgrade() -> None:
    op.drop_column("client_trainer_edges", "saved_catalog_service_id")
    op.drop_column("client_trainer_edges", "last_booking_service_id")
