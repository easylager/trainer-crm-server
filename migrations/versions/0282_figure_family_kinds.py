"""Allow figure_free and family_skate in ice_sessions.kind.

«Свободное фигурное катание» и «Семейное массовое катание» СДЮШОР Минск — отдельные вкладки на
странице арены. Раньше они схлопывались в open_ice / public_skate и не отличались от обычного
массового катания.

Revision ID: 0282_figure_family_kinds
Revises: 0280_extraliga_matches
"""

from __future__ import annotations

from alembic import op

revision = "0282_figure_family_kinds"
down_revision = "0280_extraliga_matches"
branch_labels = None
depends_on = None

_KIND_CHECK = (
    "kind IN ('public_skate', 'open_ice', 'rental', 'school_group', 'event', "
    "'hockey_practice', 'figure_free', 'family_skate')"
)


def upgrade() -> None:
    op.drop_constraint("ck_ice_sessions_kind", "ice_sessions", type_="check")
    op.create_check_constraint("ck_ice_sessions_kind", "ice_sessions", _KIND_CHECK)


def downgrade() -> None:
    # Строки новых видов не укладываются в прежнее ограничение — убираем их перед откатом.
    op.execute("DELETE FROM ice_sessions WHERE kind IN ('figure_free', 'family_skate')")
    op.drop_constraint("ck_ice_sessions_kind", "ice_sessions", type_="check")
    op.create_check_constraint(
        "ck_ice_sessions_kind",
        "ice_sessions",
        "kind IN ('public_skate', 'open_ice', 'rental', 'school_group', 'event', 'hockey_practice')",
    )
