"""Add address and coordinates to arenas for map link (Belarus: Yandex.by).

Revision ID: 0022_arena_address_coords
Revises: 0021_arenas
"""
from alembic import op
import sqlalchemy as sa


revision = "0022_arena_address_coords"
down_revision = "0021_arenas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("arenas", sa.Column("address", sa.String(512), nullable=True))
    op.add_column("arenas", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("arenas", sa.Column("longitude", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("arenas", "longitude")
    op.drop_column("arenas", "latitude")
    op.drop_column("arenas", "address")
