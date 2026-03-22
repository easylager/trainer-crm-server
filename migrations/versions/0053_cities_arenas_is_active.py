"""Add is_active to cities and arenas for soft-delete."""

from alembic import op
import sqlalchemy as sa


revision = "0053_cities_arenas_is_active"
down_revision = "0052_legal_documents_agreements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cities",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "arenas",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("arenas", "is_active")
    op.drop_column("cities", "is_active")
