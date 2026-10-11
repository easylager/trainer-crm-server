"""Term of a trainer pass product, snapshotted onto the instance at issue.

Revision ID: 0230_trainer_pass_validity_days
Revises: 0229_ice_watch_season_open

NULL means no clock (a limited visit pack may be open-ended).
A set value is whole days from the moment the trainer issues the pass.
"""

from alembic import op
import sqlalchemy as sa


revision = "0230_trainer_pass_validity_days"
down_revision = "0229_ice_watch_season_open"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_pass_products",
        sa.Column("validity_days", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_trainer_pass_products_validity_days",
        "trainer_pass_products",
        "validity_days IS NULL OR (validity_days >= 1 AND validity_days <= 3650)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_trainer_pass_products_validity_days",
        "trainer_pass_products",
        type_="check",
    )
    op.drop_column("trainer_pass_products", "validity_days")
