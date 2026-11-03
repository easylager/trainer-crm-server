"""«Кто кого»: повод moved — ход аннулирован переносом матча (аудит игры, п.2).

Revision ID: 0303_kk_moved_notice
Revises: 0302_slot_dedupe
Create Date: 2026-11-03

Матч перенесли → ходы, сделанные после нового срока закрытия, удаляются из hockey_picks
(on_match_moved). Игрок этого не видит: заходит — хода нет. Теперь при переносе пишется
строка hockey_notices kind='moved' (или 'mvfree' — матч с козырем ушёл в неделю, где козырь
уже стоит, козырь вернулся): она же и «занято» (claim-семантика таблицы), и очередь —
доставка подбирает строки с sent_at IS NULL. Сообщение разово, настройками не глушится —
игрок должен узнать, что его ход отменили.
"""

from alembic import op

revision = "0303_kk_moved_notice"
down_revision = "0302_slot_dedupe"
branch_labels = None
depends_on = None

KINDS = ("before", "result", "nomove", "overtook", "mfinal", "moved", "mvfree")
OLD_KINDS = ("before", "result", "nomove", "overtook", "mfinal")


def _in(kinds: tuple[str, ...]) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_hockey_notices_kind", "hockey_notices", type_="check")
    op.create_check_constraint("ck_hockey_notices_kind", "hockey_notices", _in(KINDS))


def downgrade() -> None:
    op.execute("DELETE FROM hockey_notices WHERE kind IN ('moved', 'mvfree')")
    op.drop_constraint("ck_hockey_notices_kind", "hockey_notices", type_="check")
    op.create_check_constraint("ck_hockey_notices_kind", "hockey_notices", _in(OLD_KINDS))
