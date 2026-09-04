"""City-driven currency and subscription price-group resolution (TASK-043).

``cities.country`` (``BY``/``RU``) drives which currency amounts are shown in
(``BYN``/``RUB``) and which currency is passed to the payment gateway.
``cities.price_group`` drives which row of the subscription pricing tables
(``subscription_tier_pricing``, ``subscription_tier_period_pricing``,
``subscription_module_period_pricing``) applies — see TASK-044 (RU pricing) and
TASK-045 (BY small-city discount) for the groups beyond the ``BY_BASE`` default.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CURRENCY_BY_COUNTRY: dict[str, str] = {"BY": "BYN", "RU": "RUB"}
DEFAULT_COUNTRY = "BY"
DEFAULT_CURRENCY = CURRENCY_BY_COUNTRY[DEFAULT_COUNTRY]
DEFAULT_PRICE_GROUP = "BY_BASE"


def currency_for_country(country: str | None) -> str:
    """Pure lookup — no DB. Unknown/missing country defaults to BYN (today's only market)."""
    return CURRENCY_BY_COUNTRY.get((country or "").upper(), DEFAULT_CURRENCY)


async def get_city_currency_info(session: AsyncSession, city_id: int | None) -> tuple[str, str]:
    """(currency, price_group) for a city id; defaults to BY/BYN/BY_BASE for None or unknown ids."""
    if city_id is None:
        return DEFAULT_CURRENCY, DEFAULT_PRICE_GROUP
    result = await session.execute(
        text("SELECT country, price_group FROM cities WHERE id = :cid"),
        {"cid": city_id},
    )
    row = result.fetchone()
    if not row:
        return DEFAULT_CURRENCY, DEFAULT_PRICE_GROUP
    return currency_for_country(row[0]), (row[1] or DEFAULT_PRICE_GROUP)


async def resolve_currency(session: AsyncSession, city_id: int | None) -> str:
    currency, _price_group = await get_city_currency_info(session, city_id)
    return currency


async def resolve_price_group(session: AsyncSession, city_id: int | None) -> str:
    _currency, price_group = await get_city_currency_info(session, city_id)
    return price_group


async def get_trainer_currency_info(session: AsyncSession, trainer_id: int) -> tuple[str, str]:
    """(currency, price_group) for a trainer, via ``trainer_profiles.city_id``.

    Falls back to BY/BYN/BY_BASE when the trainer has no profile row or no city set yet
    (e.g. onboarding in progress) — matches today's only-BYN behavior for those trainers.
    """
    result = await session.execute(
        text("""
            SELECT c.country, c.price_group
            FROM trainer_profiles tp
            LEFT JOIN cities c ON c.id = tp.city_id
            WHERE tp.trainer_id = :tid
        """),
        {"tid": trainer_id},
    )
    row = result.fetchone()
    if not row or row[0] is None:
        return DEFAULT_CURRENCY, DEFAULT_PRICE_GROUP
    return currency_for_country(row[0]), (row[1] or DEFAULT_PRICE_GROUP)


async def resolve_trainer_currency(session: AsyncSession, trainer_id: int) -> str:
    currency, _price_group = await get_trainer_currency_info(session, trainer_id)
    return currency


async def resolve_trainer_price_group(session: AsyncSession, trainer_id: int) -> str:
    _currency, price_group = await get_trainer_currency_info(session, trainer_id)
    return price_group
