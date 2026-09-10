"""client_share_events: append-only log of what a client sent into a chat (TASK-096, G-P5).

Why a separate table and not trainer_demand_events: that one is Lead Mode and requires
trainer_id. The headline share artifact is a city's ice schedule — it has no trainer.

Revision ID: 0200_client_share_events
Revises: 0198_ice_scrape_runs

Numbered 0200 while revising 0198 on purpose: 0199_ice_city_interest lives on
feat/TASK-082-ice-map-loader-groups, which release/client-premium does not contain. Chaining to a
revision this branch cannot see would break `alembic upgrade` here, so the number skips to avoid
a filename collision and the chain stays truthful. Whoever merges the two branches resolves the
resulting pair of heads the normal way (`alembic merge`).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0200_client_share_events"
down_revision = "0198_ice_scrape_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_share_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # What was shared. Extend the CHECK when a new artifact appears — an unknown kind
        # must fail loudly rather than land as an untyped row nobody can count.
        sa.Column("kind", sa.String(length=32), nullable=False),
        # Where the button was pressed (ice_tab, my_trainer, catalog, booking_success, next_booking).
        sa.Column("share_context", sa.String(length=40), nullable=True),
        sa.Column(
            "city_id", sa.Integer(), sa.ForeignKey("cities.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "trainer_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # sha256(telegram_id || kind || day) — irreversible. Lets us count *people* who shared
        # without storing who they are, and collapses refresh-spam within a day.
        sa.Column("actor_hash", sa.String(length=64), nullable=True),
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "kind IN ('ice_city_day', 'trainer')",
            name="ck_client_share_events_kind",
        ),
    )
    op.create_index(
        "ix_client_share_events_kind_occurred",
        "client_share_events",
        ["kind", "occurred_at"],
    )
    op.create_index(
        "ix_client_share_events_city_occurred",
        "client_share_events",
        ["city_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_client_share_events_city_occurred", table_name="client_share_events")
    op.drop_index("ix_client_share_events_kind_occurred", table_name="client_share_events")
    op.drop_table("client_share_events")
