"""TASK-146: отчёт о полноте каталога — пробелы карточек, парсеры, data/-катки, магазины."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.arena_profile import ensure_arena_profile
from src.application.catalog_coverage import (
    address_key,
    build_coverage_report,
    format_coverage_report,
    load_arenas,
    match_known_rink,
    name_tokens,
    KnownRink,
    _names_match,
    _token_overlap_ratio,
)

_NOW = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


def test_name_and_address_normalization() -> None:
    assert name_tokens('Каток хк "Юность"') == {"юность"}
    assert name_tokens("Юность (парк Горького)") == {"юность", "горького"}
    assert name_tokens("Ледовая арена") == set()
    assert address_key("Минск, ул. Притыцкого, 27") == ("притыцкого", "27")
    assert address_key("ул. Притыцкого 27, Минск, Минская область") == ("притыцкого", "27")
    assert _token_overlap_ratio("Ледовая арена Орша", "Ледовая арена Шклов") < 0.5
    assert not _names_match("Ледовая арена Орша", "Ледовая арена Шклов")


async def _arena(
    db_session,
    city_id: int,
    name: str,
    *,
    venue_type: str = "ice",
    coords: bool = True,
    photo: bool = False,
    phone: str | None = None,
    hours: dict | None = None,
    tickets: str | None = None,
    website: str | None = None,
    amenities: dict | None = None,
    active: bool = True,
) -> int:
    arena_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO arenas (city_id, name, address, latitude, longitude, is_active,
                                        is_confirmed, venue_type)
                    VALUES (:cid, :name, 'ул. Тестовая, 1', :lat, :lon, :active, true, :vt)
                    RETURNING id
                    """
                ),
                {
                    "cid": city_id,
                    "name": name,
                    "lat": 53.9 if coords else None,
                    "lon": 27.5 if coords else None,
                    "active": active,
                    "vt": venue_type,
                },
            )
        ).scalar_one()
    )
    await ensure_arena_profile(db_session, arena_id, city_id=city_id, name=name)
    await db_session.execute(
        text(
            """
            UPDATE arena_profiles
            SET phone = :phone, website_url = :web, tickets_url = :tix,
                opening_hours = CAST(:hours AS jsonb), amenities = CAST(:amen AS jsonb)
            WHERE arena_id = :id
            """
        ),
        {
            "id": arena_id,
            "phone": phone,
            "web": website,
            "tix": tickets,
            "hours": json.dumps(hours) if hours else None,
            "amen": json.dumps(amenities or {}),
        },
    )
    if photo:
        await db_session.execute(
            text(
                "INSERT INTO media (owner_type, owner_id, storage_key, license, status) "
                "VALUES ('arena', :id, :key, 'own', 'published')"
            ),
            {"id": arena_id, "key": f"test/cov/{arena_id}.jpg"},
        )
    return arena_id


