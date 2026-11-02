"""Сверка с таблицей 2026/27: дифф, защита, применение пачкой (TASK-343)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application import winter_admin as wa
from src.application import winter_diff as wd
from src.application.winter_import import import_points, plan_rows
from src.shared.winter_status import current_season

NOW = datetime(2026, 12, 7, 9, 0, tzinfo=timezone.utc)  # понедельник, сверка
SEASON = current_season(NOW)


def row(**kw):
    base = {
        "city": "Тестоград", "district": "", "name": "", "address": "", "hours": "", "phone": "",
        "type": "каток", "paid": "", "price": "", "lat": "", "lon": "", "geocode_precision": "none",
        "source_url": "https://example.test/2026.pdf", "source_season": "2026/27", "confidence": "high",
    }
    base.update(kw)
    return base


def seed_rows():
    return [
        row(address="ул. Мира 5", hours="пн-пт 17.00-21.00", phone="8 029 253 90 24"),                # изменятся часы
        row(address="ул. Красная 1", hours="9.00-20.00", phone="8 029 111 22 33"),                       # без изменений
        row(address="ул. Школьная 3", type="хоккейная коробка", lat="53.9", lon="27.5", geocode_precision="house"),  # пропадёт
        row(address="ул. Старая 7", type="хоккейная коробка", lat="53.95", lon="27.55", geocode_precision="house",
            hours="8.00-22.00"),                                                                          # переименуют
        row(city="Другоград", address="ул. Чужая 1"),                                                    # другой город
    ]


async def _seed(db):
    rep = await import_points(db, plan_rows(seed_rows()), now=NOW, source_season=2025)
    assert rep.created == 5
    # без пропавших больше 30% защита молчит: добавим фоновую массу
    rows = [row(address=f"ул. Фон {i}", hours="9.00-18.00") for i in range(12)]
    await import_points(db, plan_rows(rows), now=NOW, source_season=2025)
    return rows


def new_file(background):
    return background + [
        row(address="ул. Мира 5", hours="пн-пт 16.00-22.00", phone="8 029 253 90 24"),
        row(address="ул. Красная 1", hours="9.00-20.00", phone="8 029 111 22 33"),
        row(address="ул. Новая 11", type="хоккейная коробка", lat="53.8", lon="27.4", geocode_precision="house"),
        # та же коробка, другой адрес в таблице -> «та же точка»
        row(address="ул. Старая, дом 7а", type="хоккейная коробка", lat="53.95005", lon="27.55005", geocode_precision="house",
            hours="7.00-23.00"),
    ]


async def _run(db, rows):
    return await wd.create_run(db, rows, season=SEASON, label="таблица 2026/27", admin_id=5, now=NOW)


@pytest.mark.asyncio
async def test_diff_buckets(db_session):
    bg = await _seed(db_session)
    res = await _run(db_session, new_file(bg))
    c = res.diff["counts"]
    assert res.status == "pending" and not res.duplicate
    assert (c["new"], c["changed"], c["missing"], c["same"]) == (1, 1, 1, 1)
    assert c["verified"] == 13  # ул. Красная + 12 фоновых: часы совпали
    ch = res.diff["changed"][0]
    assert ch["fields"] == ["hours"] and ch["hours_old"].startswith("пн-пт 17") and ch["hours_new"].startswith("пн-пт 16")
    assert res.diff["missing"][0]["address"] == "ул. Школьная 3"
    assert res.diff["same"][0]["address_old"] == "ул. Старая 7"
    # другой город в файле не упоминался -> его точка не «пропала»
    assert all(m["city"] == "Тестоград" for m in res.diff["missing"])
    assert wd.available_parts(res.diff) == ["new", "changed", "missing", "same"]


@pytest.mark.asyncio
async def test_same_file_twice_returns_same_run(db_session):
    bg = await _seed(db_session)
    a = await _run(db_session, new_file(bg))
    b = await _run(db_session, new_file(bg))
    assert b.duplicate and b.run_id == a.run_id


@pytest.mark.asyncio
async def test_mostly_gone_file_fails_and_cannot_be_applied(db_session):
    bg = await _seed(db_session)
    res = await _run(db_session, [row(address="ул. Мира 5", hours="пн-пт 17.00-21.00")])  # 1 из 16 точек города
    assert res.status == "failed" and "30%" in res.error
    with pytest.raises(wd.DiffError) as e:
        await wd.apply_run(db_session, res.run_id, ["missing"], admin_id=1, now=NOW)
    assert e.value.code == "not_pending"
    assert (await db_session.execute(text("SELECT count(*) FROM seasonal_rink_seasons WHERE state='hidden'"))).scalar_one() == 0


def test_parse_csv_variants():
    rows = wd.parse_csv("city;name;address;hours\nМинск;Каток;ул. А 1;9.00-20.00\n".encode("utf-8-sig"))
    assert rows[0]["city"] == "Минск" and rows[0]["hours"] == "9.00-20.00"
    with pytest.raises(wd.DiffError) as e:
        wd.parse_csv("foo,bar\n1,2\n".encode())
    assert e.value.code == "no_columns"


@pytest.mark.asyncio
async def test_apply_parts_one_by_one_and_undo(db_session):
    bg = await _seed(db_session)
    res = await _run(db_session, new_file(bg))
    rid = res.run_id

    out = await wd.apply_run(db_session, rid, ["new"], admin_id=1, now=NOW)
    assert out["new"]["created"] == 1 and out["run_closed"] is False
    new_state = (await db_session.execute(text(
        "SELECT s.state, s.admin_confirmed_at, s.hours_season FROM seasonal_rink_seasons s JOIN arenas a ON a.id=s.arena_id WHERE a.address='ул. Новая 11'"))).one()
    assert new_state.state == "waiting" and new_state.admin_confirmed_at is None and new_state.hours_season == "2026/27"
    with pytest.raises(wd.DiffError):
        await wd.apply_run(db_session, rid, ["new"], admin_id=1, now=NOW)  # повтор части нельзя

    out = await wd.apply_run(db_session, rid, ["changed"], admin_id=1, now=NOW)
    mira = (await db_session.execute(text(
        "SELECT s.hours_text, s.hours_season, s.opening_hours IS NOT NULL AS oh FROM seasonal_rink_seasons s JOIN arenas a ON a.id=s.arena_id WHERE a.address='ул. Мира 5'"))).one()
    assert mira.hours_text.startswith("пн-пт 16") and mira.hours_season == "2026/27" and mira.oh
    krasnaya = (await db_session.execute(text(
        "SELECT s.hours_season FROM seasonal_rink_seasons s JOIN arenas a ON a.id=s.arena_id WHERE a.address='ул. Красная 1'"))).scalar_one()
    assert krasnaya == "2026/27"  # часы совпали -> сверено
    undo = await wa.undo_batch(db_session, out["changed"]["batch_id"], now=NOW + timedelta(minutes=3))
    assert undo["status"] == "ok" and undo["restored"] == 14
    mira = (await db_session.execute(text(
        "SELECT s.hours_text, s.hours_season FROM seasonal_rink_seasons s JOIN arenas a ON a.id=s.arena_id WHERE a.address='ул. Мира 5'"))).one()
    assert mira.hours_text.startswith("пн-пт 17") and mira.hours_season == "2025/26"

    out = await wd.apply_run(db_session, rid, ["missing"], admin_id=1, now=NOW)
    assert out["missing"] == {"hidden": 1, "kept": 0, "batch_id": out["missing"]["batch_id"]}
    gone = (await db_session.execute(text(
        "SELECT s.state, s.hidden_reason FROM seasonal_rink_seasons s JOIN arenas a ON a.id=s.arena_id WHERE a.address='ул. Школьная 3'"))).one()
    assert (gone.state, gone.hidden_reason) == ("hidden", "not_in_list")

    out = await wd.apply_run(db_session, rid, ["same"], admin_id=1, now=NOW)
    assert out["run_closed"] is True  # применены все четыре части (откат часов часть не «разприменяет»)
    same = (await db_session.execute(text(
        "SELECT a.address, s.hours_text, sr.source_key FROM arenas a JOIN seasonal_rinks sr ON sr.arena_id=a.id "
        "JOIN seasonal_rink_seasons s ON s.arena_id=a.id WHERE a.address LIKE 'ул. Старая%'"))).one()
    assert same.address == "ул. Старая, дом 7а" and same.hours_text == "7.00-23.00"
    status = (await db_session.execute(text("SELECT status FROM winter_import_runs WHERE id=:i"), {"i": rid})).scalar_one()
    assert status == "applied"  # все 4 части применены


@pytest.mark.asyncio
async def test_missing_keeps_live_flooded_and_recently_confirmed(db_session):
    bg = await _seed(db_session)
    res = await _run(db_session, new_file(bg))
    await db_session.execute(text(
        "UPDATE seasonal_rink_seasons SET state='flooded', state_source='admin' WHERE arena_id=(SELECT id FROM arenas WHERE address='ул. Школьная 3')"))
    out = await wd.apply_run(db_session, res.run_id, ["missing"], admin_id=1, now=NOW)
    assert out["missing"]["hidden"] == 0 and out["missing"]["kept"] == 1


@pytest.mark.asyncio
async def test_reject_run(db_session):
    bg = await _seed(db_session)
    res = await _run(db_session, new_file(bg))
    assert await wd.reject_run(db_session, res.run_id, now=NOW)
    assert not await wd.reject_run(db_session, res.run_id, now=NOW)
    with pytest.raises(wd.DiffError):
        await wd.apply_run(db_session, res.run_id, ["new"], admin_id=1, now=NOW)
    assert await wd.pending_runs(db_session) == []
