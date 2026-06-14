"""Collective center sessions + bookings (ADR-003 W2 studio_central)."""

from alembic import op
import sqlalchemy as sa

revision = "0167_collective_sessions_w2"
down_revision = "0166_collective_invoices"
branch_labels = None
depends_on = None

SCHEDULE_MODES = ("member_autonomous", "studio_central")
ATTENDANCE_MODES = (
    "lane_self",
    "lane_with_guest",
    "lane_own_coach",
    "center_coach_individual",
    "center_coach_pair",
)
BOOKING_STATUSES = ("pending", "confirmed", "completed", "cancelled", "declined", "no_show")


def upgrade() -> None:
    op.add_column(
        "collectives",
        sa.Column(
            "schedule_mode",
            sa.String(32),
            nullable=False,
            server_default="member_autonomous",
        ),
    )
    op.create_check_constraint(
        "ck_collectives_schedule_mode",
        "collectives",
        "schedule_mode IN ('member_autonomous', 'studio_central')",
    )

    op.create_table(
        "collective_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "collective_id",
            sa.Integer(),
            sa.ForeignKey("collectives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slot_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "arena_id",
            sa.Integer(),
            sa.ForeignKey("arenas.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="available"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("capacity >= 1 AND capacity <= 500", name="ck_collective_sessions_capacity"),
        sa.CheckConstraint(
            "status IN ('available', 'cancelled')",
            name="ck_collective_sessions_status",
        ),
    )
    op.create_index(
        "ix_collective_sessions_collective_date",
        "collective_sessions",
        ["collective_id", "slot_date"],
    )

    op.create_table(
        "collective_session_coaches",
        sa.Column(
            "collective_session_id",
            sa.Integer(),
            sa.ForeignKey("collective_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "trainer_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_collective_session_coaches_trainer_id",
        "collective_session_coaches",
        ["trainer_id"],
    )

    op.create_table(
        "collective_session_bookings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "collective_session_id",
            sa.Integer(),
            sa.ForeignKey("collective_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collective_id",
            sa.Integer(),
            sa.ForeignKey("collectives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trainer_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attendance_mode", sa.String(40), nullable=False),
        sa.Column(
            "center_coach_id",
            sa.Integer(),
            sa.ForeignKey("trainers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("guest_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("booking_price_cents", sa.Integer(), nullable=False),
        sa.Column("client_comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_by_trainer_id", sa.Integer(), sa.ForeignKey("trainers.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"attendance_mode IN ({', '.join(repr(m) for m in ATTENDANCE_MODES)})",
            name="ck_collective_session_bookings_mode",
        ),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in BOOKING_STATUSES)})",
            name="ck_collective_session_bookings_status",
        ),
        sa.CheckConstraint("guest_count >= 0 AND guest_count <= 20", name="ck_collective_session_bookings_guests"),
    )
    op.create_index(
        "ix_collective_session_bookings_session_id",
        "collective_session_bookings",
        ["collective_session_id"],
    )
    op.create_index(
        "ix_collective_session_bookings_collective_id",
        "collective_session_bookings",
        ["collective_id"],
    )
    op.create_index(
        "ix_collective_session_bookings_client_id",
        "collective_session_bookings",
        ["client_id"],
    )


def downgrade() -> None:
    op.drop_table("collective_session_bookings")
    op.drop_table("collective_session_coaches")
    op.drop_table("collective_sessions")
    op.drop_constraint("ck_collectives_schedule_mode", "collectives", type_="check")
    op.drop_column("collectives", "schedule_mode")
