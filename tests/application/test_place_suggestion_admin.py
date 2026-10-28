"""Модерация заявок «места от людей» (PDEC-028): список, правка, отказ, дубль, одобрение."""
import pytest
from sqlalchemy import text

from src.application import place_suggestion_use_cases as uc
from src.application.place_suggestion_use_cases import (
    PlaceSuggestionAdminError,
    create_place_suggestion,
    get_place_suggestion,
    list_place_suggestions,
    mark_duplicate,
    patch_place_suggestion,
    reject_place_suggestion,
)


async def _noop(*_a, **_kw):
    return None


@pytest.fixture(autouse=True)
def _no_telegram(monkeypatch):
    """Никаких реальных сообщений в Telegram: .env держит боевые токены ботов."""
    monkeypatch.setattr(uc, "notify_admins_new_place_suggestion", _noop)


async def _city(db_session, name: str, *, active: bool = True, country: str = "BY") -> int:
    r = await db_session.execute(
        text(
            "INSERT INTO cities (name, sort_order, is_active, country) "
            "VALUES (:n, 9999, :a, :c) RETURNING id"
        ),
        {"n": name, "a": active, "c": country},
    )
    return int(r.scalar_one())


async def _arena(db_session, city_id: int, name: str, *, lat=None, lon=None) -> int:
    r = await db_session.execute(
        text(
            "INSERT INTO arenas (city_id, name, latitude, longitude, venue_type, is_active, is_confirmed) "
            "VALUES (:c, :n, :lat, :lon, 'ice', true, true) RETURNING id"
        ),
        {"c": city_id, "n": name, "lat": lat, "lon": lon},
    )
    return int(r.scalar_one())


async def _suggest(db_session, *, city_id=None, new_city=None, name="Ледовая арена-пса", kind="ice",
                   details=None, contact=None, author=None) -> int:
    res = await create_place_suggestion(
        db_session, source="site" if author is None else "miniapp", kind=kind, city_id=city_id,
        new_city=new_city, name=name, address=None, details=details or {}, contact=contact,
        author_telegram_id=author, client_ip=None,
    )
    return int(res["id"])


async def _status(db_session, sid: int):
    return (await db_session.execute(
        text("SELECT status, reject_reason, closed_at, target_arena_id FROM place_suggestions WHERE id=:id"),
        {"id": sid},
    )).one()


@pytest.mark.asyncio
async def test_list_tabs_split_by_status(db_session):
    city_id = await _city(db_session, "Пса-Список")
    a = await _suggest(db_session, city_id=city_id, name="Каток А", contact="@anna_skate")
    b = await _suggest(db_session, new_city={"name": "Пса-Новгород", "country": "RU"}, name="Каток Б")
    c = await _suggest(db_session, city_id=city_id, name="Каток В")
    await db_session.execute(text("UPDATE place_suggestions SET status='needs_info' WHERE id=:id"), {"id": b})
    await reject_place_suggestion(db_session, c, "spam")

    new_ids = [r["id"] for r in await list_place_suggestions(db_session, tab="new")]
    waiting_ids = [r["id"] for r in await list_place_suggestions(db_session, tab="waiting")]
    closed_ids = [r["id"] for r in await list_place_suggestions(db_session, tab="closed")]
    assert a in new_ids and b not in new_ids and c not in new_ids
    assert waiting_ids.count(b) == 1 and a not in waiting_ids
    assert c in closed_ids and a not in closed_ids

    row_a = next(r for r in await list_place_suggestions(db_session, tab="new") if r["id"] == a)
    assert row_a["city_label"] == "Пса-Список" and row_a["is_new_city"] is False
    assert row_a["has_contact"] is True and row_a["kind"] == "ice" and row_a["name"] == "Каток А"
    row_b = next(r for r in await list_place_suggestions(db_session, tab="waiting") if r["id"] == b)
    assert row_b["city_label"] == "Пса-Новгород" and row_b["is_new_city"] is True
    assert row_b["has_contact"] is False


@pytest.mark.asyncio
async def test_list_rejects_unknown_tab(db_session):
    with pytest.raises(PlaceSuggestionAdminError):
        await list_place_suggestions(db_session, tab="all")


@pytest.mark.asyncio
async def test_get_returns_messages_and_similar(db_session):
    city_id = await _city(db_session, "Пса-Похожие")
    dup = await _arena(db_session, city_id, "Ледовая арена-пса")
    sid = await _suggest(db_session, city_id=city_id)
    await db_session.execute(
        text("INSERT INTO place_suggestion_messages (suggestion_id, direction, body) VALUES (:s, 'note', 'x')"),
        {"s": sid},
    )
    d = await get_place_suggestion(db_session, sid)
    assert d["id"] == sid and d["status"] == "new" and d["city_name"] == "Пса-Похожие"
    assert [m["body"] for m in d["messages"]] == ["x"]
    assert [s["arena_id"] for s in d["similar"]] == [dup]


