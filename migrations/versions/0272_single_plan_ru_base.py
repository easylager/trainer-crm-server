"""One trainer plan for St. Petersburg (RU_BASE): 1150 / 3105 / 11040 RUB, every module included.

Same shape as 0260 for Belarus: the CRM base row becomes the whole price, module surcharges go
to zero, and the online / analytics bundles stop being sold. 1150 RUB is the owner's decision
(2026-10-26); the 3- and 12-month prices follow PDEC-025 (−10% / −20%). RU_MOSCOW is a separate
decision and stays as it is.

Paid subscriptions and invoices are not touched. Downgrade restores the prices live on 2026-10-26.

Revision ID: 0272_single_plan_ru_base
Revises: 0271_hockey_double_and_reminders
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0272_single_plan_ru_base"
down_revision = "0271_hockey_double_and_reminders"
branch_labels = None
depends_on = None

_GROUP = "RU_BASE"
_NEW_BASE = {1: 115000, 3: 310500, 12: 1104000}
_OLD_BASE = {1: 59000, 3: 159300, 12: 566400}
_OLD_MODULES = {
    "online": {1: 43000, 3: 115000, 12: 409000},
    "analytics": {1: 15000, 3: 39000, 12: 139000},
    "groups": {1: 15000, 3: 39000, 12: 139000},
}

_NEW_NAME = "Подписка Glide"
_NEW_DESCRIPTION = "Всё включено: ученики сами записываются в ваши окна — с катка и по вашей ссылке."
_NEW_BULLETS = [
    "«Записаться» на карточке в каталоге и запись по ссылке",
    "Напоминания ученикам и родителям",
    "Абонементы и сертификаты с автосписанием",
    "Группы и индивидуальные занятия",
    "Клиентская база, заметки, аналитика",
]
_OLD_NAME = "CRM"
_OLD_DESCRIPTION = "Базовый функционал для работы с клиентами"
_OLD_BULLETS = ["Расписание и шаблоны", "Ручная запись клиентов", "Ведение клиентской базы", "Абонементы и сертификаты"]


def _set_base(conn, prices: dict[int, int], *, name: str, description: str, bullets: list[str]) -> None:
    for months, cents in prices.items():
        conn.execute(
            sa.text(
                "UPDATE subscription_tier_period_pricing SET price_cents = :c, updated_at = now() "
                "WHERE tier = 'crm' AND price_group = :g AND period_months = :m"
            ),
            {"c": cents, "g": _GROUP, "m": months},
        )
    conn.execute(
        sa.text(
            "UPDATE subscription_tier_pricing SET price_cents = :c, name_ru = :n, short_description_ru = :d, "
            "bullets_json = CAST(:b AS jsonb), updated_at = now() WHERE tier = 'crm' AND price_group = :g"
        ),
        {"c": prices[1], "n": name, "d": description, "b": json.dumps(bullets, ensure_ascii=False), "g": _GROUP},
    )


def upgrade() -> None:
    conn = op.get_bind()
    _set_base(conn, _NEW_BASE, name=_NEW_NAME, description=_NEW_DESCRIPTION, bullets=_NEW_BULLETS)
    conn.execute(
        sa.text("UPDATE subscription_module_period_pricing SET price_cents = 0 WHERE price_group = :g"),
        {"g": _GROUP},
    )
    conn.execute(
        sa.text(
            "UPDATE subscription_tier_pricing SET is_active = false, updated_at = now() "
            "WHERE tier IN ('online', 'analytics') AND price_group = :g"
        ),
        {"g": _GROUP},
    )


def downgrade() -> None:
    conn = op.get_bind()
    _set_base(conn, _OLD_BASE, name=_OLD_NAME, description=_OLD_DESCRIPTION, bullets=_OLD_BULLETS)
    for module, by_period in _OLD_MODULES.items():
        for months, cents in by_period.items():
            conn.execute(
                sa.text(
                    "UPDATE subscription_module_period_pricing SET price_cents = :c "
                    "WHERE price_group = :g AND module = :mod AND period_months = :m"
                ),
                {"c": cents, "g": _GROUP, "mod": module, "m": months},
            )
    conn.execute(
        sa.text(
            "UPDATE subscription_tier_pricing SET is_active = true, updated_at = now() "
            "WHERE tier IN ('online', 'analytics') AND price_group = :g"
        ),
        {"g": _GROUP},
    )
