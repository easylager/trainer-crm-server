"""Add legal_documents and trainer_agreements tables for trainer terms."""

from alembic import op
import sqlalchemy as sa


revision = "0052_legal_documents_agreements"
down_revision = "0051_support_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("file_key", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_legal_documents_code_is_active",
        "legal_documents",
        ["code", "is_active"],
        unique=False,
    )

    op.create_table(
        "trainer_agreements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("accepted_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["legal_documents.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_trainer_agreements_trainer_id",
        "trainer_agreements",
        ["trainer_id"],
        unique=False,
    )
    op.create_index(
        "ix_trainer_agreements_document_id",
        "trainer_agreements",
        ["document_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_trainer_agreements_trainer_document",
        "trainer_agreements",
        ["trainer_id", "document_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_trainer_agreements_trainer_document", "trainer_agreements", type_="unique")
    op.drop_index("ix_trainer_agreements_document_id", table_name="trainer_agreements")
    op.drop_index("ix_trainer_agreements_trainer_id", table_name="trainer_agreements")
    op.drop_table("trainer_agreements")

    op.drop_index("ix_legal_documents_code_is_active", table_name="legal_documents")
    op.drop_table("legal_documents")


