"""Открытка «Зови» на домашний матч Динамо (TASK-304).

``ice_invites.match_id``
    На что зовёт открытка, если это не сеанс льда: домашний матч (``hockey_matches``).
    ``ON DELETE SET NULL`` — как у ``session_id``: открытка держит снимок времени и арены
    и после удаления строки читается состоянием «gone».

``ice_invites.kind`` += ``hockey_match``
    Вид приглашения; сеансовые виды не трогаем.

``ck_ice_invites_one_target``
    Не оба сразу: ``session_id`` и ``match_id`` не бывают заполнены вместе. «Ровно один»
    CHECK не выразит, потому что оба ссылочных поля обнуляются каскадом (``SET NULL``), когда
    сеанс или матч уходит. «Ровно один при создании» держит ``create_invite``.

Revision ID: 0252_ice_invites_match
Revises: 0251_hockey_player_prefs
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0252_ice_invites_match"
down_revision = "0251_hockey_player_prefs"
branch_labels = None
depends_on = None

# Держать в синхроне с src/infrastructure/db/models.py (_INVITE_KIND_CHECK).
_KIND_NEW = "kind IN ('public_skate', 'open_ice', 'hockey_practice', 'hockey_match')"
_KIND_OLD = "kind IN ('public_skate', 'open_ice', 'hockey_practice')"


def upgrade() -> None:
    op.add_column(
        "ice_invites",
        sa.Column(
            "match_id",
            sa.Integer(),
            sa.ForeignKey("hockey_matches.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_ice_invites_match_id", "ice_invites", ["match_id"])
    op.drop_constraint("ck_ice_invites_kind", "ice_invites", type_="check")
    op.create_check_constraint("ck_ice_invites_kind", "ice_invites", _KIND_NEW)
    op.create_check_constraint("ck_ice_invites_one_target", "ice_invites", "session_id IS NULL OR match_id IS NULL")


def downgrade() -> None:
    # Открытки на матч не превращаем молча в сеансовые: откат упадёт, пока они есть.
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE ice_invites IN ACCESS EXCLUSIVE MODE"))
    has_match = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM ice_invites WHERE kind = 'hockey_match')")
    ).scalar_one()
    if has_match:
        raise RuntimeError("Cannot downgrade 0252_ice_invites_match: ice_invites contains kind='hockey_match' rows.")
    op.drop_constraint("ck_ice_invites_one_target", "ice_invites", type_="check")
    op.drop_constraint("ck_ice_invites_kind", "ice_invites", type_="check")
    op.create_check_constraint("ck_ice_invites_kind", "ice_invites", _KIND_OLD)
    op.drop_index("ix_ice_invites_match_id", table_name="ice_invites")
    op.drop_column("ice_invites", "match_id")
