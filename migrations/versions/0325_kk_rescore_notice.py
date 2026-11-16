"""«Кто кого»: повод rescore — исправление уже разосланного итога.

Revision ID: 0325_kk_rescore_notice
Revises: 0324_scrub_ops_blurb
Create Date: 2026-11-16

Итог матча поправили после рассылки (kind='result' ушёл с неверным счётом) → игроку уходит одно сообщение
«Мы ошиблись с итогом…». Строка hockey_notices kind='rescore' — и «занято» (один раз на игрока и матч), и
очередь доставки (sent_at IS NULL), как у 'moved'. Старый счёт и старые очки нужны для текста, поэтому в
таблицу добавлена nullable-колонка payload (jsonb); существующие строки не меняются.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0325_kk_rescore_notice"
down_revision = "0324_scrub_ops_blurb"
branch_labels = None
depends_on = None

KINDS = ("before", "result", "nomove", "overtook", "mfinal", "moved", "mvfree", "rescore")
OLD_KINDS = ("before", "result", "nomove", "overtook", "mfinal", "moved", "mvfree")


def _in(kinds: tuple[str, ...]) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade() -> None:
    op.add_column("hockey_notices", sa.Column("payload", postgresql.JSONB(), nullable=True))
    op.drop_constraint("ck_hockey_notices_kind", "hockey_notices", type_="check")
    op.create_check_constraint("ck_hockey_notices_kind", "hockey_notices", _in(KINDS))


def downgrade() -> None:
    op.execute("DELETE FROM hockey_notices WHERE kind = 'rescore'")
    op.drop_constraint("ck_hockey_notices_kind", "hockey_notices", type_="check")
    op.create_check_constraint("ck_hockey_notices_kind", "hockey_notices", _in(OLD_KINDS))
    op.drop_column("hockey_notices", "payload")
