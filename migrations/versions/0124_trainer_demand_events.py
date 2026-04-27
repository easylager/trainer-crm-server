"""Lead Mode foundation: append-only demand signals (profile views, contact clicks, blocked attempts).

Anonymous counters only — no user-level identity. dedup_hash is sha256(ip||ua||trainer_id||day) to
collapse refresh-spam inside 24h windows. The hash itself is not PII (irreversible, narrow window),
and IP/UA are never stored in cleartext.

Revision ID: 0124_demand_events
Revises: 0123_trinity_arena_preset
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0124_demand_events"
down_revision = "0123_trinity_arena_preset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_demand_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        # kind: profile_view | contact_click | booking_attempt_blocked (open enum, validated in app layer).
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # source: catalog | direct_link | search | bot | client_app — free-form, validated in app.
        sa.Column("source", sa.String(40), nullable=True),
        # sha256 hex (64 chars). Same (trainer_id, kind, dedup_hash) collapses refresh spam.
        sa.Column("dedup_hash", sa.CHAR(64), nullable=True),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Hot path: aggregate per trainer over time window (last 7d/14d/30d).
    op.create_index(
        "ix_demand_events_trainer_time",
        "trainer_demand_events",
        ["trainer_id", sa.text("occurred_at DESC")],
    )
    # Cross-trainer reporting per kind (admin analytics).
    op.create_index(
        "ix_demand_events_kind_time",
        "trainer_demand_events",
        ["kind", sa.text("occurred_at DESC")],
    )
    # Partial unique to dedupe refresh storms; rows without dedup_hash (server-side events) are not deduped.
    op.create_index(
        "ux_demand_events_dedup",
        "trainer_demand_events",
        ["trainer_id", "kind", "dedup_hash"],
        unique=True,
        postgresql_where=sa.text("dedup_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_demand_events_dedup", table_name="trainer_demand_events")
    op.drop_index("ix_demand_events_kind_time", table_name="trainer_demand_events")
    op.drop_index("ix_demand_events_trainer_time", table_name="trainer_demand_events")
    op.drop_table("trainer_demand_events")
