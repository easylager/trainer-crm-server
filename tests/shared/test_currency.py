from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.currency import (
    currency_for_country,
    get_city_currency_info,
    get_trainer_currency_info,
    resolve_currency,
    resolve_price_group,
)


def test_currency_for_country_pure():
    assert currency_for_country("BY") == "BYN"
    assert currency_for_country("RU") == "RUB"
    assert currency_for_country("ru") == "RUB"  # case-insensitive
    assert currency_for_country(None) == "BYN"
    assert currency_for_country("XX") == "BYN"  # unknown country defaults to BYN


async def _insert_city(db_session: AsyncSession, *, name: str, country: str, price_group: str) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO cities (name, country, price_group)
            VALUES (:name, :country, :price_group)
            RETURNING id
            """
        ),
        {"name": name, "country": country, "price_group": price_group},
    )
    return int(r.scalar_one())


async def _insert_trainer_with_city(db_session: AsyncSession, city_id: int | None) -> int:
    r = await db_session.execute(
        text("INSERT INTO trainers (status, schedule_grid_step_minutes) VALUES ('active', 15) RETURNING id")
    )
    trainer_id = int(r.scalar_one())
    await db_session.execute(
        text("INSERT INTO trainer_profiles (trainer_id, city_id) VALUES (:tid, :cid)"),
        {"tid": trainer_id, "cid": city_id},
    )
    return trainer_id


async def test_get_city_currency_info_by(db_session: AsyncSession):
    city_id = await _insert_city(db_session, name="Тестгород BY", country="BY", price_group="BY_BASE")
    currency, price_group = await get_city_currency_info(db_session, city_id)
    assert currency == "BYN"
    assert price_group == "BY_BASE"


async def test_get_city_currency_info_ru(db_session: AsyncSession):
    city_id = await _insert_city(db_session, name="Тестгород RU", country="RU", price_group="RU_BASE")
    currency, price_group = await get_city_currency_info(db_session, city_id)
    assert currency == "RUB"
    assert price_group == "RU_BASE"


async def test_get_city_currency_info_missing_city_defaults_to_by(db_session: AsyncSession):
    currency, price_group = await get_city_currency_info(db_session, 999_999_999)
    assert currency == "BYN"
    assert price_group == "BY_BASE"


async def test_get_city_currency_info_none_city_id_defaults_to_by(db_session: AsyncSession):
    currency, price_group = await get_city_currency_info(db_session, None)
    assert currency == "BYN"
    assert price_group == "BY_BASE"


async def test_resolve_currency_and_price_group_convenience_wrappers(db_session: AsyncSession):
    city_id = await _insert_city(db_session, name="Тестгород RU 2", country="RU", price_group="RU_MOSCOW")
    assert await resolve_currency(db_session, city_id) == "RUB"
    assert await resolve_price_group(db_session, city_id) == "RU_MOSCOW"


async def test_get_trainer_currency_info_resolves_via_own_city(db_session: AsyncSession):
    city_id = await _insert_city(db_session, name="Тестгород RU 3", country="RU", price_group="RU_BASE")
    trainer_id = await _insert_trainer_with_city(db_session, city_id)
    currency, price_group = await get_trainer_currency_info(db_session, trainer_id)
    assert currency == "RUB"
    assert price_group == "RU_BASE"


async def test_get_trainer_currency_info_no_city_defaults_to_by(db_session: AsyncSession):
    trainer_id = await _insert_trainer_with_city(db_session, None)
    currency, price_group = await get_trainer_currency_info(db_session, trainer_id)
    assert currency == "BYN"
    assert price_group == "BY_BASE"


async def test_get_trainer_currency_info_no_profile_row_defaults_to_by(db_session: AsyncSession):
    r = await db_session.execute(
        text("INSERT INTO trainers (status, schedule_grid_step_minutes) VALUES ('active', 15) RETURNING id")
    )
    trainer_id = int(r.scalar_one())
    currency, price_group = await get_trainer_currency_info(db_session, trainer_id)
    assert currency == "BYN"
    assert price_group == "BY_BASE"
