"""Площадки перестают быть только льдом, а тренеры — только тренерами.

Пять колонок, ни одной новой таблицы — всё вешается на существующие сущности.

``arenas.venue_type``
    Лёд становится частным случаем, а не синонимом площадки. Дефолт ``ice``
    сохраняет поведение для всех 200+ существующих арен, заведённых до того,
    как тип вообще спрашивали.

``trainer_profiles.specialist_role``
    Свободный текст, а не enum: к нам идут не только тренеры по конькам, и
    угадать список ролей заранее нельзя. UI подсказывает чипсами, но не
    ограничивает — см. ``src/shared/specialist_roles.py``.

``trainer_profiles.online_enabled``
    Независимый флаг, а НЕ ``trainers.arena_work_format='online'``. Тот —
    fallback «площадки нет вообще» и взаимоисключает физическую арену;
    консультант с залом и онлайном через него невыразим.

``trainer_profiles.onboarding_completed_at``
    Отличает «ещё не настраивал» от «настроил и сознательно оставил расписание
    пустым». Без этого хаб читает пустую неделю как незаконченный онбординг и
    требует её заполнить — сразу после того, как экран сказал, что она
    необязательна. Вывести из других полей нельзя: пустая неделя не оставляет
    следов, а услуги и длительность есть и у тренера, созданного на сайте.

``services.created_by_trainer_id`` / ``services.is_public``
    Услуга, добавленная тренером, живёт в той же таблице (переиспользуем
    ``trainer_services``, фильтры, абонементы), но ``is_public=false`` держит
    её вне общего фильтра каталога до модерации. Тот же приём, что у
    ``arenas.created_by_trainer_id`` + ``is_confirmed``.

Revision ID: 0206_venue_types_and_specialists
Revises: 0205_client_merges_audit
"""
from alembic import op
import sqlalchemy as sa


revision = "0206_venue_types_and_specialists"
down_revision = "0205_client_merges_audit"
branch_labels = None
depends_on = None

# Держать в синхроне с src/shared/venue_types.py (VENUE_TYPE_KEYS).
VENUE_TYPES = ("ice", "gym", "choreo", "pool", "outdoor", "other")


def upgrade() -> None:
    op.add_column(
        "arenas",
        sa.Column("venue_type", sa.String(16), nullable=False, server_default="ice"),
    )
    op.create_check_constraint(
        "ck_arenas_venue_type",
        "arenas",
        "venue_type IN ('ice', 'gym', 'choreo', 'pool', 'outdoor', 'other')",
    )
    op.create_index("ix_arenas_venue_type", "arenas", ["venue_type"])

    op.add_column(
        "trainer_profiles",
        sa.Column("specialist_role", sa.String(64), nullable=True),
    )
    op.add_column(
        "trainer_profiles",
        sa.Column(
            "online_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "trainer_profiles",
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Бэкфилл: у кого есть недельный шаблон — тот онбординг уже прошёл. Это ровно
    # та проверка, которой пользовался бот (`trainer_has_weekly_template`), пока
    # отметки не было. Без бэкфилла колонка у всех существующих тренеров осталась бы
    # пустой, и хаб предлагал бы им настройку заново, стоит расписанию опустеть.
    # Момент берём за now(): настоящее время онбординга не сохранилось нигде, а
    # колонка нужна как флаг, не как аналитика.
    op.execute(
        sa.text(
            """
            UPDATE trainer_profiles p
            SET onboarding_completed_at = now()
            WHERE p.onboarding_completed_at IS NULL
              AND EXISTS (
                  SELECT 1 FROM trainer_schedule_templates t
                  WHERE t.trainer_id = p.trainer_id
              )
            """
        )
    )

    op.add_column(
        "services",
        sa.Column("created_by_trainer_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_services_created_by_trainer",
        "services",
        "trainers",
        ["created_by_trainer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "services",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("services", "is_public")
    op.drop_constraint("fk_services_created_by_trainer", "services", type_="foreignkey")
    op.drop_column("services", "created_by_trainer_id")

    op.drop_column("trainer_profiles", "onboarding_completed_at")
    op.drop_column("trainer_profiles", "online_enabled")
    op.drop_column("trainer_profiles", "specialist_role")

    op.drop_index("ix_arenas_venue_type", table_name="arenas")
    op.drop_constraint("ck_arenas_venue_type", "arenas", type_="check")
    op.drop_column("arenas", "venue_type")