async def _job(db_session, arena_id: int, *, last_ok_at: datetime | None, streak: int = 0) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config,
                                         created_at, last_ok_at, failure_streak, last_error_code)
            VALUES (:aid, 'cov_test_v1', true, 'daily', :now, '{}'::jsonb, :created, :ok, :streak, :code)
            """
        ),
        {
            "aid": arena_id,
            "now": _NOW,
            "created": _NOW - timedelta(days=30),
            "ok": last_ok_at,
            "streak": streak,
            "code": "extract_error" if streak else None,
        },
    )


@pytest.mark.asyncio
async def test_coverage_report_lists_what_a_human_must_fill(db_session, tmp_path) -> None:
    city_id = int(
        (
            await db_session.execute(
                text(
                    "INSERT INTO cities (name, country, price_group, is_active, sort_order) "
                    "VALUES ('Покрытоград', 'BY', 'BY_BASE', true, 9400) RETURNING id"
                )
            )
        ).scalar_one()
    )
    full_hours = {"mon": ["10:00", "22:00"]}
    complete = await _arena(
        db_session,
        city_id,
        "Каток Полный",
        photo=True,
        phone="+375 17 000",
        hours=full_hours,
        tickets="https://tickets.example/ice",
        website="https://full.example",
    )
    await _job(db_session, complete, last_ok_at=_NOW - timedelta(minutes=30))
    bare = await _arena(db_session, city_id, "Ледовая арена Голая", coords=False)
    broken = await _arena(db_session, city_id, "Каток Сломанный", photo=True, phone="+375", hours=full_hours)
    await _job(db_session, broken, last_ok_at=_NOW - timedelta(days=2), streak=5)
    gym = await _arena(db_session, city_id, "Зал Силы", venue_type="gym", photo=True, hours=full_hours)
    shop = await _arena(db_session, city_id, "Точилка", venue_type="shop", coords=False, phone="+375 29")
    await _arena(db_session, city_id, "Каток Скрытый", active=False)

    sources = tmp_path / "test-sources.csv"
    sources.write_text(
        "arena_name,address,kind,is_primary,update_cadence\n"
        '"Полный каток (центр)","Покрытоград, ул. Другая, 5",site,true,weekly\n'
        '"Каток Новый","Покрытоград, ул. Новая, 7",site,true,weekly\n'
        '"Каток Новый","Покрытоград, ул. Новая, 7",directory,false,daily\n'
        '"Тренировочный","Покрытоград, ул. Т, 1",site,true,skip_training_only\n',
        encoding="utf-8",
    )
    shops = tmp_path / "shops-test.json"
    shops.write_text(
        json.dumps(
            {
                "city": "Покрытоград",
                "shops": [
                    {"key": "t", "name": "Точилка", "address": "ул. Острая, 1", "phones": ["+375 29"],
                     "hours": {"mon": ["10:00", "19:00"]}, "website": "https://t.example"},
                    {"key": "n", "name": "Новая мастерская", "address": None, "phones": [], "hours": None},
                ],
                "rink_sharpening": [{"match": ["сломанн"], "note": "Сломанный каток"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = await build_coverage_report(
        db_session,
        now=_NOW,
        city="Покрытоград",
        known_rink_files=[sources],
        shop_files=[shops],
    )
    [cov] = report.cities
    assert cov.published_by_type == {"ice": 3, "gym": 1, "shop": 1}
    assert cov.unpublished == 1

    gaps = {a.id: a.gaps for a in cov.arenas_with_gaps}
    assert complete not in gaps
    assert set(gaps[bare]) >= {"координаты", "фото", "часы работы", "телефон", "касса (tickets_url)", "сайт"}
    assert "касса (tickets_url)" not in gaps[gym]  # у зала кассы сеансов нет
    assert "телефон" in gaps[gym]

    assert [a.id for a in cov.rinks_without_parser] == [bare]
    [problem] = cov.rinks_parser_problem
    assert problem.id == broken and "падает" in (problem.parser_state or "")

    # «Полный каток (центр)» совпал с «Каток Полный» по токену; вторичный и skip_* — не пробел.
    assert [r.name for r in cov.known_missing_in_db] == ["Каток Новый"]

    by_name = {s.name: s for s in cov.shops}
    assert by_name["Точилка"].db_arena_id == shop
    assert by_name["Точилка"].missing_in_file == []
    assert set(by_name["Точилка"].missing_in_db) == {"координаты", "фото", "часы работы"}
    assert by_name["Новая мастерская"].db_arena_id is None
    assert set(by_name["Новая мастерская"].missing_in_file) == {"адрес", "часы работы", "телефон", "сайт/инстаграм"}
    assert cov.rink_sharpening_problems == [f"Сломанный каток: #{broken} без отметки «заточка» в карточке"]

    body = format_coverage_report(report)
    assert "=== Покрытоград (BY) ===" in body
    assert f"#{bare} Ледовая арена Голая [Лёд] — нет: координаты" in body
    assert "Каток Новый, Покрытоград, ул. Новая, 7 [weekly] ← test-sources.csv" in body
    assert "Новая мастерская — в файле нет: адрес" in body
    print(body)  # pytest -s: живой пример отчёта


@pytest.mark.asyncio
async def test_trainer_arena_without_photo_not_counted_published(db_session) -> None:
    """AC-2: арена тренера без фото скрыта из публичной выдачи — в отчёте не «опубликована»."""
    from tests.api.test_public_arenas import _insert_bare_trainer, _insert_city

    city_id = await _insert_city(db_session, name=f"Скрытоград-{uuid.uuid4().hex[:8]}")
    trainer_id = await _insert_bare_trainer(db_session)
    arena_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO arenas (city_id, name, address, latitude, longitude, is_active,
                                        is_confirmed, venue_type, created_by_trainer_id)
                    VALUES (:c, 'Каток тренера', 'ул. Тайная, 1', 53.9, 27.5, true, true, 'ice', :tid)
                    RETURNING id
                    """
                ),
                {"c": city_id, "tid": trainer_id},
            )
        ).scalar_one()
    )
    await ensure_arena_profile(db_session, arena_id, city_id=city_id, name="Каток тренера")
    await db_session.commit()

    rows = await load_arenas(db_session, now=_NOW)
    hidden = next(r for r in rows if r.id == arena_id)
    assert hidden.published is False


