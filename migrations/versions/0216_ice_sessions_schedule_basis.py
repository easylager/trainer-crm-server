"""TASK-179: schedule_basis on ice_sessions (live / projected / photo / manual)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0216_ice_sessions_schedule_basis"
down_revision = "0216_ice_ops_alerts"
branch_labels = None
depends_on = None

_BASIS_CHECK = "schedule_basis IN ('live', 'projected', 'photo', 'manual')"

_PROJECTED_KEYS = ("brest_lds_v1", "zamok_html_v1")
_PHOTO_KEYS = ("lida_lds_v1", "junost_instagram_caption_v1")


def upgrade() -> None:
    op.add_column(
        "ice_sessions",
        sa.Column(
            "schedule_basis",
            sa.String(length=16),
            nullable=False,
            server_default="live",
        ),
    )
    op.create_check_constraint("ck_ice_sessions_schedule_basis", "ice_sessions", _BASIS_CHECK)
    op.execute(
        """
        UPDATE ice_sessions
        SET schedule_basis = 'manual'
        WHERE source_id = 'admin' OR source_id LIKE 'etalon_%'
        """
    )
    op.execute(
        f"""
        UPDATE ice_sessions s
        SET schedule_basis = 'projected'
        FROM ice_parser_jobs j
        WHERE j.arena_id = s.arena_id
          AND j.parser_key IN ({", ".join(repr(k) for k in _PROJECTED_KEYS)})
          AND s.kind IN ('public_skate', 'open_ice')
          AND s.schedule_basis = 'live'
        """
    )
    op.execute(
        f"""
        UPDATE ice_sessions s
        SET schedule_basis = 'photo'
        FROM ice_parser_jobs j
        WHERE j.arena_id = s.arena_id
          AND j.parser_key IN ({", ".join(repr(k) for k in _PHOTO_KEYS)})
          AND s.kind IN ('public_skate', 'open_ice')
          AND s.schedule_basis = 'live'
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_ice_sessions_schedule_basis", "ice_sessions", type_="check")
    op.drop_column("ice_sessions", "schedule_basis")
