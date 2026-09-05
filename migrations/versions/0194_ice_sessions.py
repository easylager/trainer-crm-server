"""Canonical ice_sessions table for MK/open-ice slots (TASK-050).

Manual admin entry and later parsers share these columns. Recurrence instances
are keyed by (recurrence_key, local_date) so a cancelled row is not resurrected.

Revision ID: 0194_ice_sessions
Revises: 0193_media
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0194_ice_sessions"
down_revision = "0193_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ice_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("starts_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("starts_at_local", sa.Time(), nullable=False),
        sa.Column("ends_at_local", sa.Time(), nullable=False),
        sa.Column("price_adult_minor", sa.Integer(), nullable=True),
        sa.Column("price_child_minor", sa.Integer(), nullable=True),
        sa.Column("price_rental_minor", sa.Integer(), nullable=True),
        sa.Column("price_minor", sa.Integer(), nullable=True),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("price_note", sa.String(length=256), nullable=True),
        sa.Column("session_label", sa.String(length=128), nullable=True),
        sa.Column("age_note", sa.String(length=128), nullable=True),
        sa.Column("capacity_note", sa.String(length=128), nullable=True),
        sa.Column("external_url", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("recurrence_key", sa.String(length=64), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('public_skate', 'open_ice', 'rental', 'school_group', 'event')",
            name="ck_ice_sessions_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'cancelled', 'superseded')",
            name="ck_ice_sessions_status",
        ),
        sa.CheckConstraint(
            "price_adult_minor IS NULL OR price_adult_minor >= 0",
            name="ck_ice_sessions_price_adult",
        ),
        sa.CheckConstraint(
            "price_child_minor IS NULL OR price_child_minor >= 0",
            name="ck_ice_sessions_price_child",
        ),
        sa.CheckConstraint(
            "price_rental_minor IS NULL OR price_rental_minor >= 0",
            name="ck_ice_sessions_price_rental",
        ),
        sa.CheckConstraint(
            "EXTRACT(EPOCH FROM (ends_at_utc - starts_at_utc)) / 60 BETWEEN 30 AND 120",
            name="ck_ice_sessions_duration",
        ),
    )
    op.create_index("ix_ice_sessions_arena_starts", "ice_sessions", ["arena_id", "starts_at_utc"])
    op.create_index("ix_ice_sessions_local_date_arena", "ice_sessions", ["local_date", "arena_id"])
    op.create_index(
        "uq_ice_sessions_recurrence_date",
        "ice_sessions",
        ["recurrence_key", "local_date"],
        unique=True,
        postgresql_where=sa.text("recurrence_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_ice_sessions_recurrence_date", table_name="ice_sessions")
    op.drop_index("ix_ice_sessions_local_date_arena", table_name="ice_sessions")
    op.drop_index("ix_ice_sessions_arena_starts", table_name="ice_sessions")
    op.drop_table("ice_sessions")
