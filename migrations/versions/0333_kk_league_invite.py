"""«Кто кого»: еженедельное приглашение собрать лигу (TASK-431).

Revision ID: 0333_kk_league_invite
Revises: 0332_kk_league_src
Create Date: 2026-11-18

* CHECK на ``hockey_notices.kind`` расширен видом ``lginvite`` — фото-приглашение «Собери лигу» по пятницам
  игрокам без лиги (серия из трёх недель).
* ``hockey_player_prefs.notify_lginvite`` (nullable, ``NULL`` = включено): кнопка «Не присылать» под приглашением
  выключает только этот вид.

Откат, как у 0328, данных не теряет: колонка и строки ``lginvite`` остаются (иначе после повторного наката серия
началась бы заново), прежний CHECK возвращается как ``NOT VALID``.
"""

from alembic import op

revision = "0333_kk_league_invite"
down_revision = "0332_kk_league_src"
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
)
NEW_KINDS = ("lginvite",)


def _in(kinds: tuple[str, ...]) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade() -> None:
    op.execute("ALTER TABLE hockey_player_prefs ADD COLUMN IF NOT EXISTS notify_lginvite boolean")
    op.execute("ALTER TABLE hockey_notices DROP CONSTRAINT IF EXISTS ck_hockey_notices_kind")
    op.create_check_constraint("ck_hockey_notices_kind", "hockey_notices", _in(OLD_KINDS + NEW_KINDS))


def downgrade() -> None:
    op.execute("ALTER TABLE hockey_notices DROP CONSTRAINT IF EXISTS ck_hockey_notices_kind")
    op.execute(f"ALTER TABLE hockey_notices ADD CONSTRAINT ck_hockey_notices_kind CHECK ({_in(OLD_KINDS)}) NOT VALID")
