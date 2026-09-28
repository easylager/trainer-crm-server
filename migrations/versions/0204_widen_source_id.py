"""Widen ice_sessions.source_id — Google Calendar recurring-instance ids overflow varchar(64).

Ozerki's public-skate calendar publishes recurring events; each instance id
Google returns is base id + date suffix, routinely 55-60 chars. Combined with
the "<rink_code>:" prefix ingestion adapters use, that blew past the original
64-char budget and crashed the publish INSERT (StringDataRightTruncationError),
which in turn took down the whole ice-ingest scheduler tick (see
src/ingestion/normalize.py's _safe_source_id for the belt-and-suspenders cap
that also bounds this column regardless of width).

Revision ID: 0204_widen_source_id
Revises: 0203_merge_tickets_oval
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0204_widen_source_id"
down_revision = "0203_merge_tickets_oval"
branch_labels = None
depends_on = None


NEW_LENGTH = 160
OLD_LENGTH = 64


def upgrade() -> None:
    op.alter_column(
        "ice_sessions",
        "source_id",
        type_=sa.String(length=NEW_LENGTH),
        existing_type=sa.String(length=OLD_LENGTH),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "ice_sessions",
        "source_id",
        type_=sa.String(length=OLD_LENGTH),
        existing_type=sa.String(length=NEW_LENGTH),
        existing_nullable=True,
    )
