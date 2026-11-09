"""«Кто кого»: рекламная метка источника.

- ``hockey_players.first_src`` — метка, с которой человек сделал самый первый ход (kks_<метка>, ?src=);
  пишется один раз при создании игрока и больше не меняется;
- ``hockey_entry_events`` — заходы по метке без ключа игрока: только метка и время, чтобы считать
  охват рекламной ссылки, не привязывая его к человеку.

Revision ID: 0312_kk_promo_src
Revises: 0311_kk_perf_indexes
"""

from __future__ import annotations

from alembic import op

revision = "0312_kk_promo_src"
down_revision = "0311_kk_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE hockey_players ADD COLUMN IF NOT EXISTS first_src VARCHAR(16)")
    # Частичный: у подавляющего большинства игроков метки нет, индекс остаётся крошечным.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_hockey_players_first_src ON hockey_players (first_src)"
        " WHERE first_src IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS hockey_entry_events (
            id BIGSERIAL PRIMARY KEY,
            src VARCHAR(16) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_hockey_entry_events_src ON hockey_entry_events (src, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hockey_entry_events")
    op.execute("DROP INDEX IF EXISTS ix_hockey_players_first_src")
    op.execute("ALTER TABLE hockey_players DROP COLUMN IF EXISTS first_src")
