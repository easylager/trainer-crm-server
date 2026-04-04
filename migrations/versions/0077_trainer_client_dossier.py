"""Trainer client dossier: structured profile fields, entries timeline, and tags.

Extends the simple note field into a full client dossier system:
- Profile fields (goals, limitations, level) in trainer_client_notes
- Timeline of dated entries in trainer_client_entries
- Quick-access tags in trainer_client_tags

Revision ID: 0077_trainer_client_dossier
Revises: 0076_trainer_primary_arena
"""

from alembic import op
import sqlalchemy as sa


revision = "0077_trainer_client_dossier"
down_revision = "0076_trainer_primary_arena"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extend trainer_client_notes with profile fields
    op.add_column(
        "trainer_client_notes",
        sa.Column("goals", sa.Text(), nullable=True),
    )
    op.add_column(
        "trainer_client_notes",
        sa.Column("limitations", sa.Text(), nullable=True),
    )
    op.add_column(
        "trainer_client_notes",
        sa.Column("level", sa.Text(), nullable=True),
    )

    # Timeline entries (dated notes after sessions)
    op.create_table(
        "trainer_client_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "trainer_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_trainer_client_entries_trainer_client",
        "trainer_client_entries",
        ["trainer_id", "client_id"],
    )
    op.create_index(
        "ix_trainer_client_entries_created_at",
        "trainer_client_entries",
        ["created_at"],
    )

    # Quick-access tags
    op.create_table(
        "trainer_client_tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "trainer_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag", sa.String(100), nullable=False),
        sa.Column(
            "category",
            sa.String(50),
            nullable=True,
        ),  # injury, goal, level, schedule, custom
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_trainer_client_tags_trainer_client",
        "trainer_client_tags",
        ["trainer_id", "client_id"],
    )
    # Prevent duplicate tags for same trainer+client
    op.create_unique_constraint(
        "uq_trainer_client_tags_trainer_client_tag",
        "trainer_client_tags",
        ["trainer_id", "client_id", "tag"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_trainer_client_tags_trainer_client_tag",
        "trainer_client_tags",
        type_="unique",
    )
    op.drop_index("ix_trainer_client_tags_trainer_client", table_name="trainer_client_tags")
    op.drop_table("trainer_client_tags")

    op.drop_index("ix_trainer_client_entries_created_at", table_name="trainer_client_entries")
    op.drop_index(
        "ix_trainer_client_entries_trainer_client", table_name="trainer_client_entries"
    )
    op.drop_table("trainer_client_entries")

    op.drop_column("trainer_client_notes", "level")
    op.drop_column("trainer_client_notes", "limitations")
    op.drop_column("trainer_client_notes", "goals")
