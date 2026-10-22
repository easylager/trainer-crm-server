"""Карточка катка v2 на сайте: блоки по данным админки, порядок, разметка для поиска."""

from __future__ import annotations

import json
import re
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_arenas import _minsk_today
from tests.api.test_public_place_page import _place
from tests.api.test_site_trainers import _trainer_on

VISIT = {
    "tickets": {"mode": "box_office", "open": "12:30", "close": "21:00", "card": True, "cash": True},
    "child_age_max": 14,
    "facts": {"locker_rooms": {"state": "yes"}, "lockers": {"state": "no"}, "warmth": {"state": "cool"}},
    "services": [{"kind": "sharpening", "price": "8 BYN"}, {"kind": "aid", "price": "5 BYN"}],
    "rental": {"sizes": "26–47"},
    "school": {"age_from": 4, "rows": [{"label": "Занятие, 15 минут", "child": "10 BYN", "adult": "15 BYN"}]},
    "passes": {"columns": ["Детский", "Взрослый"], "rows": [{"label": "4", "values": ["15 BYN", "22 BYN"]}]},
    "rink_rental": {"rows": [{"label": "Только лёд", "minutes": 60, "price": "240 BYN"}]},
}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _rink(db_session, *, visit: dict, ohm: bool = False) -> dict:
    place = await _place(db_session, name="Ледовый дворец Островец", website_url="https://ostrovets.example")
    await db_session.execute(
        text("UPDATE arena_profiles SET visit_info = CAST(:v AS jsonb) WHERE arena_id = :a"),
        {"v": json.dumps(visit), "a": place["arena_id"]},
    )
    for d in range(1, 3):
        await create_ice_session(
            db_session, place["arena_id"], local_date=_minsk_today() + timedelta(days=d), starts_at_local="18:00",
            duration_minutes=45, price_adult_minor=800, price_child_minor=500, price_rental_minor=700,
        )
        if ohm:
            await create_ice_session(
                db_session, place["arena_id"], local_date=_minsk_today() + timedelta(days=d), starts_at_local="22:00",
                duration_minutes=60, kind="hockey_practice", price_adult_minor=1500,
            )
    await db_session.commit()
    return place


def _section_ids(html: str) -> list[str]:
    """Блоки страницы по порядку. «plan» — заготовка выбранного сеанса, скрыта до тапа."""
    return [i for i in re.findall(r'<section class="b-sec[^"]*" id="([a-z]+)"', html) if i != "plan"]


@pytest.mark.asyncio
async def test_small_rink_gets_blocks_in_fixed_order_without_trainers(app_use_test_db, db_session) -> None:
    place = await _rink(db_session, visit=VISIT)
    async with _client() as client:
        html = (await client.get(place["path"])).text
    assert _section_ids(html) == ["schedule", "facts", "services", "more", "contacts"]
    # Обложка: чипы вместо блока «Как добраться».
    chips = re.search(r'<div class="b-hero__chips">(.*?)</div>', html, re.S).group(1)
    assert ">Маршрут<" in chips and ">Телефон<" in chips and ">Сайт<" in chips and "startapp=arena_" in chips
    schedule = html.split('id="schedule"', 1)[1].split("</section>", 1)[0]
    assert '<b class="b-price__v">8 BYN</b>' in schedule and "до 14 лет" in schedule and "размеры 26–47" in schedule
    assert "Взрослому с прокатом — 15 BYN." in schedule
    assert "<b>Билеты только в кассе</b> · касса 12:30–21:00 · карта, наличные" in schedule
    services = html.split('id="services"', 1)[1].split("</section>", 1)[0]
    assert services.index("Опора «пингвин»") < services.index("Заточка")  # пингвин первым
    assert 'class="b-penguin"' in services
    more = html.split('id="more"', 1)[1].split("</section>", 1)[0]
    # Подробности свёрнуты, но лежат в разметке — их видит поисковик.
    assert "Научиться кататься" in more and "<td>10 BYN</td>" in more
    assert "от 15 BYN за 4 катания" in more and "<td>22 BYN</td>" in more
    assert "Снять лёд целиком" in more and "240 BYN" in more
    assert "data-coach-open" in more  # нет тренеров — вход для тренера здесь


@pytest.mark.asyncio
async def test_trainers_take_the_school_and_coach_entry(app_use_test_db, db_session) -> None:
    place = await _rink(db_session, visit=VISIT)
    async with _client() as client:
        await _trainer_on(db_session, client, place, first_name="Анна")
        html = (await client.get(place["path"])).text
    assert _section_ids(html) == ["schedule", "facts", "services", "trainers", "more", "contacts"]
    trainers = html.split('id="trainers"', 1)[1].split("</section>", 1)[0]
    assert "Школа катка" in trainers and "data-coach-open" in trainers
    more = html.split('id="more"', 1)[1].split("</section>", 1)[0]
    assert "Научиться кататься" not in more and "data-coach-open" not in more


@pytest.mark.asyncio
async def test_ohm_is_a_tab_of_the_ice_block(app_use_test_db, db_session) -> None:
    place = await _rink(db_session, visit=VISIT, ohm=True)
    async with _client() as client:
        html = (await client.get(place["path"])).text
    assert 'id="ohm"' in html and "<h2 class=\"b-h2\">На льду</h2>" in html
    assert 'id="icetab-skate"' in html and 'class="b-pane b-pane--ohm"' in html
    assert _section_ids(html)[0] == "schedule"


@pytest.mark.asyncio
async def test_search_markup_carries_prices_and_amenities(app_use_test_db, db_session) -> None:
    place = await _rink(db_session, visit=VISIT)
    async with _client() as client:
        html = (await client.get(place["path"])).text
    desc = re.search(r'<meta name="description" content="([^"]*)"', html).group(1)
    assert "Вход 8 BYN, детский 5 BYN, прокат 7 BYN" in desc and "Билеты в кассе" in desc
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1))
    features = {f["name"]: f["value"] for f in ld["amenityFeature"]}
    assert features == {"Раздевалка": True, "Камеры хранения": False}
    assert ld["paymentAccepted"] == "Cash, Credit Card"
    offers = [o["itemOffered"]["name"] for o in ld["hasOfferCatalog"]["itemListElement"]]
    assert offers == ["Опора «пингвин»", "Заточка"]


@pytest.mark.asyncio
async def test_same_day_kassa_opens_a_sheet_when_today_has_no_sessions(app_use_test_db, db_session) -> None:
    place = await _rink(db_session, visit={"tickets": {"mode": "same_day"}})
    await db_session.execute(
        text("UPDATE arena_profiles SET tickets_url = 'https://kassa.example/buy' WHERE arena_id = :a"),
        {"a": place["arena_id"]},
    )
    await db_session.commit()
    async with _client() as client:
        html = (await client.get(place["path"])).text
    schedule = html.split('id="schedule"', 1)[1].split("</section>", 1)[0]
    assert 'class="b-buypill"' in schedule and "data-sameday-open" in schedule
    assert "Онлайн-билет появится в день сеанса" in schedule and "Напомнить в Telegram" in schedule
    assert "Онлайн продают только в день сеанса." in schedule
