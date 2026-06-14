"""Collective brand kit: cover, about, gallery (Wave P1.6)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0165_collective_brand_kit"
down_revision = "0164_collective_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collectives", sa.Column("cover_key", sa.String(256), nullable=True))
    op.add_column("collectives", sa.Column("about", sa.Text(), nullable=True))
    op.add_column(
        "collectives",
        sa.Column(
            "gallery_keys",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("collectives", "gallery_keys")
    op.drop_column("collectives", "about")
    op.drop_column("collectives", "cover_key")
