"""Freeze pass sale price on pass_instances (accounting must not follow product price edits)."""

from alembic import op
import sqlalchemy as sa


revision = "0157_pass_instance_price"
down_revision = "0156_merge_audit_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pass_instances", sa.Column("price_cents", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE pass_instances pi
        SET price_cents = p.price_cents
        FROM trainer_pass_products p
        WHERE p.id = pi.pass_product_id
          AND pi.price_cents IS NULL
        """
    )
    op.execute(
        """
        UPDATE pass_instances
        SET price_cents = 0
        WHERE price_cents IS NULL
        """
    )
    op.alter_column("pass_instances", "price_cents", nullable=False)


def downgrade() -> None:
    op.drop_column("pass_instances", "price_cents")
