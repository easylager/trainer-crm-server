"""Trainer ratings: table + aggregates on profile for Bayesian sort.

Revision ID: 0016_trainer_ratings
Revises: 0015_booking_request_link
"""
from alembic import op
import sqlalchemy as sa


revision = "0016_trainer_ratings"
down_revision = "0015_booking_request_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_ratings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("client_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trainer_id", "client_telegram_id", name="uq_trainer_rating_client"),
    )
    op.create_index(op.f("ix_trainer_ratings_trainer_id"), "trainer_ratings", ["trainer_id"], unique=False)

    op.add_column(
        "trainer_profiles",
        sa.Column("rating_avg", sa.Float(), nullable=True),
    )
    op.add_column(
        "trainer_profiles",
        sa.Column("rating_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("trainer_profiles", "rating_count")
    op.drop_column("trainer_profiles", "rating_avg")
    op.drop_index(op.f("ix_trainer_ratings_trainer_id"), table_name="trainer_ratings")
    op.drop_table("trainer_ratings")
