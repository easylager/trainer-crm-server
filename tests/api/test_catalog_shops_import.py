"""TASK-146: импорт магазинов партнёра — только названное, без дублей, без угадываний."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from src.application.catalog_shops_import import (
    ShopImportError,
    apply_plan,
    build_plan,
    parse_shops_file,
)
from tests.api.test_public_arenas import _insert_arena, _insert_city

REPO = Path(__file__).resolve().parents[2]


def test_real_partner_file_parses_and_names_only_stated_services() -> None:
    city, records, rinks = parse_shops_file(REPO / "data" / "catalog" / "shops-minsk.json")
    assert city == "Минск"
    assert len(records) == 13
    assert sum(1 for r in records if r.photo) == 12  # у Sport-Ice в парке Горького фото нет
    by_key = {r.key: r for r in records}
    # Фигурист.by — магазин; про заточку источник молчит → ключа нет (неизвестно), а не False.
    assert by_key["figurist"].amenities == {"retail": True, "discipline_figure": True}
    assert "skate_sharpening" not in by_key["figurist"].amenities
    assert by_key["het-trik"].amenities["blade_profiling"] is True
    assert by_key["hotice"].display_address is None
    assert by_key["sportcontinent"].display_address.endswith("(здание Минского ледового Дворца спорта, 1-й этаж)")
    assert by_key["icecity"].display_address.endswith("(ТРЦ «Тивали», 3-й этаж, пав. 327)")
    assert "Ещё телефоны: +375 44 599-90-97." in by_key["het-trik"].short_description
    assert len(rinks) == 4


def test_unknown_service_rejects_the_whole_file(tmp_path: Path) -> None:
    bad = {"city": "Минск", "shops": [{"name": "X", "services": ["massage"]}]}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ShopImportError):
        parse_shops_file(path)


@pytest.mark.asyncio
async def test_import_is_idempotent_and_rinks_need_an_unambiguous_match(
    app_use_test_db, db_session, tmp_path: Path
) -> None:
    city_name = f"Импортинск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=city_name)
    olymp = await _insert_arena(db_session, city_id, name="Олимпик Арена")
    await _insert_arena(db_session, city_id, name="Чижовка-Арена")
    await _insert_arena(db_session, city_id, name="Чижовка-Арена (малая)")
    await db_session.commit()

    payload = {
        "city": city_name,
        "shops": [
            {
                "key": "sport-ice",
                "name": "Sport-Ice — Дворец спорта",
                "address": "пр-т Победителей, 4А",
                "phones": ["+375 17 396-95-93", "+375 29 148-80-08"],
                "website": "https://sport-ice.by",
                "instagram": "sport_ice.by",
                "services": ["retail"],
                "disciplines": ["hockey"],
                "hours": {"mon": ["10:00", "19:00"], "sun": ["11:00", "17:00"]},
            }
        ],
        "rink_sharpening": [{"match": ["олимпик"], "note": "Олимпик"}, {"match": ["чижовк"], "note": "Чижовка"}],
    }
    path = tmp_path / "shops.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    city, records, rules = parse_shops_file(path)

    plan = await build_plan(db_session, city_name=city, records=records, rink_rules=rules)
    assert [r.name for r in plan.creates] == ["Sport-Ice — Дворец спорта"]
    assert [a for a, _ in plan.rink_updates] == [olymp]
    assert any("несколько совпадений" in p for p in plan.rink_problems)

    async def fake_geocode(address: str, city_value: str):
        return (53.9, 27.55)

    report = await apply_plan(db_session, plan, geocode=fake_geocode)
    await db_session.commit()
    assert len(report["created"]) == 1 and not report["not_on_map"]

    again = await build_plan(db_session, city_name=city, records=records, rink_rules=rules)
    assert not again.creates and len(again.updates) == 1

    shop = (
        await db_session.execute(
            text(
                "SELECT a.venue_type, a.latitude, p.phone, p.amenities, p.opening_hours, p.social_urls, p.status "
                "FROM arenas a JOIN arena_profiles p ON p.arena_id = a.id "
                "WHERE a.city_id = :c AND a.venue_type = 'shop'"
            ),
            {"c": city_id},
        )
    ).one()
    assert shop[0] == "shop" and shop[1] == 53.9
    assert shop[2] == "+375 17 396-95-93"
    assert shop[3] == {"retail": True, "discipline_hockey": True}
    assert shop[4]["weekly"]["mon"] == ["10:00", "19:00"] and shop[4]["weekly"]["tue"] is None
    assert shop[5] == {"instagram": "https://instagram.com/sport_ice.by"}
    assert shop[6] == "published"
    rink = (
        await db_session.execute(text("SELECT amenities FROM arena_profiles WHERE arena_id = :id"), {"id": olymp})
    ).scalar_one()
    assert rink["skate_sharpening"] is True


def test_weekly_hours_group_and_today_label() -> None:
    from datetime import datetime, timezone

    from src.application.arena_profile import hours_groups, opening_hours_schema_org
    from src.application.place_page import open_now_label

    weekly = {
        "weekly": {
            "mon": ["10:00", "19:00"],
            "tue": ["10:00", "19:00"],
            "wed": ["10:00", "19:00"],
            "thu": ["10:00", "19:00"],
            "fri": ["10:00", "19:00"],
            "sat": ["10:00", "18:00"],
            "sun": None,
        }
    }
    assert hours_groups(weekly) == [("Пн–Пт", ("10:00", "19:00")), ("Сб", ("10:00", "18:00")), ("Вс", None)]
    assert opening_hours_schema_org(weekly) == ["Mo-Fr 10:00-19:00", "Sa 10:00-18:00"]
    sunday_noon = datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc)
    assert open_now_label({"opening_hours": weekly}, now=sunday_noon) == "Сегодня выходной"
    friday_late = datetime(2026, 10, 2, 18, 0, tzinfo=timezone.utc)  # 21:00 в Минске
    assert open_now_label({"opening_hours": weekly}, now=friday_late) == "Сегодня уже закрыто"


def test_cyrillic_domain_is_shown_as_typed() -> None:
    from src.application.place_page import _display_host

    assert _display_host("https://xn--j1aaid0h.xn--90ais") == "конёк.бел"
    assert _display_host("https://hotice.by/") == "hotice.by"


def test_real_rinks_file_parses() -> None:
    city, records, _ = parse_shops_file(REPO / "data" / "catalog" / "rinks-minsk.json")
    assert city == "Минск"
    by_key = {r.key: r for r in records}
    assert by_key["f1-nemiga"].venue_type == "outdoor"
    assert by_key["f1-nemiga"].season == (11, 3)
    assert by_key["olympic-arena"].match == ["олимпик"]


def test_rink_record_rejects_shop_only_services(tmp_path: Path) -> None:
    bad = {"city": "Минск", "shops": [{"name": "Каток", "venue_type": "ice", "services": ["retail"]}]}
    path = tmp_path / "rinks.json"
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ShopImportError):
        parse_shops_file(path)


@pytest.mark.asyncio
async def test_rink_import_creates_missing_and_enriches_existing_without_wiping(
    db_session, tmp_path: Path
) -> None:
    """Пропущенный каток — создаётся; существующий (из досье) — дополняется, но не затирается."""
    city_name = f"Городрк-{uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=city_name)
    olymp = await _insert_arena(
        db_session, city_id, name="Олимпик-арена", phone="+375 17 000-00-00", website_url="https://old.example"
    )
    await db_session.execute(
        text("UPDATE arena_profiles SET amenities = CAST(:a AS jsonb) WHERE arena_id = :id"),
        {"a": json.dumps({"parking": True}), "id": olymp},
    )
    await db_session.commit()
    data = {
        "city": city_name,
        "shops": [
            {"name": "Олимпик Арена", "venue_type": "ice", "match": ["олимпик"],
             "website": "https://new.example", "services": ["skate_sharpening"],
             "hours": {d: ["07:00", "23:00"] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}},
            {"name": "Каток на площади", "venue_type": "outdoor", "address": "пл. Ледовая, 1",
             "season": [11, 3], "services": ["skate_rental"]},
        ],
    }
    path = tmp_path / "rinks.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    city, records, rules = parse_shops_file(path)
    plan = await build_plan(db_session, city_name=city, records=records, rink_rules=rules)
    assert [rec.name for rec in plan.creates] == ["Каток на площади"]
    assert [(aid, rec.name) for aid, rec in plan.updates] == [(olymp, "Олимпик Арена")]
    await apply_plan(db_session, plan)
    await db_session.commit()

    row = (
        await db_session.execute(
            text("SELECT a.name, p.phone, p.website_url, p.amenities, p.opening_hours "
                 "FROM arenas a JOIN arena_profiles p ON p.arena_id = a.id WHERE a.id = :id"),
            {"id": olymp},
        )
    ).first()
    assert row[0] == "Олимпик-арена"  # имя из базы не переименовываем
    assert row[1] == "+375 17 000-00-00"
    assert row[2] == "https://old.example"  # уже заполненное — не перезаписываем
    assert row[3] == {"parking": True, "skate_sharpening": True}
    assert row[4]["weekly"]["mon"] == ["07:00", "23:00"]

    created = (
        await db_session.execute(
            text("SELECT a.venue_type, p.season_start_month, p.season_end_month, p.amenities "
                 "FROM arenas a JOIN arena_profiles p ON p.arena_id = a.id "
                 "WHERE a.city_id = :c AND a.name = 'Каток на площади'"),
            {"c": city_id},
        )
    ).first()
    assert created[0] == "outdoor"
    assert (created[1], created[2]) == (11, 3)
    assert created[3] == {"skate_rental": True}


@pytest.mark.asyncio
async def test_partner_photo_is_attached_once(db_session, tmp_path: Path, monkeypatch) -> None:
    """Фото из файла — одно на место; повторный импорт копий не плодит."""
    monkeypatch.delenv("S3_ENDPOINT", raising=False)
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path / "media"))
    city_name = f"Фотоград-{uuid.uuid4().hex[:6]}"
    await _insert_city(db_session, name=city_name)
    await db_session.commit()
    photo = REPO / "data" / "catalog" / "photos" / "minsk" / "het-trik.jpg"
    data = {"city": city_name, "shops": [{"name": "Мастерская", "services": ["skate_sharpening"], "photo": str(photo)}]}
    path = tmp_path / "shops.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for _ in range(2):
        city, records, rules = parse_shops_file(path)
        plan = await build_plan(db_session, city_name=city, records=records, rink_rules=rules)
        await apply_plan(db_session, plan)
        await db_session.commit()
    rows = (
        await db_session.execute(
            text("SELECT m.license, m.attribution FROM media m JOIN arenas a ON a.id = m.owner_id "
                 "JOIN cities c ON c.id = a.city_id WHERE m.owner_type = 'arena' AND c.name = :c"),
            {"c": city_name},
        )
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "permitted" and "партнёра" in rows[0][1]
