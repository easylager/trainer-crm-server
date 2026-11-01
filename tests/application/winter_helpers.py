"""Фикстуры-хелперы для тестов зимних точек (TASK-343)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from src.shared.winter_status import current_season

NOW = datetime(2026, 12, 10, 12, 0, tzinfo=timezone.utc)
SEASON = current_season(NOW)


async def make_city(db, name="Тестоград") -> int:
    row = (await db.execute(text("SELECT id FROM cities WHERE name=:n"), {"n": name})).first()
    if row:
        return int(row[0])
    return int((await db.execute(
        text("INSERT INTO cities (name, country, is_active, latitude, longitude) VALUES (:n, 'BY', true, 53.9, 27.5) RETURNING id"),
        {"n": name},
    )).scalar_one())


async def make_point(
    db, *, name="Каток тест", city="Тестоград", lat=53.9, lon=27.56, precision="house", state="waiting",
    kind="rink", paid=False, hours=None, status="published", slug=None, pin=None, state_source="import",
    state_at=None,
) -> int:
    cid = await make_city(db, city)
    aid = int((await db.execute(
        text("INSERT INTO arenas (city_id, name, address, latitude, longitude, venue_type, is_active) "
             "VALUES (:c, :n, 'ул. Тестовая 1', :la, :lo, 'outdoor', true) RETURNING id"),
        {"c": cid, "n": name, "la": lat, "lo": lon},
    )).scalar_one())
    await db.execute(
        text("INSERT INTO arena_profiles (arena_id, city_id, slug, district, status, catalog_pin) VALUES (:a, :c, :s, 'Центр', :st, :pin)"),
        {"a": aid, "c": cid, "s": slug or f"t-{aid}", "st": status, "pin": pin},
    )
    await db.execute(
        text("INSERT INTO seasonal_rinks (arena_id, kind, is_paid, geocode_precision, often_hockey) VALUES (:a, :k, :p, :g, :oh)"),
        {"a": aid, "k": kind, "p": paid, "g": precision, "oh": kind == "hockey_box"},
    )
    import json
    await db.execute(
        text("INSERT INTO seasonal_rink_seasons (arena_id, season, state, state_source, state_at, hours_known, opening_hours, hours_text, hours_season, phone) "
             "VALUES (:a, :s, :st, :ss, :sa, :hk, CAST(:oh AS jsonb), :ht, '2025/26', '+375291112233')"),
        {"a": aid, "s": SEASON, "st": state, "ss": state_source, "sa": state_at or NOW - timedelta(days=30),
         "hk": bool(hours), "oh": json.dumps(hours) if hours else None, "ht": "7:00–23:00" if hours else None},
    )
    return aid


async def make_client(db, telegram_id: int, age_days: int = 30) -> int:
    return int((await db.execute(
        text("INSERT INTO clients (telegram_id, first_name, created_at) VALUES (:t, 'Тест', :c) RETURNING id"),
        {"t": telegram_id, "c": NOW - timedelta(days=age_days)},
    )).scalar_one())
