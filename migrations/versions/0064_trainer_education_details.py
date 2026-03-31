"""Structured trainer education entries and moderation audit."""

from alembic import op
import sqlalchemy as sa


revision = "0064_trainer_education_details"
down_revision = "0063_certificate_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_education",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("education_type", sa.Enum("formal_education", "course_or_certificate", name="trainer_education_type_enum", create_constraint=True), nullable=False),
        sa.Column("institution_name", sa.String(length=160), nullable=False),
        sa.Column("program_or_title", sa.String(length=180), nullable=False),
        sa.Column("degree_level", sa.String(length=64), nullable=True),
        sa.Column("country", sa.String(length=64), nullable=True),
        sa.Column("city", sa.String(length=64), nullable=True),
        sa.Column("start_year", sa.Integer(), nullable=True),
        sa.Column("end_year", sa.Integer(), nullable=True),
        sa.Column("is_in_progress", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("document_url", sa.String(length=512), nullable=True),
        sa.Column(
            "moderation_status",
            sa.Enum("pending_moderation", "approved", "rejected", name="trainer_education_moderation_status_enum", create_constraint=True),
            server_default="pending_moderation",
            nullable=False,
        ),
        sa.Column("moderation_comment", sa.String(length=500), nullable=True),
        sa.Column("approved_snapshot", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("supersedes_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["trainer_education.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_trainer_education_trainer_status_updated",
        "trainer_education",
        ["trainer_id", "moderation_status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "idx_trainer_education_pending",
        "trainer_education",
        ["moderation_status", "created_at"],
        unique=False,
    )
    op.create_table(
        "trainer_education_moderation_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_education_id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["trainer_education_id"], ["trainer_education.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trainer_education_moderation_events_trainer_education_id",
        "trainer_education_moderation_events",
        ["trainer_education_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trainer_education_moderation_events_trainer_education_id",
        table_name="trainer_education_moderation_events",
    )
    op.drop_table("trainer_education_moderation_events")
    op.drop_index("idx_trainer_education_pending", table_name="trainer_education")
    op.drop_index("idx_trainer_education_trainer_status_updated", table_name="trainer_education")
    op.drop_table("trainer_education")
    sa.Enum(name="trainer_education_moderation_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="trainer_education_type_enum").drop(op.get_bind(), checkfirst=True)
