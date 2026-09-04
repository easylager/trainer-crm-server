"""BY small-city subscription discount (TASK-045): price_group 'BY_SMALL', -15%.

Reclassifies every active Belarusian city that is not Minsk or one of the 5 oblast
capitals (Гродно, Брест, Витебск, Гомель, Могилев) to ``price_group='BY_SMALL'`` — matched
by name, confirmed by the product owner 2026-09-04 (their first list omitted Vitebsk/Gomel
by oversight; both stay BY_BASE). Seeds BY_SMALL rows into the three pricing tables at 15%
off the BY_BASE price (product owner: "можно 15 процентов например пока поставить" — a
starting figure, not a final one). No new columns needed — reuses the ``price_group``
infrastructure from migration 0188 (TASK-043) / 0189 (TASK-044).

Revision ID: 0191_by_small_city_discount
Revises: 0190_client_edges_client_id
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa
import json


revision = "0191_by_small_city_discount"
down_revision = "0190_client_edges_client_id"
branch_labels = None
depends_on = None

_BY_CAPITAL_CITIES = ("Минск", "Гродно", "Брест", "Витебск", "Гомель", "Могилев")

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

# -15% off the current BY_BASE amounts (subscription_tier_pricing / _period_pricing).
_TIER_MONTHLY_CENTS = {"crm": 1700, "online": 2975, "analytics": 3400}
_TIER_PERIOD_CENTS = {
    "crm": {1: 1700, 3: 4590, 12: 16320},
    "online": {1: 2975, 3: 8032, 12: 28560},
    "analytics": {1: 3400, 3: 9180, 12: 32640},
}

_MODULE_NAME_RU = {
    "online": "Онлайн-запись в каталоге",
    "analytics": "Аналитика и отчёты",
    "groups": "Группы (когорты)",
}
_MODULE_PERIOD_CENTS = {
    "online": {1: 1275, 3: 3442, 12: 12240},
    "analytics": {1: 425, 3: 1148, 12: 4080},
    "groups": {1: 425, 3: 1148, 12: 4080},
}

_PERIOD_DAYS = {1: 30, 3: 90, 12: 365}


def upgrade() -> None:
    conn = op.get_bind()

    placeholders = ", ".join(f":cap{i}" for i in range(len(_BY_CAPITAL_CITIES)))
    params = {f"cap{i}": name for i, name in enumerate(_BY_CAPITAL_CITIES)}
    conn.execute(
        sa.text(f"""
            UPDATE cities
            SET price_group = 'BY_SMALL'
            WHERE country = 'BY' AND name NOT IN ({placeholders})
        """),
        params,
    )

    for tier, monthly_cents in _TIER_MONTHLY_CENTS.items():
        meta = _TIER_META[tier]
        conn.execute(
            sa.text("""
                INSERT INTO subscription_tier_pricing
                    (tier, price_group, price_cents, currency, period_days,
                     name_ru, short_description_ru, bullets_json, display_order, is_active)
                VALUES
                    (CAST(:tier AS subscription_tier_enum), 'BY_SMALL', :price_cents, 'BYN', 30,
                     :name_ru, :short_description_ru, CAST(:bullets_json AS jsonb), :display_order, true)
            """),
            {
                "tier": tier,
                "price_cents": monthly_cents,
                "name_ru": meta["name_ru"],
                "short_description_ru": meta["short_description_ru"],
                "bullets_json": json.dumps(meta["bullets"], ensure_ascii=False),
                "display_order": meta["display_order"],
            },
        )
        for months, cents in _TIER_PERIOD_CENTS[tier].items():
            conn.execute(
                sa.text("""
                    INSERT INTO subscription_tier_period_pricing
                        (tier, price_group, period_months, price_cents, period_days)
                    VALUES
                        (CAST(:tier AS subscription_tier_enum), 'BY_SMALL', :months, :price_cents, :days)
                """),
                {"tier": tier, "months": months, "price_cents": cents, "days": _PERIOD_DAYS[months]},
            )

    for module, by_months in _MODULE_PERIOD_CENTS.items():
        for months, cents in by_months.items():
            conn.execute(
                sa.text("""
                    INSERT INTO subscription_module_period_pricing
                        (module, price_group, period_months, price_cents, period_days, currency, name_ru)
                    VALUES
                        (:module, 'BY_SMALL', :months, :price_cents, :days, 'BYN', :name_ru)
                """),
                {
                    "module": module,
                    "months": months,
                    "price_cents": cents,
                    "days": _PERIOD_DAYS[months],
                    "name_ru": _MODULE_NAME_RU[module],
                },
            )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM subscription_module_period_pricing WHERE price_group = 'BY_SMALL'"))
    conn.execute(sa.text("DELETE FROM subscription_tier_period_pricing WHERE price_group = 'BY_SMALL'"))
    conn.execute(sa.text("DELETE FROM subscription_tier_pricing WHERE price_group = 'BY_SMALL'"))
    conn.execute(sa.text("UPDATE cities SET price_group = 'BY_BASE' WHERE price_group = 'BY_SMALL'"))
