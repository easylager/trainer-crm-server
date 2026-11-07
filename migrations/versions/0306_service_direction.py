"""services: link a trainer's own service to a catalog direction.

``direction_service_id`` points at a public reference service (the «direction»).
``direction_decided_at`` records that an admin looked at the service:
  * decided_at NULL                     -> not reviewed yet
  * decided_at set, direction NULL      -> «не показывать» in the catalog
  * both set                            -> linked to that direction
``direction_decided_by`` is the admin's Telegram id.

Revision ID: 0306_service_direction
Revises: 0305_ice_city_interest_actor
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0306_service_direction"
down_revision = "0305_ice_city_interest_actor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "services",
        sa.Column(
            "direction_service_id",
            sa.Integer(),
            sa.ForeignKey("services.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("services", sa.Column("direction_decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("services", sa.Column("direction_decided_by", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        "ck_services_direction_not_self",
        "services",
        "direction_service_id IS NULL OR direction_service_id <> id",
    )


def downgrade() -> None:
    op.drop_constraint("ck_services_direction_not_self", "services", type_="check")
    op.drop_column("services", "direction_decided_by")
    op.drop_column("services", "direction_decided_at")
    op.drop_column("services", "direction_service_id")
