"""Allow long public-skating windows («с 11:45 до 16:30, билет на час») in ice_sessions.

Обычный сеанс — 30–120 минут. Окно свободного катания длиннее (до 8 часов, ночные
катания) допускается только для массовых видов и только с price_note: клиент должен
видеть, на сколько его билет, а не думать, что 600 ₽ — за всё окно.

Revision ID: 0314_ice_sessions_open_window
Revises: 0313_spb_rink_cards_batch1
"""

from __future__ import annotations

from alembic import op

revision = "0314_ice_sessions_open_window"
down_revision = "0313_spb_rink_cards_batch1"
branch_labels = None
depends_on = None

_MINUTES = "EXTRACT(EPOCH FROM (ends_at_utc - starts_at_utc)) / 60"
_SESSION_CHECK = f"{_MINUTES} BETWEEN 30 AND 120"
_WINDOW_CHECK = (
    f"{_SESSION_CHECK} OR (kind IN ('public_skate', 'open_ice', 'family_skate') "
    f"AND btrim(coalesce(price_note, '')) <> '' AND {_MINUTES} > 120 AND {_MINUTES} <= 480)"
)


def upgrade() -> None:
    op.drop_constraint("ck_ice_sessions_duration", "ice_sessions", type_="check")
    op.create_check_constraint("ck_ice_sessions_duration", "ice_sessions", _WINDOW_CHECK)


def downgrade() -> None:
    # Окна не укладываются в старое правило — удаляем их, иначе constraint не создать.
    op.execute(f"DELETE FROM ice_sessions WHERE NOT ({_SESSION_CHECK})")
    op.drop_constraint("ck_ice_sessions_duration", "ice_sessions", type_="check")
    op.create_check_constraint("ck_ice_sessions_duration", "ice_sessions", _SESSION_CHECK)
