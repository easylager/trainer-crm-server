import pytest
from sqlalchemy import text

from src.application import place_suggestion_city_search as cs
from src.application.place_suggestion_city_search import search_cities

CITY = "Пситестоград"


@pytest.fixture
async def our_city(db_session, monkeypatch):
    monkeypatch.setenv("ICE_DISCOVERY_COUNTRIES", "BY,RU")
    row = (await db_session.execute(text("SELECT id FROM cities WHERE name = :n"), {"n": CITY})).fetchone()
    if row:
        cid = int(row[0])
        await db_session.execute(
            text("UPDATE cities SET is_active = true, country = 'BY', region = 'Минская область' WHERE id = :id"),
            {"id": cid},
        )
    else:
        cid = int((await db_session.execute(text(
            "INSERT INTO cities (name, sort_order, is_active, country, region, latitude, longitude) "
            "VALUES (:n, 1, true, 'BY', 'Минская область', 53.9, 27.56) RETURNING id"
        ), {"n": CITY})).scalar_one())
    await db_session.commit()
    return cid


async def _geocode_must_not_run(_q):
    raise AssertionError("geocoder called")


@pytest.mark.asyncio
async def test_our_city_found_by_prefix(db_session, our_city):
    items = await search_cities(db_session, CITY[:5].lower(), geocode=lambda q: _geo([]))
    hit = next(i for i in items if i["city_id"] == our_city)
    assert hit["name"] == CITY and hit["country"] == "BY" and hit["is_new"] is False
    assert hit["region"] == "Минская область"


@pytest.mark.asyncio
async def test_short_query_skips_geocoder(db_session, our_city):
    items = await search_cities(db_session, CITY[:1], geocode=_geocode_must_not_run)
    assert all(not i["is_new"] for i in items)


@pytest.mark.asyncio
async def test_geocoder_duplicate_of_our_city_is_dropped(db_session, our_city):
    geo = [
        {"city_id": None, "name": CITY, "region": "Минская", "country": "BY", "lat": 1.0, "lon": 2.0, "is_new": True},
        {"city_id": None, "name": CITY, "region": "Псковская", "country": "RU", "lat": 3.0, "lon": 4.0, "is_new": True},
    ]
    items = await search_cities(db_session, CITY, geocode=lambda q: _geo(geo))
    assert [i for i in items if i["is_new"]] == [geo[1]]
    assert len(items) <= 6


@pytest.mark.asyncio
async def test_geocoder_failure_returns_only_ours(db_session, our_city):
    async def boom(_q):
        raise RuntimeError("nominatim down")

    items = await search_cities(db_session, CITY, geocode=boom)
    assert [i["city_id"] for i in items] == [our_city]


async def _geo(items):
    return items


@pytest.mark.asyncio
async def test_nominatim_parses_caches_and_throttles(monkeypatch):
    calls = []

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {"lat": "54.73", "lon": "55.96",
                 "address": {"city": "Уфа", "state": "Башкортостан", "country_code": "ru"}},
                {"lat": "1", "lon": "2", "address": {"country_code": "ru"}},  # без города — мимо
            ]

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None):
            calls.append((url, params, headers))
            return FakeResp()

    monkeypatch.setattr(cs.httpx, "AsyncClient", FakeClient)
    cs._cache.clear()
    monkeypatch.setattr(cs, "_last_request_at", 0.0)

    first = await cs.nominatim_cities("Уфа")
    assert first == [{"city_id": None, "name": "Уфа", "region": "Башкортостан", "country": "RU",
                      "lat": 54.73, "lon": 55.96, "is_new": True}]
    assert calls[0][1]["featureType"] == "city"
    assert "TrainerCRM" in calls[0][2]["User-Agent"]

    assert await cs.nominatim_cities("уфа") == first  # кэш, без запроса
    assert len(calls) == 1

    assert await cs.nominatim_cities("Казань") == []  # тот же момент — лимит 1 запрос/с
    assert len(calls) == 1


def test_cache_evicts_expired_and_caps_size(monkeypatch):
    cs._cache.clear()
    monkeypatch.setattr(cs, "CACHE_MAX_ENTRIES", 3)
    cs._cache_put("old", 0.0, [])
    now = cs.CACHE_TTL_SEC + 10
    cs._cache_put("a", now, [])
    assert "old" not in cs._cache
    cs._cache_put("b", now, [])
    cs._cache_put("c", now, [])
    cs._cache_put("d", now, [])
    assert list(cs._cache) == ["b", "c", "d"]
    cs._cache.clear()
