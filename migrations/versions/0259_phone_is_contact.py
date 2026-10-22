"""Phone is a contact, not an identity: one family number may belong to several clients.

The unique index made the second child added with mom's number overwrite the first one,
and a second parent booking with the family number crash with a 500. Identity is the
Telegram/MAX account plus ``client_profile_links``; the phone stays indexed for lookup.

``trainer_client_match_dismissals`` remembers the trainer's «разные люди» answer to
«Похоже, это Анна из вашего списка» so the same pair is never offered again.

Revision ID: 0259_phone_is_contact
Revises: 0258_rink_visit_data
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0259_phone_is_contact"
down_revision = "0258_rink_visit_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_clients_phone_normalized", table_name="clients")
    op.create_index("ix_clients_phone_normalized", "clients", ["phone_normalized"], unique=False)

    op.create_table(
        "trainer_client_match_dismissals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "trainer_id", sa.Integer(), sa.ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "other_client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "trainer_id", "client_id", "other_client_id", name="ux_client_match_dismissals_pair"
        ),
    )


def downgrade() -> None:
    op.drop_table("trainer_client_match_dismissals")
    # Fails if a family number is already shared — that data is exactly what upgrade allows.
    op.drop_index("ix_clients_phone_normalized", table_name="clients")
    op.create_index(
        "ix_clients_phone_normalized",
        "clients",
        ["phone_normalized"],
        unique=True,
        postgresql_where=sa.text("phone_normalized IS NOT NULL AND phone_normalized <> ''"),
    )
