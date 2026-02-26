"""Client request responses: trainer "responds" to a request (can fulfill it).

Revision ID: 0013_client_request_responses
Revises: 0012_client_requests
"""
from alembic import op
import sqlalchemy as sa


revision = "0013_client_request_responses"
down_revision = "0012_client_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_request_responses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_request_id", sa.Integer(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["client_request_id"], ["client_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_request_id", "trainer_id", name="uq_request_trainer"),
    )
    op.create_index(
        op.f("ix_client_request_responses_trainer_id"),
        "client_request_responses",
        ["trainer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_client_request_responses_client_request_id"),
        "client_request_responses",
        ["client_request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_client_request_responses_client_request_id"), table_name="client_request_responses")
    op.drop_index(op.f("ix_client_request_responses_trainer_id"), table_name="client_request_responses")
    op.drop_table("client_request_responses")
