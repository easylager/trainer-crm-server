"""bookings: where the client who booked themselves came from (TASK-351).

``source`` is a short stable code (``src/application/booking_source.py``): trainer link,
recommendation, rink page, city page, site catalog, trainer page, Mini App, unknown.
``source_arena_id`` / ``source_city_id`` keep the place when the source has one. No FKs:
attribution must never fail a booking. Old rows and trainer-made bookings stay NULL.

Revision ID: 0307_booking_source
Revises: 0306_service_direction
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0307_booking_source"
down_revision = "0306_service_direction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("source", sa.String(length=24), nullable=True))
    op.add_column("bookings", sa.Column("source_arena_id", sa.Integer(), nullable=True))
    op.add_column("bookings", sa.Column("source_city_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("bookings", "source_city_id")
    op.drop_column("bookings", "source_arena_id")
    op.drop_column("bookings", "source")
