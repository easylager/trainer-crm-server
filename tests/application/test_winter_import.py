"""Импорт seed сезонных точек: план и запись (TASK-343)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from src.application.winter_import import NEMIGA_SLUG, import_points, plan_rows

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)


def row(**kw):
    base = {
        "city": "Тестоград", "district": "", "name": "", "address": "", "hours": "", "phone": "",
        "type": "каток", "paid": "", "price": "", "lat": "", "lon": "", "geocode_precision": "none",
        "source_url": "https://example.test/a.pdf", "source_season": "2025/26", "confidence": "high",
    }
    base.update(kw)
    return base


def test_empty_name_is_generated_and_school_moves_to_operator():
    p = plan_rows([
        row(type="хоккейная коробка", address="г. Тестоград, ул. Доватора, 21", geocode_precision="house", lat="53.1", lon="27.1"),
        row(name="ГУО «Средняя школа № 144 г.Минска»", type="хоккейная коробка", address="ул. Красина, 65"),
    ])
    assert p[0].name == "Коробка, ул. Доватора, 21" and p[0].name_source == "generated"
    assert p[1].name == "Коробка, ул. Красина, 65" and p[1].operator.startswith("ГУО")


def test_city_centroid_drops_coordinates_and_map():
    p = plan_rows([row(address="ул. Ленина 1", lat="53.9", lon="27.5", geocode_precision="city")])[0]
    assert p.lat is None and p.lon is None and p.precision == "city"


def test_same_coordinates_in_two_cities_are_not_trusted():
    a, b = plan_rows([
        row(city="Брест", name="Каток Приорбанк", address="пл. Ленина", lat="53.89", lon="27.54", geocode_precision="street"),
        row(city="Витебск", name="Каток Приорбанк", address="пл. Ленина", lat="53.89", lon="27.54", geocode_precision="street"),
    ])
    assert a.precision == b.precision == "none" and a.lat is None


def test_indoor_names_are_skipped():
    p = plan_rows([row(name="ГКСУ «Чижовка-Арена» (закрытые х/к)"), row(name="Крыты каток")])
    assert [x.skip_reason for x in p] == ["indoor", "indoor"]


def test_candidate_without_address_is_hidden_with_address_is_not():
    a, b = plan_rows([
        row(confidence="candidate", lat="53.1", lon="27.1", geocode_precision="osm_exact"),
        row(confidence="candidate", address="ул. Мира 5", lat="53.2", lon="27.2", geocode_precision="osm_exact"),
    ])
    assert a.hidden_reason == "candidate" and b.hidden_reason is None


def test_twin_rink_and_box_are_linked_not_merged():
    a, b = plan_rows([
        row(address="ул. Брестская, 69/5", type="каток"),
        row(address="г. Тестоград, ул. Брестская, 69/5", type="хоккейная коробка"),
    ])
    assert a.skip_reason is None and b.skip_reason is None and b.same_complex_key == a.key


def test_exact_duplicate_row_is_collapsed_and_fills_gaps():
    a, b = plan_rows([row(address="ул. Мира 5"), row(address="ул. Мира 5", phone="8 029 253 90 24", hours="9.00-20.00")])
    assert b.skip_reason == "duplicate" and a.phone == "+375292539024" and a.hours.known


def test_two_nameless_addressless_rows_are_not_deduped():
    p = plan_rows([row(lat="53.1", lon="27.1"), row(lat="53.2", lon="27.2")])
    assert all(x.skip_reason is None for x in p) and p[0].key != p[1].key


async def _city(db):
    return (await db.execute(text("INSERT INTO cities (name, country, is_active) VALUES ('Тестоград', 'BY', true) RETURNING id"))).scalar_one()


@pytest.mark.asyncio
async def test_import_is_idempotent_and_keeps_manual_state(db_session):
    rows = [row(address="ул. Мира 5", hours="пн-пт 17.00-21.00; сб-вс 11.00-22.00", phone="8 029 253 90 24"),
            row(address="ул. Красная 1", type="хоккейная коробка", paid="платный")]
    planned = plan_rows(rows)
    r1 = await import_points(db_session, planned, now=NOW)
    assert r1.created == 2 and r1.existing == 0
    # админ вручную закрыл точку и подвинул пин — импорт не трогает
    await db_session.execute(
        text("UPDATE seasonal_rink_seasons SET state='closed', state_source='admin' WHERE hours_text LIKE 'пн-пт%'")
    )
    await db_session.execute(text("UPDATE arenas SET name='Мой каток', latitude=1.5 WHERE address='ул. Мира 5'"))
    r2 = await import_points(db_session, plan_rows(rows), now=NOW)
    assert r2.created == 0 and r2.existing == 2
    n = (await db_session.execute(text("SELECT count(*) FROM seasonal_rinks sr JOIN arenas a ON a.id=sr.arena_id WHERE a.city_id=(SELECT id FROM cities WHERE name='Тестоград')"))).scalar_one()
    assert n == 2
    state, name, lat = (await db_session.execute(text(
        "SELECT s.state, a.name, a.latitude FROM seasonal_rink_seasons s JOIN arenas a ON a.id=s.arena_id WHERE a.address='ул. Мира 5'"
    ))).one()
    assert (state, name, lat) == ("closed", "Мой каток", 1.5)
    prof = (await db_session.execute(text("SELECT status, slug FROM arena_profiles p JOIN arenas a ON a.id=p.arena_id WHERE a.address='ул. Красная 1'"))).one()
    assert prof.status == "draft" and prof.slug.startswith("testograd-korobka-")
    paid = (await db_session.execute(text("SELECT is_paid FROM seasonal_rinks sr JOIN arenas a ON a.id=sr.arena_id WHERE a.address='ул. Красная 1'"))).scalar_one()
    assert paid is True


@pytest.mark.asyncio
async def test_existing_catalog_arena_is_not_duplicated(db_session):
    cid = await _city(db_session)
    await db_session.execute(
        text("INSERT INTO arenas (city_id, name, address, venue_type, is_active) VALUES (:c, 'Ледовая арена', 'ул. Мира, 5', 'ice', true)"),
        {"c": cid},
    )
    planned = plan_rows([row(name="Каток у арены", address="г. Тестоград, ул. Мира 5")])
    rep = await import_points(db_session, planned, now=NOW)
    assert rep.created == 0 and len(rep.matched_catalog) == 1
    assert (await db_session.execute(text("SELECT count(*) FROM seasonal_rinks"))).scalar_one() == 0


@pytest.mark.asyncio
async def test_hours_unknown_stay_unknown_and_candidate_goes_to_queue(db_session):
    planned = plan_rows([row(confidence="candidate", lat="53.1", lon="27.1", geocode_precision="osm_exact"), row(address="ул. А 1", hours="")])
    rep = await import_points(db_session, planned, now=NOW)
    assert rep.hidden_candidates == 1 and rep.hours_unknown == 2
    states = sorted((await db_session.execute(text("SELECT state, hours_known, opening_hours IS NULL FROM seasonal_rink_seasons"))).all())
    assert states == [("hidden", False, True), ("waiting", False, True)]
    assert (await db_session.execute(text("SELECT count(*) FROM seasonal_moderation_items WHERE kind='new_point' AND status='open'"))).scalar_one() == 1


@pytest.mark.asyncio
async def test_nemiga_is_pinned_first_without_inventing_price_or_hours(db_session):
    cid = await _city(db_session)
    aid = (await db_session.execute(text(
        "INSERT INTO arenas (city_id, name, address, venue_type, is_active) VALUES (:c, 'Каток на Немиге', 'пр-т Победителей, 4а', 'outdoor', true) RETURNING id"
    ), {"c": cid})).scalar_one()
    await db_session.execute(text("INSERT INTO arena_profiles (arena_id, city_id, slug, status) VALUES (:a, :c, :s, 'published')"), {"a": aid, "c": cid, "s": NEMIGA_SLUG})
    rep = await import_points(db_session, [], now=NOW)
    assert "pinned" in rep.nemiga
    pin = (await db_session.execute(text("SELECT catalog_pin FROM arena_profiles WHERE arena_id=:a"), {"a": aid})).scalar_one()
    sr = (await db_session.execute(text("SELECT is_paid FROM seasonal_rinks WHERE arena_id=:a"), {"a": aid})).one()
    st = (await db_session.execute(text("SELECT state, hours_known, hours_text FROM seasonal_rink_seasons WHERE arena_id=:a"), {"a": aid})).one()
    assert pin == 1 and sr.is_paid is None and tuple(st) == ("waiting", False, None)
