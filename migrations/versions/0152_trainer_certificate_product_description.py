"""Optional marketing copy on certificate products (title stays in name)."""

from alembic import op
import sqlalchemy as sa

revision = "0152_cert_product_description"
down_revision = "0151_session_milestones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_certificate_products",
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_certificate_products", "description")
