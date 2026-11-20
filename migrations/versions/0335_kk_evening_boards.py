"""«Кто кого»: табло вечера — одно сообщение итогов на игрока и игровой день (PDEC-038, TASK-434).

Revision ID: 0335_kk_evening_boards
Revises: 0334_kk_league_outfits
Create Date: 2026-11-20

Только добавление: ``hockey_evening_boards`` (ключ ``player_key, day``) — сообщение-табло вечера в чате бота.
``message_id`` — его номер: следующие итоги вечера правят это сообщение, а не шлют новое (``NULL`` — табло ещё не
отправлено или вечер ушёл сразу итогом). ``closed_at`` — «Итог вечера» отправлен: вечер закрыт, табло больше не
правим. Защита от повтора самих итогов по-прежнему в ``hockey_notices`` (вид ``result``, строка на матч).

``hockey_notices.kind`` получает вид ``evening``: «Итог вечера» занимается строкой (игрок + якорный матч вечера)
и уходит ровно один раз.

Откат удаляет таблицу и строки ``evening``: это номер сообщения для правки и отметки рассылки, не результат игры.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0335_kk_evening_boards"
down_revision = "0334_kk_league_outfits"
branch_labels = None
depends_on = None

OLD_KINDS = (
    "before",
    "result",
    "nomove",
    "overtook",
    "mfinal",
    "moved",
    "mvfree",
    "rescore",
    "invite",
    "comeback",
    "week",
    "month",
    "consent",
    "lginvite",
)
NEW_KINDS = ("evening",)


def _in(kinds: tuple[str, ...]) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade() -> None:
    op.execute("ALTER TABLE hockey_notices DROP CONSTRAINT IF EXISTS ck_hockey_notices_kind")
    op.create_check_constraint("ck_hockey_notices_kind", "hockey_notices", _in(OLD_KINDS + NEW_KINDS))
    op.create_table(
        "hockey_evening_boards",
        sa.Column(
            "player_key",
            sa.BigInteger(),
            sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("hockey_evening_boards")
    op.execute("DELETE FROM hockey_notices WHERE kind = 'evening'")
    op.execute("ALTER TABLE hockey_notices DROP CONSTRAINT IF EXISTS ck_hockey_notices_kind")
    op.execute(f"ALTER TABLE hockey_notices ADD CONSTRAINT ck_hockey_notices_kind CHECK ({_in(OLD_KINDS)}) NOT VALID")
