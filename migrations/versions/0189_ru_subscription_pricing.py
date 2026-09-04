"""RU subscription pricing (TASK-044): RU_BASE (СПб/ЛО) and RU_MOSCOW (Москва/МО).

Seeds RUB rows into the three pricing tables that TASK-043 widened with ``price_group``
(migration 0188). Moscow/MO is reclassified from ``RU_BASE`` (TASK-043's blanket default
for both RU cities) to ``RU_MOSCOW`` — the +25% premium price_group confirmed by the
product owner (2026-09-04).

Amounts: RU_BASE computed from current BY_BASE monthly prices × ~28.35 RUB/BYN
(2026-09-03 rate), rounded; RU_MOSCOW = RU_BASE × 1.25, rounded. 3/12-month tier prices use
the same discount schedule as the existing BY seed (migration 0069): 3mo = monthly × 3 ×
0.9, 12mo = monthly × 12 × 0.8. Module period prices (1/3/12 months) are the values
proposed and accepted in TASK-044's task file directly (not further derived).

These are starting figures pending real-world confirmation once RU trainers exist — not
claimed as final/perfect. See ``.ai/tasks/TASK-044-ru-subscription-pricing.md``.

Revision ID: 0189_ru_subscription_pricing
Revises: 0188_currency_by_city_foundation
Create Date: 2026-09-04
"""
import json

from alembic import op
import sqlalchemy as sa


revision = "0189_ru_subscription_pricing"
down_revision = "0188_currency_by_city_foundation"
branch_labels = None
depends_on = None


_TIER_META = {
    "crm": {
        "name_ru": "CRM",
        "short_description_ru": "Базовый функционал для работы с клиентами",
        "bullets": [
            "Расписание и шаблоны",
            "Ручная запись клиентов",
            "Ведение клиентской базы",
            "Абонементы и сертификаты",
        ],
        "display_order": 1,
    },
    "online": {
        "name_ru": "Онлайн-запись",
        "short_description_ru": "Клиенты записываются сами через каталог",
        "bullets": ["Всё из CRM", "Самостоятельная запись клиентов", "Уведомления о записях"],
        "display_order": 2,
    },
    "analytics": {
        "name_ru": "Аналитика",
        "short_description_ru": "Отчёты и финансовая аналитика",
        "bullets": [
            "Всё из Онлайн-записи",
            "Статистика записей",
            "Финансовые отчёты",
            "Выгрузка данных",
        ],
        "display_order": 3,
    },
}

# price_group -> tier -> monthly price_cents
_TIER_MONTHLY_CENTS = {
    "RU_BASE": {"crm": 59000, "online": 99000, "analytics": 115000},
    "RU_MOSCOW": {"crm": 75000, "online": 125000, "analytics": 145000},
}

_MODULE_NAME_RU = {
    "online": "Онлайн-запись в каталоге",
    "analytics": "Аналитика и отчёты",
    "groups": "Группы (когорты)",
}

# price_group -> module -> {period_months: price_cents}
_MODULE_PERIOD_CENTS = {
    "RU_BASE": {
        "online": {1: 43000, 3: 115000, 12: 409000},
        "analytics": {1: 15000, 3: 39000, 12: 139000},
        "groups": {1: 15000, 3: 39000, 12: 139000},
    },
    "RU_MOSCOW": {
        "online": {1: 55000, 3: 145000, 12: 510000},
        "analytics": {1: 19000, 3: 49000, 12: 175000},
        "groups": {1: 19000, 3: 49000, 12: 175000},
    },
}

_PERIOD_DAYS = {1: 30, 3: 90, 12: 365}


def _tier_period_cents(monthly: int, months: int) -> int:
    if months == 1:
        return monthly
    if months == 3:
        return round(monthly * 3 * 0.9)
    if months == 12:
        return round(monthly * 12 * 0.8)
    raise ValueError(months)


def upgrade() -> None:
    conn = op.get_bind()

    # Moscow/MO gets its own premium price_group; TASK-043 defaulted both RU cities to RU_BASE.
    conn.execute(sa.text("UPDATE cities SET price_group = 'RU_MOSCOW' WHERE name = 'Москва/МО'"))

    for price_group, tiers in _TIER_MONTHLY_CENTS.items():
        for tier, monthly_cents in tiers.items():
            meta = _TIER_META[tier]
            conn.execute(
                sa.text("""
                    INSERT INTO subscription_tier_pricing
                        (tier, price_group, price_cents, currency, period_days,
                         name_ru, short_description_ru, bullets_json, display_order, is_active)
                    VALUES
                        (CAST(:tier AS subscription_tier_enum), :price_group, :price_cents, 'RUB', 30,
                         :name_ru, :short_description_ru, CAST(:bullets_json AS jsonb), :display_order, true)
                """),
                {
                    "tier": tier,
                    "price_group": price_group,
                    "price_cents": monthly_cents,
                    "name_ru": meta["name_ru"],
                    "short_description_ru": meta["short_description_ru"],
                    "bullets_json": json.dumps(meta["bullets"], ensure_ascii=False),
                    "display_order": meta["display_order"],
                },
            )
            for months in (1, 3, 12):
                conn.execute(
                    sa.text("""
                        INSERT INTO subscription_tier_period_pricing
                            (tier, price_group, period_months, price_cents, period_days)
                        VALUES
                            (CAST(:tier AS subscription_tier_enum), :price_group, :months, :price_cents, :days)
                    """),
                    {
                        "tier": tier,
                        "price_group": price_group,
                        "months": months,
                        "price_cents": _tier_period_cents(monthly_cents, months),
                        "days": _PERIOD_DAYS[months],
                    },
                )

    for price_group, modules in _MODULE_PERIOD_CENTS.items():
        for module, by_months in modules.items():
            for months, cents in by_months.items():
                conn.execute(
                    sa.text("""
                        INSERT INTO subscription_module_period_pricing
                            (module, price_group, period_months, price_cents, period_days, currency, name_ru)
                        VALUES
                            (:module, :price_group, :months, :price_cents, :days, 'RUB', :name_ru)
                    """),
                    {
                        "module": module,
                        "price_group": price_group,
                        "months": months,
                        "price_cents": cents,
                        "days": _PERIOD_DAYS[months],
                        "name_ru": _MODULE_NAME_RU[module],
                    },
                )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM subscription_module_period_pricing WHERE price_group IN ('RU_BASE', 'RU_MOSCOW')"
        )
    )
    conn.execute(
        sa.text(
            "DELETE FROM subscription_tier_period_pricing WHERE price_group IN ('RU_BASE', 'RU_MOSCOW')"
        )
    )
    conn.execute(
        sa.text("DELETE FROM subscription_tier_pricing WHERE price_group IN ('RU_BASE', 'RU_MOSCOW')")
    )
    conn.execute(sa.text("UPDATE cities SET price_group = 'RU_BASE' WHERE name = 'Москва/МО'"))
