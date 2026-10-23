"""One trainer plan (PDEC-025): 39 / 105 / 375 BYN, every module included.

Belarus price groups only. The CRM base row becomes the whole price; module surcharges go
to zero so the existing constructor arithmetic (base + modules) gives the single price, and
the online / analytics bundles stop being sold. BY_SMALL keeps its −15%. RU groups are a
separate decision and stay as they are.

Paid subscriptions and invoices are not touched — a trainer keeps what they paid for until
it ends. Downgrade restores the prices that were live on 2026-10-23.

Revision ID: 0260_single_trainer_plan
Revises: 0259_phone_is_contact
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0260_single_trainer_plan"
down_revision = "0259_phone_is_contact"
branch_labels = None
depends_on = None

_BY_GROUPS = ("BY_BASE", "BY_SMALL")

# price group → {period_months: cents}
_NEW_BASE = {
    "BY_BASE": {1: 3900, 3: 10500, 12: 37500},
    "BY_SMALL": {1: 3315, 3: 8925, 12: 31875},
}
_OLD_BASE = {
    "BY_BASE": {1: 2000, 3: 5400, 12: 19200},
    "BY_SMALL": {1: 1700, 3: 4590, 12: 16320},
}
# price group → module → {period_months: cents}
_OLD_MODULES = {
    "BY_BASE": {
        "online": {1: 1500, 3: 4050, 12: 14400},
        "analytics": {1: 500, 3: 1350, 12: 4800},
        "groups": {1: 500, 3: 1350, 12: 4800},
    },
    "BY_SMALL": {
        "online": {1: 1275, 3: 3442, 12: 12240},
        "analytics": {1: 425, 3: 1148, 12: 4080},
        "groups": {1: 425, 3: 1148, 12: 4080},
    },
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


def _set_base(conn, prices: dict, *, name: str, description: str, bullets: list[str]) -> None:
    for group, by_period in prices.items():
        for months, cents in by_period.items():
            conn.execute(
                sa.text(
                    "UPDATE subscription_tier_period_pricing SET price_cents = :c, updated_at = now() "
                    "WHERE tier = 'crm' AND price_group = :g AND period_months = :m"
                ),
                {"c": cents, "g": group, "m": months},
            )
        conn.execute(
            sa.text(
                "UPDATE subscription_tier_pricing SET price_cents = :c, name_ru = :n, short_description_ru = :d, "
                "bullets_json = CAST(:b AS jsonb), updated_at = now() WHERE tier = 'crm' AND price_group = :g"
            ),
            {"c": by_period[1], "n": name, "d": description, "b": json.dumps(bullets, ensure_ascii=False), "g": group},
        )


def upgrade() -> None:
    conn = op.get_bind()
    _set_base(conn, _NEW_BASE, name=_NEW_NAME, description=_NEW_DESCRIPTION, bullets=_NEW_BULLETS)
    conn.execute(
        sa.text("UPDATE subscription_module_period_pricing SET price_cents = 0 WHERE price_group = ANY(:g)"),
        {"g": list(_BY_GROUPS)},
    )
    conn.execute(
        sa.text(
            "UPDATE subscription_tier_pricing SET is_active = false, updated_at = now() "
            "WHERE tier IN ('online', 'analytics') AND price_group = ANY(:g)"
        ),
        {"g": list(_BY_GROUPS)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    _set_base(conn, _OLD_BASE, name=_OLD_NAME, description=_OLD_DESCRIPTION, bullets=_OLD_BULLETS)
    for group, modules in _OLD_MODULES.items():
        for module, by_period in modules.items():
            for months, cents in by_period.items():
                conn.execute(
                    sa.text(
                        "UPDATE subscription_module_period_pricing SET price_cents = :c "
                        "WHERE price_group = :g AND module = :mod AND period_months = :m"
                    ),
                    {"c": cents, "g": group, "mod": module, "m": months},
                )
    conn.execute(
        sa.text(
            "UPDATE subscription_tier_pricing SET is_active = true, updated_at = now() "
            "WHERE tier IN ('online', 'analytics') AND price_group = ANY(:g)"
        ),
        {"g": list(_BY_GROUPS)},
    )
