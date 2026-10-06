"""TASK-196 AC-2 (API): цены услуг тренера приходят в валюте его города.

Тренер из Санкт-Петербурга (cities.country='RU') видит и показывает цены в RUB,
минский — в BYN. Валюта не хранится на услуге: она вычисляется из города
тренера (BY → BYN, RU → RUB) — той же моделью, что и у сеансов льда
(currency_code на каждой цене).
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.db_catalog_helpers import require_seed_service_id


async def _insert_city(db_session, *, country: str) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO cities (name, country, price_group, is_active)
            VALUES (:name, :c, :pg, true)
            RETURNING id
            """
        ),
        {
            "name": f"CurCity-{country}-{uuid.uuid4().hex[:6]}",
            "c": country,
            "pg": "BY_BASE" if country == "BY" else "RU_BASE",
        },
    )
    return int(r.scalar_one())


async def _create_listed_trainer(
    client: AsyncClient,
    db_session,
    *,
    city_id: int,
    service_id: int,
    price_cents: int,
) -> int:
    body = {
        "profile": {"first_name": "Валюта", "last_name": "Тестова", "age": 28, "city_id": city_id},
        "service_ids": [service_id],
    }
    r = await client.post("/api/trainers", json=body)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    st = await client.patch(f"/api/trainers/{tid}/status", json={"status": "active"})
    assert st.status_code == 200, st.text
    # Каталог оп-ин (0182): выкатываем карточку в SQL — окно рейт-лимитов у суиты одно.
    await db_session.execute(
        text("UPDATE trainers SET is_catalog_visible = true, catalog_state = 'published' WHERE id = :tid"),
        {"tid": tid},
    )
    await db_session.execute(
        text("UPDATE trainer_services SET price_cents = :pc WHERE trainer_id = :tid AND service_id = :sid"),
        {"pc": price_cents, "tid": tid, "sid": service_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_service_price_variants
                (trainer_id, service_id, label, price_cents, sort_order, tier_kind)
            VALUES (:tid, :sid, 'Взрослый', :pc, 0, 'adult')
            """
        ),
        {"pc": price_cents, "tid": tid, "sid": service_id},
    )
    await db_session.commit()
    return tid


def _our_service(item: dict, service_id: int) -> dict:
    services = item["services"]
    svc = next(s for s in services if s["service_id"] == service_id)
    assert svc["price_tiers"], "услуги без тиров не проверяют валюту тира"
    return svc


@pytest.mark.asyncio
async def test_ru_city_trainer_prices_come_in_rub(app_use_test_db, db_session) -> None:
    service_id = await require_seed_service_id(db_session)
    ru_city = await _insert_city(db_session, country="RU")
    by_city = await _insert_city(db_session, country="BY")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ru_tid = await _create_listed_trainer(
            client, db_session, city_id=ru_city, service_id=service_id, price_cents=400000
        )
        by_tid = await _create_listed_trainer(
            client, db_session, city_id=by_city, service_id=service_id, price_cents=400000
        )

        # Список каталога (то, что читает клиентский каталог и вкладка «Лёд»).
        listing = await client.get("/api/public/trainers", params={"city_id": ru_city, "limit": 200})
        assert listing.status_code == 200, listing.text
        ru_item = next(it for it in listing.json()["items"] if it["id"] == ru_tid)
        svc = _our_service(ru_item, service_id)
        assert svc["currency_code"] == "RUB"
        assert svc["price_byn_min"] == 4000.0  # поле легаси-имени, цифры без валюты
        assert svc["price_tiers"][0]["currency_code"] == "RUB"

        # Карточка тренера (тиры для диалога записи — catalog-main tier radio).
        detail = await client.get(f"/api/public/trainers/{ru_tid}")
        assert detail.status_code == 200, detail.text
        dsvc = _our_service(detail.json(), service_id)
        assert dsvc["currency_code"] == "RUB"
        assert dsvc["price_tiers"][0]["currency_code"] == "RUB"

        # Контроль: минский тренер в той же выдаче — по-прежнему BYN.
        by_listing = await client.get("/api/public/trainers", params={"city_id": by_city, "limit": 200})
        assert by_listing.status_code == 200, by_listing.text
        by_item = next(it for it in by_listing.json()["items"] if it["id"] == by_tid)
        assert _our_service(by_item, service_id)["currency_code"] == "BYN"
