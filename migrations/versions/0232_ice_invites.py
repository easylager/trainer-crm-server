"""Invite cards for a real public session (TASK-231).

One row in ice_invites, many rows in ice_invite_answers. session_id is
ON DELETE SET NULL because publish drops ice_sessions that leave the schedule.
The card keeps arena_id, kind, and the UTC window. The status key is stored
as sha256 only.

Revision ID: 0232_ice_invites
Revises: 0231_rental_section_copy
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0232_ice_invites"
down_revision = "0231_rental_section_copy"
branch_labels = None
depends_on = None

_CODE_CHECK = "code ~ '^[23456789abcdefghjkmnpqrstuvwxyz]{8}$'"
_KIND_CHECK = "kind IN ('public_skate', 'open_ice', 'hockey_practice')"


def upgrade() -> None:
    op.create_table(
        "ice_invites",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("status_key_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("ice_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "arena_id",
            sa.Integer(),
            sa.ForeignKey("arenas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("starts_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("to_name", sa.String(length=20), nullable=True),
        sa.Column("from_name", sa.String(length=20), nullable=False),
        sa.Column("show_price", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("parent_code", sa.String(length=8), nullable=True),
        sa.Column("creator_actor_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("first_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_CODE_CHECK, name="ck_ice_invites_code"),
        sa.CheckConstraint(_KIND_CHECK, name="ck_ice_invites_kind"),
        sa.CheckConstraint(
            "char_length(from_name) BETWEEN 1 AND 20",
            name="ck_ice_invites_from_name",
        ),
        sa.CheckConstraint(
            "to_name IS NULL OR char_length(to_name) BETWEEN 1 AND 20",
            name="ck_ice_invites_to_name",
        ),
        sa.UniqueConstraint("code", name="uq_ice_invites_code"),
    )
    op.create_index("ix_ice_invites_parent_code", "ice_invites", ["parent_code"])
    op.create_index("ix_ice_invites_created_at", "ice_invites", ["created_at"])
    op.create_index("ix_ice_invites_session_id", "ice_invites", ["session_id"])
    op.create_table(
        "ice_invite_answers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "invite_id",
            sa.BigInteger(),
            sa.ForeignKey("ice_invites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("responder_key", sa.String(length=64), nullable=False),
        sa.Column("responder_actor_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "answered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("tries", sa.SmallInteger(), nullable=False),
        sa.Column("resist_ms", sa.Integer(), nullable=False),
        sa.Column("falls", sa.SmallInteger(), nullable=False),
        sa.Column("tricked", sa.Boolean(), nullable=False),
        sa.CheckConstraint("tries BETWEEN 0 AND 10", name="ck_ice_invite_answers_tries"),
        sa.CheckConstraint(
            "resist_ms BETWEEN 0 AND 600000",
            name="ck_ice_invite_answers_resist",
        ),
        sa.CheckConstraint("falls BETWEEN 0 AND 5", name="ck_ice_invite_answers_falls"),
        sa.UniqueConstraint(
            "invite_id",
            "responder_key",
            name="uq_ice_invite_answers_invite_responder",
        ),
    )


def downgrade() -> None:
    op.drop_table("ice_invite_answers")
    op.drop_index("ix_ice_invites_session_id", table_name="ice_invites")
    op.drop_index("ix_ice_invites_created_at", table_name="ice_invites")
    op.drop_index("ix_ice_invites_parent_code", table_name="ice_invites")
    op.drop_table("ice_invites")
