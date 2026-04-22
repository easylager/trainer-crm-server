"""Trainer morning/weekly digest settings + once-per-day-per-kind send log.

- trainers.digest_enabled: opt-in to ritual push (default TRUE).
- trainers.digest_send_time: Europe/Minsk local time; NULL = auto 1h before first session.
- trainer_digest_sent: guarantees one digest per (trainer, date, kind='daily'|'weekly').
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0118_trainer_digest_settings"
down_revision = "0117_trainer_no_pass_footer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainers",
        sa.Column(
            "digest_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "trainers",
        sa.Column("digest_send_time", sa.Time(), nullable=True),
    )

    op.create_table(
        "trainer_digest_sent",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("sent_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "trainer_id", "sent_date", "kind", name="uq_trainer_digest_sent"
        ),
    )
    op.create_index(
        op.f("ix_trainer_digest_sent_trainer_id"),
        "trainer_digest_sent",
        ["trainer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_trainer_digest_sent_trainer_id"),
        table_name="trainer_digest_sent",
    )
    op.drop_table("trainer_digest_sent")
    op.drop_column("trainers", "digest_send_time")
    op.drop_column("trainers", "digest_enabled")
