"""«Кто кого»: право капитана — экипировка в лиге (TASK-432).

Revision ID: 0334_kk_league_outfits
Revises: 0333_kk_league_invite
Create Date: 2026-11-19

Только добавление: ``hockey_league_outfits`` — одна выдача за игровой день в лиге (ключ ``league_id, day``):
капитан вечера (``captain_key``) выдаёт вещь (``item``) любому участнику, в том числе себе. Выдачу можно поменять —
строка перезаписывается. Действительна ли она (капитан всё ещё капитан, получатель ещё в лиге, вечер — последний
сыгранный), решается при чтении. Лига или игрок ушли из базы — выдачи уходят каскадом.

Получателю — сообщение бота (вид ``outfit``): очередь прямо в строке выдачи (``notice_*``); новый получатель —
новое сообщение. ``hockey_player_prefs.notify_outfit`` (``NULL`` = включено) — «Не присылать такое».

Откат удаляет таблицу: экипировка — шутка вечера, не результат игры.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0334_kk_league_outfits"
down_revision = "0333_kk_league_invite"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hockey_league_outfits",
        sa.Column(
            "league_id", sa.BigInteger(), sa.ForeignKey("hockey_leagues.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column(
            "captain_key",
            sa.BigInteger(),
            sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_key", sa.BigInteger(), sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("item", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("notice_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notice_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notice_failed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("ALTER TABLE hockey_player_prefs ADD COLUMN IF NOT EXISTS notify_outfit boolean")
    # Карточка экипировки для чата — в воронке карточек отдельной строкой.
    op.drop_constraint("ck_hockey_card_events_card", "hockey_card_events", type_="check")
    op.create_check_constraint(
        "ck_hockey_card_events_card", "hockey_card_events", "card IN ('result', 'league', 'crown', 'outfit')"
    )
    # Ключ (league_id, day) обслуживает чтение; индексы ниже — для каскадного удаления игрока.
    op.create_index("ix_hockey_league_outfits_to", "hockey_league_outfits", ["to_key"])
    op.create_index("ix_hockey_league_outfits_captain", "hockey_league_outfits", ["captain_key"])


def downgrade() -> None:
    op.execute("DELETE FROM hockey_card_events WHERE card = 'outfit'")
    op.drop_constraint("ck_hockey_card_events_card", "hockey_card_events", type_="check")
    op.create_check_constraint(
        "ck_hockey_card_events_card", "hockey_card_events", "card IN ('result', 'league', 'crown')"
    )
    op.execute("ALTER TABLE hockey_player_prefs DROP COLUMN IF EXISTS notify_outfit")
    op.drop_index("ix_hockey_league_outfits_captain", table_name="hockey_league_outfits")
    op.drop_index("ix_hockey_league_outfits_to", table_name="hockey_league_outfits")
    op.drop_table("hockey_league_outfits")