@pytest.mark.asyncio
async def test_get_new_city_has_no_similar_and_missing_is_error(db_session):
    sid = await _suggest(db_session, new_city={"name": "Пса-Пустоград", "country": "BY"})
    assert (await get_place_suggestion(db_session, sid))["similar"] == []
    with pytest.raises(PlaceSuggestionAdminError) as exc:
        await get_place_suggestion(db_session, 99_999_999)
    assert exc.value.code == "not_found"


@pytest.mark.asyncio
async def test_patch_open_suggestion_normalizes_and_ignores_unknown(db_session):
    city_id = await _city(db_session, "Пса-Правка")
    sid = await _suggest(db_session, new_city={"name": "Пса-Опечатка", "country": "BY"})
    d = await patch_place_suggestion(db_session, sid, {
        "name": "  Новое   имя ", "city_id": city_id, "latitude": 53.9, "longitude": 27.5,
        "details": {"price_adult": "12", "junk": "x"}, "status": "approved",
    })
    assert d["name"] == "Новое имя" and d["city_id"] == city_id and d["status"] == "new"
    assert d["details"] == {"price_adult": "12"} and d["latitude"] == pytest.approx(53.9)


@pytest.mark.asyncio
async def test_patch_rejects_bad_values(db_session):
    sid = await _suggest(db_session, new_city={"name": "Пса-Плохо", "country": "BY"})
    for fields in ({"name": "  "}, {"city_id": 99_999_999}, {"new_city_country": "RUS"},
                   {"latitude": 123}, {"new_city_name": None}):
        with pytest.raises(PlaceSuggestionAdminError):
            await patch_place_suggestion(db_session, sid, fields)


@pytest.mark.asyncio
async def test_patch_closed_suggestion_fails(db_session):
    sid = await _suggest(db_session, new_city={"name": "Пса-Закрыто", "country": "BY"})
    await reject_place_suggestion(db_session, sid, "closed")
    with pytest.raises(PlaceSuggestionAdminError) as exc:
        await patch_place_suggestion(db_session, sid, {"name": "X"})
    assert exc.value.code == "closed"


@pytest.mark.asyncio
async def test_reject_closes_with_reason(db_session):
    sid = await _suggest(db_session, new_city={"name": "Пса-Отказ", "country": "BY"})
    with pytest.raises(PlaceSuggestionAdminError):
        await reject_place_suggestion(db_session, sid, "boring")
    await reject_place_suggestion(db_session, sid, "not_ice")
    status, reason, closed_at, _ = await _status(db_session, sid)
    assert status == "rejected" and reason == "not_ice" and closed_at is not None
    with pytest.raises(PlaceSuggestionAdminError):
        await reject_place_suggestion(db_session, sid, "spam")


@pytest.mark.asyncio
async def test_duplicate_copies_only_into_empty_fields(db_session):
    city_id = await _city(db_session, "Пса-Дубль")
    target = await _arena(db_session, city_id, "Дворец спорта-пса")
    await db_session.execute(
        text(
            "INSERT INTO arena_profiles (arena_id, city_id, slug, phone, amenities, social_urls) "
            "VALUES (:a, :c, 'dvorec-psa', '+375 29 000-00-00', '{}'::jsonb, '{}'::jsonb)"
        ),
        {"a": target, "c": city_id},
    )
    sid = await _suggest(db_session, city_id=city_id, name="Дворец", details={
        "link": "+375 29 111-22-33", "price_adult": "10", "hours": "10:00–22:00",
    })
    await mark_duplicate(db_session, sid, target, ["phone", "visitor_prices", "opening_hours"])
    status, _, closed_at, target_id = await _status(db_session, sid)
    assert status == "duplicate" and closed_at is not None and target_id == target
    phone, prices, hours = (await db_session.execute(
        text("SELECT phone, visitor_prices, opening_hours FROM arena_profiles WHERE arena_id=:a"), {"a": target}
    )).one()
    assert phone == "+375 29 000-00-00"
    assert prices == {"adult": "10", "currency": "BYN", "source": "visitors"}
    assert hours == {"daily": {"open": "10:00", "close": "22:00"}}


@pytest.mark.asyncio
async def test_duplicate_rejects_unknown_field_and_missing_target(db_session):
    city_id = await _city(db_session, "Пса-Дубль2")
    target = await _arena(db_session, city_id, "Цель")
    sid = await _suggest(db_session, city_id=city_id)
    with pytest.raises(PlaceSuggestionAdminError):
        await mark_duplicate(db_session, sid, target, ["name"])
    with pytest.raises(PlaceSuggestionAdminError) as exc:
        await mark_duplicate(db_session, sid, 99_999_999, [])
    assert exc.value.code == "arena_not_found"