@pytest.mark.asyncio
async def test_future_sessions_ignore_expired_valid_until(db_session) -> None:
    city_id = int(
        (
            await db_session.execute(
                text(
                    "INSERT INTO cities (name, country, price_group, is_active, sort_order) "
                    "VALUES ('Сеансград', 'BY', 'BY_BASE', true, 9900) RETURNING id"
                )
            )
        ).scalar_one()
    )
    arena_id = await _arena(db_session, city_id, "Каток сеансов", photo=True, phone="+375", hours={"mon": ["10:00", "22:00"]})
    await db_session.execute(
        text(
            """
            INSERT INTO ice_sessions (
                arena_id, kind, local_date, starts_at_local, ends_at_local,
                starts_at_utc, ends_at_utc, status, observed_at, valid_until, currency_code
            ) VALUES (
                :aid, 'public_skate', '2026-10-10', '18:00', '19:00',
                :start, :end, 'active', :now, :vu, 'BYN'
            )
            """
        ),
        {
            "aid": arena_id,
            "start": _NOW + timedelta(days=2),
            "end": _NOW + timedelta(days=2, hours=1),
            "now": _NOW,
            "vu": _NOW - timedelta(hours=1),
        },
    )
    await db_session.commit()
    rows = await load_arenas(db_session, now=_NOW)
    row = next(r for r in rows if r.id == arena_id)
    assert row.future_sessions == 0


@pytest.mark.asyncio
async def test_match_known_rink_ignores_unpublished_arena(db_session) -> None:
    city_id = int(
        (
            await db_session.execute(
                text(
                    "INSERT INTO cities (name, country, price_group, is_active, sort_order) "
                    "VALUES ('Матчград', 'BY', 'BY_BASE', true, 9910) RETURNING id"
                )
            )
        ).scalar_one()
    )
    arena_id = await _arena(db_session, city_id, "Каток Скрытый", active=False)
    await db_session.commit()
    arenas = await load_arenas(db_session, now=_NOW)
    rink = KnownRink(source_file="t.csv", name="Каток Скрытый", city_name="Матчград", arena_id=arena_id, address=None)
    assert match_known_rink(rink, arenas) is None


def _row(arena_id: int, name: str, *, lat: float | None = None, lon: float | None = None, published: bool = True):
    from src.application.catalog_coverage import ArenaRow

    return ArenaRow(
        id=arena_id, name=name, address=None, city_id=1, city_name="Минск", country="BY",
        venue_type="ice", published=published, gaps=[], job_id=None, job_enabled=False,
        parser_key=None, parser_state=None, future_sessions=0, amenities={},
        latitude=lat, longitude=lon,
    )


def test_rink_linked_by_arena_id_is_present_even_if_names_differ() -> None:
    """Явная связь по arena_id сильнее строгого сравнения имён (<0.5 общих токенов)."""
    arena = _row(7, "Минск-Арена (малая)")
    rink = KnownRink(source_file="t.csv", name="Тренировочный каток Чижовка", city_name="Минск",
                     arena_id=7, address=None)
    assert _token_overlap_ratio(arena.name, rink.name) < 0.5
    assert match_known_rink(rink, [arena]) is arena
    # Связь по id на скрытое место не считается: в выдаче его нет.
    assert match_known_rink(rink, [_row(7, "Минск-Арена (малая)", published=False)]) is None


def test_rink_matches_by_coordinates_when_names_disagree() -> None:
    arena = _row(8, "Дворец спорта «Уручье»", lat=53.9450, lon=27.6850)
    near = KnownRink(source_file="t.csv", name="Каток Восточный", city_name="Минск", arena_id=None,
                     address=None, latitude=53.9455, longitude=27.6853)
    far = KnownRink(source_file="t.csv", name="Каток Восточный", city_name="Минск", arena_id=None,
                    address=None, latitude=53.90, longitude=27.55)
    assert match_known_rink(near, [arena]) is arena
    assert match_known_rink(far, [arena]) is None


def test_known_rinks_read_coordinates_from_csv(tmp_path) -> None:
    from src.application.catalog_coverage import load_known_rinks

    path = tmp_path / "by-arenas-prod.csv"
    path.write_text(
        "city_id,city_name,country,arena_id,arena_name,address,latitude,longitude,is_active,is_confirmed\n"
        "1,Минск,BY,5,Каток,\"Минск, ул. Тест, 1\",53.9,27.5,true,true\n"
        "1,Минск,BY,6,Без координат,,,,true,true\n",
        encoding="utf-8",
    )
    rinks = {r.arena_id: r for r in load_known_rinks([path])}
    assert (rinks[5].latitude, rinks[5].longitude) == (53.9, 27.5)
    assert rinks[6].latitude is None
