"""Client profile links: one Telegram/VK account can act as several client profiles.

Decouples "who is logged in" (``account_telegram_id`` — the same key produced by
``client_catalog_telegram_key``) from "who the service is for" (``profile_client_id`` —
a ``clients`` row). A parent managing two children's separate booking histories needs two
``clients`` rows and two links from their one account; today the system has only one
``clients`` row per Telegram account, so a second child's booking silently lands on the
first child's history (see docs/adr/004-multi-profile-clients.md).

Backfill is exact and lossless: today every ``clients.telegram_id`` maps 1:1 to its own
row, so a ``role='self', is_default=true`` link reproduces today's resolution exactly.
No existing behavior changes until callers start reading this table.

Revision ID: 0186_client_profile_links
Revises: 0185_hint_dismissals
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0186_client_profile_links"
down_revision = "0185_hint_dismissals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_profile_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_client_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="guardian"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["profile_client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_telegram_id", "profile_client_id", name="uq_client_profile_links_account_profile"
        ),
    )
    op.create_index(
        "ix_client_profile_links_account",
        "client_profile_links",
        ["account_telegram_id"],
    )
    op.create_index(
        "ix_client_profile_links_profile",
        "client_profile_links",
        ["profile_client_id"],
    )
    # Hard invariant: at most one default profile per account. Not just a nicety — a lazy
    # self-link backfill running after a different profile was already made default must
    # never be able to silently create a second "default" row (see EPIC1 Slice 3 regression:
    # test_ensure_self_link_never_creates_a_second_default_after_switch).
    op.create_index(
        "uq_client_profile_links_one_default_per_account",
        "client_profile_links",
        ["account_telegram_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.execute(
        """
        INSERT INTO client_profile_links (account_telegram_id, profile_client_id, role, is_default)
        SELECT telegram_id, id, 'self', true
        FROM clients
        WHERE telegram_id IS NOT NULL
        ON CONFLICT (account_telegram_id, profile_client_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("uq_client_profile_links_one_default_per_account", table_name="client_profile_links")
    op.drop_index("ix_client_profile_links_profile", table_name="client_profile_links")
    op.drop_index("ix_client_profile_links_account", table_name="client_profile_links")
    op.drop_table("client_profile_links")
