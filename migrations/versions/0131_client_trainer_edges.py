"""
Client ↔ Trainer edge-state graph.

Replaces the single selected_trainer_id scalar with a proper edge table:
  - is_saved / is_primary flags (orthogonal)
  - completed_count counter
  - recency timestamps (saved_at, last_booking_at, last_completed_at, last_interaction_at)
  - context_type / context_id for future contextual-primary scoping

Data migration:
  1. selected_trainer_id → is_primary = true (preserve existing "my trainer" state)
  2. completed bookings (status='completed') → completed_count, last_completed_at per pair
  3. any bookings → last_booking_at, last_interaction_at per pair
"""

import sqlalchemy as sa
from alembic import op

revision = "0131_client_trainer_edges"
down_revision = "0130_seed_service_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_trainer_edges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("is_saved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_booking_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_interaction_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context_type", sa.String(32), nullable=True),
        sa.Column("context_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["telegram_id"],
            ["client_sessions.telegram_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trainer_id"],
            ["trainers.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "telegram_id", "trainer_id", "context_type", "context_id",
            name="uq_client_trainer_context",
        ),
    )
    op.create_index("ix_client_trainer_edges_telegram_id", "client_trainer_edges", ["telegram_id"])
    op.create_index("ix_client_trainer_edges_trainer_id", "client_trainer_edges", ["trainer_id"])

    # ── Data migration ─────────────────────────────────────────────────────────
    conn = op.get_bind()

    # 1. existing selected_trainer_id → is_primary = true edge
    #    Only for sessions that have a valid trainer_id pointing to an existing trainer.
    conn.execute(sa.text("""
        INSERT INTO client_trainer_edges
            (telegram_id, trainer_id, is_primary, is_saved, completed_count, created_at)
        SELECT
            cs.telegram_id,
            cs.selected_trainer_id,
            true,
            false,
            0,
            now()
        FROM client_sessions cs
        JOIN trainers t ON t.id = cs.selected_trainer_id
        WHERE cs.selected_trainer_id IS NOT NULL
        ON CONFLICT ON CONSTRAINT uq_client_trainer_context DO NOTHING
    """))

    # 2. aggregate booking history into edges
    #    Upsert: create edge if not exists, then update counters + timestamps.
    conn.execute(sa.text("""
        INSERT INTO client_trainer_edges
            (telegram_id, trainer_id, is_primary, is_saved, completed_count,
             last_booking_at, last_completed_at, last_interaction_at, created_at)
        SELECT
            c.telegram_id,
            b.trainer_id,
            false,
            false,
            COUNT(*) FILTER (WHERE b.status = 'completed'),
            MAX(b.created_at),
            MAX(b.created_at) FILTER (WHERE b.status = 'completed'),
            MAX(b.created_at),
            MIN(b.created_at)
        FROM bookings b
        JOIN clients c ON c.id = b.client_id
        WHERE c.telegram_id IS NOT NULL
        GROUP BY c.telegram_id, b.trainer_id
        ON CONFLICT ON CONSTRAINT uq_client_trainer_context DO UPDATE SET
            completed_count    = GREATEST(
                client_trainer_edges.completed_count,
                EXCLUDED.completed_count
            ),
            last_booking_at    = GREATEST(
                client_trainer_edges.last_booking_at,
                EXCLUDED.last_booking_at
            ),
            last_completed_at  = GREATEST(
                client_trainer_edges.last_completed_at,
                EXCLUDED.last_completed_at
            ),
            last_interaction_at = GREATEST(
                client_trainer_edges.last_interaction_at,
                EXCLUDED.last_interaction_at
            )
    """))


def downgrade() -> None:
    op.drop_index("ix_client_trainer_edges_trainer_id", "client_trainer_edges")
    op.drop_index("ix_client_trainer_edges_telegram_id", "client_trainer_edges")
    op.drop_table("client_trainer_edges")
