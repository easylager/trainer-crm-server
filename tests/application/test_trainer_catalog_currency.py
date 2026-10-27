"""Превью каталога у тренера пишет цену в валюте его города: Питер — «руб.», Беларусь — «BYN»."""

from __future__ import annotations

import pytest

from src.application.trainer_catalog_view import _money_ru, _service_line_ru
from src.shared.currency import currency_label_ru


def test_currency_label_for_people():
    assert currency_label_ru("RUB") == "руб."
    assert currency_label_ru("rub") == "руб."
    assert currency_label_ru("BYN") == "BYN"
    assert currency_label_ru(None) == "BYN"


@pytest.mark.parametrize(
    ("currency", "expected"),
    [("BYN", "Обучение катанию «с нуля»: от 2500 BYN"), ("RUB", "Обучение катанию «с нуля»: от 2500 руб.")],
)
def test_service_line_uses_the_trainers_currency(currency, expected):
    services = [{"service_name": "Обучение катанию «с нуля»", "price_byn_min": 2500, "price_byn_max": 3000}]
    assert _service_line_ru(services, currency) == expected


def test_default_is_byn_and_fractions_survive():
    assert _service_line_ru([{"service_name": "Лёд", "price_cents": 3350}]) == "Лёд: 33.50 BYN"
    assert _money_ru(1200, "RUB") == "1200 руб."
    assert _service_line_ru([{"service_name": "Лёд"}], "RUB") == "Лёд: по запросу"


@pytest.mark.asyncio
async def test_a_trainer_from_a_russian_city_is_resolved_to_rub(db_session):
    from sqlalchemy import text

    from src.shared.currency import resolve_trainer_currency

    await db_session.execute(text("INSERT INTO cities (id, name, country, is_active) VALUES (9971, 'ТестПитер', 'RU', true)"))
    await db_session.execute(text("INSERT INTO cities (id, name, country, is_active) VALUES (9972, 'ТестМинск', 'BY', true)"))
    tid = {}
    for key, cid in (("ru", 9971), ("by", 9972)):
        tid[key] = (
            await db_session.execute(
                text("INSERT INTO trainers (telegram_id) VALUES (:t) RETURNING id"), {"t": 990000 + cid}
            )
        ).scalar_one()
        await db_session.execute(
            text("INSERT INTO trainer_profiles (trainer_id, city_id) VALUES (:t, :c)"), {"t": tid[key], "c": cid}
        )
    assert await resolve_trainer_currency(db_session, tid["ru"]) == "RUB"
    assert await resolve_trainer_currency(db_session, tid["by"]) == "BYN"


@pytest.mark.asyncio
async def test_month_revenue_carries_the_trainers_currency(db_session):
    from sqlalchemy import text

    from src.application.stats_use_cases import get_trainer_hub_revenue_month_to_date

    await db_session.execute(text("INSERT INTO cities (id, name, country, is_active) VALUES (9973, 'ТестПитер2', 'RU', true)"))
    tid = (await db_session.execute(text("INSERT INTO trainers (telegram_id) VALUES (990973) RETURNING id"))).scalar_one()
    await db_session.execute(text("INSERT INTO trainer_profiles (trainer_id, city_id) VALUES (:t, 9973)"), {"t": tid})
    out = await get_trainer_hub_revenue_month_to_date(db_session, tid)
    assert out["currency"] == "RUB" and "revenue_total_cents" in out
