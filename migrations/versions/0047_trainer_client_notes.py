"""Trainer-client notes table: per-trainer private notes about clients.

Revision ID: 0047_trainer_client_notes
Revises: 0046_certificate_products
"""
from alembic import op
import sqlalchemy as sa


revision = "0047_trainer_client_notes"
down_revision = "0046_certificate_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_client_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trainer_id", sa.Integer(), sa.ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("trainer_id", "client_id", name="uq_trainer_client_notes_trainer_client"),
    )
    op.create_index(
        "ix_trainer_client_notes_trainer_id",
        "trainer_client_notes",
        ["trainer_id"],
        unique=False,
    )
    op.create_index(
        "ix_trainer_client_notes_client_id",
        "trainer_client_notes",
        ["client_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_trainer_client_notes_client_id", table_name="trainer_client_notes")
    op.drop_index("ix_trainer_client_notes_trainer_id", table_name="trainer_client_notes")
    op.drop_table("trainer_client_notes")

