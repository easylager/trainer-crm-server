"""Explicit catalog publication state for trainers, with an event journal.

Before this, "is the trainer in the public catalog?" was the pair
``status = 'active' AND is_catalog_visible = true``, duplicated across eleven
queries — and an incomplete profile silently demoted the whole **account** to
``pending_profile`` (``trainer_use_cases._demote_status_if_profile_incomplete``),
so "card left the catalog" and "account never passed moderation" were the same
event with no notification attached to either.

``catalog_state`` separates the two: the account keeps ``status``, the card gets
its own state, and every transition is one row in ``trainer_catalog_events``.

``is_catalog_visible`` stays for one release as a derived mirror (written only by
``set_catalog_state``) so admin tooling and analytics keep working.

Revision ID: 0206_trainer_catalog_state
Revises: 0205_client_merges_audit
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0206_trainer_catalog_state"
down_revision = "0205_client_merges_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainers",
        sa.Column(
            "catalog_state",
            sa.String(24),
            nullable=False,
            server_default="draft",
        ),
    )
    # Machine-readable code (missing_phone, moderator_revision, …) — UI and tests
    # read this; the human sentence lives in the event's reason_detail.
    op.add_column("trainers", sa.Column("catalog_state_reason", sa.String(64), nullable=True))
    op.add_column(
        "trainers",
        sa.Column("catalog_state_changed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "trainer_catalog_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "trainer_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # NULL only for the very first event of a trainer that had no prior state.
        sa.Column("from_state", sa.String(24), nullable=True),
        sa.Column("to_state", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column("reason_detail", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_trainer_catalog_events_trainer",
        "trainer_catalog_events",
        ["trainer_id", sa.text("created_at DESC")],
    )

    # --- Backfill -----------------------------------------------------------
    # Order matters: every branch is mutually exclusive on (status, flag,
    # moderation_submitted_at, moderation_feedback), and the set of publicly
    # visible trainers must be identical before and after (see the migration
    # test). `status = 'active'` is reachable only through an admin approval,
    # so an active-but-hidden trainer has an already-reviewed card: they get
    # `hidden` (return in one tap, no re-moderation), never `draft`.
    op.execute(
        """
        UPDATE trainers SET
            catalog_state = CASE
                WHEN status = 'deactivated' THEN 'draft'
                WHEN status = 'active' AND is_catalog_visible THEN 'published'
                WHEN status = 'active' THEN 'hidden'
                WHEN is_catalog_visible
                     AND moderation_feedback IS NOT NULL
                     AND btrim(moderation_feedback) <> '' THEN 'needs_revision'
                WHEN is_catalog_visible
                     AND moderation_submitted_at IS NOT NULL THEN 'pending_review'
                ELSE 'draft'
            END,
            catalog_state_changed_at = now()
        """
    )
    op.execute(
        """
        INSERT INTO trainer_catalog_events (
            trainer_id, from_state, to_state, reason, reason_detail, actor_type, actor_id
        )
        SELECT id, NULL, catalog_state, 'backfill_0206',
               'Состояние восстановлено из status + is_catalog_visible при переходе на явную модель.',
               'system', 'migration'
        FROM trainers
        """
    )


def downgrade() -> None:
    op.drop_index("ix_trainer_catalog_events_trainer", table_name="trainer_catalog_events")
    op.drop_table("trainer_catalog_events")
    op.drop_column("trainers", "catalog_state_changed_at")
    op.drop_column("trainers", "catalog_state_reason")
    op.drop_column("trainers", "catalog_state")
