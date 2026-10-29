import pytest
from sqlalchemy import text


async def _columns(db_session, table: str) -> set[str]:
    rows = (await db_session.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
    ), {"t": table})).fetchall()
    return {r[0] for r in rows}


@pytest.mark.asyncio
async def test_place_suggestions_tables_exist(db_session):
    assert {"id", "kind", "status", "city_id", "new_city_name", "name", "details",
            "contact", "contact_kind", "author_telegram_id", "bind_token",
            "target_arena_id", "result_arena_id", "source", "created_at"} <= await _columns(
        db_session, "place_suggestions")
    assert {"suggestion_id", "direction", "body", "created_at"} <= await _columns(
        db_session, "place_suggestion_messages")
    assert {"latitude", "longitude", "region"} <= await _columns(db_session, "cities")
    assert "visitor_prices" in await _columns(db_session, "arena_profiles")


@pytest.mark.asyncio
async def test_arenas_venue_type_accepts_school(db_session):
    check = (await db_session.execute(text(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_arenas_venue_type'"
    ))).scalar_one()
    assert "'school'" in check


@pytest.mark.asyncio
async def test_place_suggestion_photos_table_and_token(db_session):
    assert {"id", "suggestion_id", "created_at", "storage_key", "variants", "width", "height",
            "publish"} <= await _columns(db_session, "place_suggestion_photos")
    assert "photo_token" in await _columns(db_session, "place_suggestions")
    rule = (await db_session.execute(text(
        "SELECT confdeltype::text FROM pg_constraint WHERE conrelid = 'place_suggestion_photos'::regclass "
        "AND contype = 'f'"
    ))).scalar_one()
    assert rule == "c"
