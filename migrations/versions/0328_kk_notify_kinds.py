"""«Кто кого»: новые поводы уведомлений и согласие игрока (TASK-426, срезы 2–4).

Revision ID: 0328_kk_notify_kinds
Revises: 0327_kk_notify_journal
Create Date: 2026-11-16

* CHECK на ``hockey_notices.kind`` расширен новыми видами (колонка varchar(12)): ``invite`` — матч сегодня или завтра,
  ``comeback`` — возврат, ``week`` — итог недели, ``month`` — итог месяца, ``consent`` — вопрос о согласии
  после первого хода.
* ``hockey_player_prefs.notify_consent`` (nullable): ``NULL`` — не спрашивали, ``true`` — согласен, ``false`` —
  нажал «Не присылать». Игрокам, которые уже делали ходы и не выключили бота (``remind`` и нет блокировки), согласие
  ставится по умолчанию (решение владельца 2026-11-16), но только там, где ответа ещё нет: ``false`` и ``true``,
  уже записанные игроком, миграция не трогает. Для игроков с ходами без строки настроек строка создаётся.

Откат намеренно НЕ теряет данные: колонка ``notify_consent`` остаётся (ответы игроков не пропадают, а повторный
накат не обнуляет их), строки новых видов в ``hockey_notices`` не удаляются (иначе после повторного наката пропала
бы защита от повторной отправки). Прежний CHECK возвращается как ``NOT VALID``: старый код новые виды вставить не
сможет, а уже лежащие строки не мешают. Повторный накат пересоздаёт CHECK с новыми видами и проверяет все строки.
"""

from alembic import op

revision = "0328_kk_notify_kinds"
down_revision = "0327_kk_notify_journal"
branch_labels = None
depends_on = None

OLD_KINDS = ("before", "result", "nomove", "overtook", "mfinal", "moved", "mvfree", "rescore")
NEW_KINDS = ("invite", "comeback", "week", "month", "consent")


def _in(kinds: tuple[str, ...]) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade() -> None:
    op.execute("ALTER TABLE hockey_player_prefs ADD COLUMN IF NOT EXISTS notify_consent boolean")
    op.execute("ALTER TABLE hockey_notices DROP CONSTRAINT IF EXISTS ck_hockey_notices_kind")
    op.create_check_constraint("ck_hockey_notices_kind", "hockey_notices", _in(OLD_KINDS + NEW_KINDS))
    op.execute("""
        INSERT INTO hockey_player_prefs (player_key, notify_consent)
        SELECT DISTINCT player_key, true FROM hockey_picks
        ON CONFLICT (player_key) DO UPDATE
        SET notify_consent = CASE
            WHEN hockey_player_prefs.notify_consent IS NULL
                 AND hockey_player_prefs.remind AND hockey_player_prefs.bot_blocked_at IS NULL THEN true
            ELSE hockey_player_prefs.notify_consent END
        """)


def downgrade() -> None:
    # Данные не трогаем (см. докстринг): колонка и строки новых видов остаются, CHECK — мягкий.
    op.execute("ALTER TABLE hockey_notices DROP CONSTRAINT IF EXISTS ck_hockey_notices_kind")
    op.execute(f"ALTER TABLE hockey_notices ADD CONSTRAINT ck_hockey_notices_kind CHECK ({_in(OLD_KINDS)}) NOT VALID")
