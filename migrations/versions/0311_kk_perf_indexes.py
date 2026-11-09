"""«Кто кого» под нагрузкой: индексы под счётчики сторон, уведомления и короны игрока.

- ``ix_hockey_picks_match_side`` (match_id, side) — число людей за каждую сторону по списку матчей без
  чтения всей строки хода;
- ``ix_hockey_notices_sent_at`` — «кому сегодня уже писали» (фильтр по sent_at; прежний индекс начинается
  с player_key); частичный: итоги и переносы дневной бюджет не тратят, их в индексе нет;
- ``ix_hockey_notices_due_moved`` — очередь писем о переносе (kind moved/mvfree, ещё не отправлены);
  частичный, поэтому крошечный и не растёт с историей;
- ``ix_hockey_crowns_player`` — короны только у показанных на экране игроков.

Revision ID: 0311_kk_perf_indexes
Revises: 0310_admin_journey_hidden
"""

from __future__ import annotations

from alembic import op

revision = "0311_kk_perf_indexes"
down_revision = "0310_admin_journey_hidden"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_hockey_picks_match_side ON hockey_picks (match_id, side)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_hockey_notices_sent_at ON hockey_notices (sent_at, player_key)"
        " WHERE sent_at IS NOT NULL AND kind NOT IN ('result', 'moved', 'mvfree')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_hockey_notices_due_moved ON hockey_notices (match_id, player_key)"
        " WHERE kind IN ('moved', 'mvfree') AND sent_at IS NULL AND NOT failed"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_hockey_crowns_player ON hockey_crowns (player_key)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_hockey_crowns_player")
    op.execute("DROP INDEX IF EXISTS ix_hockey_notices_due_moved")
    op.execute("DROP INDEX IF EXISTS ix_hockey_notices_sent_at")
    op.execute("DROP INDEX IF EXISTS ix_hockey_picks_match_side")
