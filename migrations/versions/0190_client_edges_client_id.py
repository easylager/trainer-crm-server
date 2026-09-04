"""client_trainer_edges: key on client_id instead of telegram_id (EPIC1 Slice 5).

Today one edge row is shared by (telegram_id, trainer_id) — every client profile of a
Telegram account (self + any guardian/child profiles from Slice 1-4) collapses onto the
same "мой тренер"/saved/notify-slots state. ``client_id`` is the real per-profile identity;
this migration adds it, backfills it 1:1 from the account's own row (exact for every row
that exists today, since no guardian profile could book/save before Slice 4 shipped), and
moves the uniqueness constraint onto it so a child profile gets its own edge going forward.

``telegram_id`` stays NOT NULL — application code (client_trainer_edge_repository.py) still
needs it to populate new rows and to address push notifications (a guardian profile has no
Telegram chat of its own), so it is not dropped or made nullable here.

Revision ID: 0190_client_edges_client_id
Revises: 0189_ru_subscription_pricing
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0190_client_edges_client_id"
down_revision = "0189_ru_subscription_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_trainer_edges",
        sa.Column("client_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_client_trainer_edges_client_id",
        "client_trainer_edges",
        ["client_id"],
    )
    op.create_foreign_key(
        "fk_client_trainer_edges_client_id",
        "client_trainer_edges",
        "clients",
        ["client_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute(
        """
        UPDATE client_trainer_edges e
        SET client_id = c.id
        FROM clients c
        WHERE c.telegram_id = e.telegram_id
          AND e.client_id IS NULL
        """
    )

    op.drop_constraint("uq_client_trainer_pair", "client_trainer_edges", type_="unique")
    op.create_unique_constraint(
        "uq_client_trainer_pair",
        "client_trainer_edges",
        ["client_id", "trainer_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_client_trainer_pair", "client_trainer_edges", type_="unique")
    op.create_unique_constraint(
        "uq_client_trainer_pair",
        "client_trainer_edges",
        ["telegram_id", "trainer_id"],
    )
    op.drop_constraint("fk_client_trainer_edges_client_id", "client_trainer_edges", type_="foreignkey")
    op.drop_index("ix_client_trainer_edges_client_id", table_name="client_trainer_edges")
    op.drop_column("client_trainer_edges", "client_id")
