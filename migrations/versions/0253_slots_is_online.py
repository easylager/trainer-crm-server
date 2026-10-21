"""slots.is_online — очный слот без площадки не равен онлайн-слоту.

NULL ``arena_id`` раньше означал «онлайн», если у тренера есть онлайн-услуга.
Так слоты тренера без катка, но с обычными услугами, молча уходили только на онлайн.

Колонка хранит формат явно.
Бэкфилл: venue-less слот остаётся онлайн, только если тренер уже мог выбрать
онлайн сознательно (есть привязанная площадка) или очных услуг у него нет.
Слоты без площадок при смеси услуг остаются очными (default false) — это и был
случай «добавил часы, а они сели на онлайн».
Групповой слот (есть service_id) берёт формат своей услуги.

Revision ID: 0253_slots_is_online
Revises: 0252_ice_invites_match
"""

from __future__ import annotations

from alembic import op

revision = "0253_slots_is_online"
down_revision = "0252_ice_invites_match"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE slots ADD COLUMN IF NOT EXISTS is_online BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        """
        UPDATE slots AS s
        SET is_online = true
        WHERE s.arena_id IS NULL
          AND s.service_id IS NULL
          AND (
            EXISTS (
              SELECT 1 FROM trainer_services ts
              WHERE ts.trainer_id = s.trainer_id
                AND COALESCE(ts.is_online, false)
            )
            OR EXISTS (
              SELECT 1 FROM trainers t
              WHERE t.id = s.trainer_id
                AND COALESCE(t.arena_work_format, '') = 'online'
            )
          )
          AND (
            EXISTS (
              SELECT 1 FROM trainer_arenas ta
              WHERE ta.trainer_id = s.trainer_id
            )
            OR NOT EXISTS (
              SELECT 1 FROM trainer_services ts
              WHERE ts.trainer_id = s.trainer_id
                AND NOT COALESCE(ts.is_online, false)
            )
          )
        """
    )
    # Групповой слот несёт свою услугу: формат — её, а не общий профиль тренера.
    op.execute(
        """
        UPDATE slots AS s
        SET is_online = true
        WHERE s.arena_id IS NULL
          AND s.service_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM trainer_services ts
            WHERE ts.trainer_id = s.trainer_id
              AND ts.service_id = s.service_id
              AND COALESCE(ts.is_online, false)
          )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE slots DROP COLUMN IF EXISTS is_online")
