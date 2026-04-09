"""Training groups (cohorts): tables + slots.training_group_id.

Revision ID: 0088
Revises: 0087
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trainer_id", sa.Integer(), sa.ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("max_members", sa.Integer(), nullable=False, server_default="10"),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("season_start_date", sa.Date(), nullable=True),
        sa.Column("catalog_visible", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("catalog_pitch", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_training_groups_trainer_id", "training_groups", ["trainer_id"])
    op.create_index("ix_training_groups_trainer_status", "training_groups", ["trainer_id", "status"])

    op.create_table(
        "training_group_schedule_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "training_group_id",
            sa.Integer(),
            sa.ForeignKey("training_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_of_week", sa.Integer(), nullable=False),  # 0=Mon .. 6=Sun
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="60"),
    )
    op.create_index(
        "ix_tg_schedule_rules_group",
        "training_group_schedule_rules",
        ["training_group_id"],
    )

    op.create_table(
        "training_group_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "training_group_id",
            sa.Integer(),
            sa.ForeignKey("training_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("training_group_id", "client_id", name="uq_training_group_member"),
    )
    op.create_index("ix_tg_members_group", "training_group_members", ["training_group_id"])
    op.create_index("ix_tg_members_client", "training_group_members", ["client_id"])

    op.create_table(
        "training_group_join_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "training_group_id",
            sa.Integer(),
            sa.ForeignKey("training_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_tg_join_group", "training_group_join_requests", ["training_group_id"])
    op.create_index("ix_tg_join_client", "training_group_join_requests", ["client_id"])
    op.create_index("ix_tg_join_status", "training_group_join_requests", ["training_group_id", "status"])

    op.add_column(
        "slots",
        sa.Column("training_group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_slots_training_group_id",
        "slots",
        "training_groups",
        ["training_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_slots_training_group_id", "slots", ["training_group_id"])


def downgrade() -> None:
    op.drop_index("ix_slots_training_group_id", table_name="slots")
    op.drop_constraint("fk_slots_training_group_id", "slots", type_="foreignkey")
    op.drop_column("slots", "training_group_id")

    op.drop_index("ix_tg_join_status", table_name="training_group_join_requests")
    op.drop_index("ix_tg_join_client", table_name="training_group_join_requests")
    op.drop_index("ix_tg_join_group", table_name="training_group_join_requests")
    op.drop_table("training_group_join_requests")

    op.drop_index("ix_tg_members_client", table_name="training_group_members")
    op.drop_index("ix_tg_members_group", table_name="training_group_members")
    op.drop_table("training_group_members")

    op.drop_index("ix_tg_schedule_rules_group", table_name="training_group_schedule_rules")
    op.drop_table("training_group_schedule_rules")

    op.drop_index("ix_training_groups_trainer_status", table_name="training_groups")
    op.drop_index("ix_training_groups_trainer_id", table_name="training_groups")
    op.drop_table("training_groups")
