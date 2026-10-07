"""TASK-201-A: allow hockey_practice (ОХМ) in ice_sessions.kind.

Revision ID: 0224_hockey_practice_kind
Revises: 0223_public_contact_click
"""

from __future__ import annotations

from alembic import op

revision = "0224_hockey_practice_kind"
down_revision = "0223_public_contact_click"
branch_labels = None
depends_on = None

_KIND_CHECK = (
    "kind IN ('public_skate', 'open_ice', 'rental', 'school_group', 'event', 'hockey_practice')"
)


def upgrade() -> None:
    op.drop_constraint("ck_ice_sessions_kind", "ice_sessions", type_="check")
    op.create_check_constraint("ck_ice_sessions_kind", "ice_sessions", _KIND_CHECK)


def downgrade() -> None:
    op.drop_constraint("ck_ice_sessions_kind", "ice_sessions", type_="check")
    op.create_check_constraint(
        "ck_ice_sessions_kind",
        "ice_sessions",
        "kind IN ('public_skate', 'open_ice', 'rental', 'school_group', 'event')",
    )
