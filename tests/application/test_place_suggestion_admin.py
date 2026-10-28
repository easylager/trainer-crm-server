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


@pytest.fixture
def approved_notices(monkeypatch):
    calls: list[int] = []

    async def _fake(sid, **_kw):
        calls.append(sid)

    monkeypatch.setattr(uc, "notify_author_approved", _fake)
    return calls


@pytest.mark.asyncio
async def test_approve_new_city_creates_city_arena_and_profile(db_session, approved_notices):
    from src.application.place_suggestion_use_cases import approve_place_suggestion

    sid = await _suggest(
        db_session,
        new_city={"name": "Пса-Уфа", "country": "RU", "region": "Башкортостан", "lat": 54.73, "lon": 55.96},
        name="Ледовая арена Уфа",
        details={"price_adult": "500", "price_rental": "300", "hours": "ежедневно 10:00–22:00",
                 "link": "https://ice-ufa.example.ru"},
        author=777001,
    )
    res = await approve_place_suggestion(db_session, sid, admin_id=4242)
    assert res["city_kept_inactive"] is False and res["slug"]
    assert res["url"] == f"/p/{res['url'].split('/')[2]}/{res['slug']}"

    city = (await db_session.execute(text(
        "SELECT name, is_active, country, price_group, latitude, longitude, region FROM cities WHERE id=:id"),
        {"id": res["city_id"]})).one()
    assert city[0] == "Пса-Уфа" and city[1] is True and city[2] == "RU" and city[3] == "RU_BASE"
    assert city[4] == pytest.approx(54.73) and city[5] == pytest.approx(55.96) and city[6] == "Башкортостан"

    arena = (await db_session.execute(text(
        "SELECT city_id, name, venue_type, is_active, is_confirmed, confirmed_at, confirmed_by_admin_id "
        "FROM arenas WHERE id=:id"), {"id": res["arena_id"]})).one()
    assert arena[0] == res["city_id"] and arena[1] == "Ледовая арена Уфа" and arena[2] == "ice"
    assert arena[3] is True and arena[4] is True and arena[5] is not None and arena[6] == 4242

    prof = (await db_session.execute(text(
        "SELECT slug, status, visitor_prices, opening_hours, website_url, phone, schedule_mode "
        "FROM arena_profiles WHERE arena_id=:id"), {"id": res["arena_id"]})).one()
    assert prof[0] == res["slug"] and prof[1] == "published"
    assert prof[2] == {"adult": "500", "rental": "300", "currency": "RUB", "source": "visitors"}
    assert prof[3] == {"daily": {"open": "10:00", "close": "22:00"}}
    assert prof[4] == "https://ice-ufa.example.ru" and prof[5] is None and prof[6] == "phone"

    st = (await db_session.execute(text(
        "SELECT status, result_arena_id, city_id, closed_at FROM place_suggestions WHERE id=:id"),
        {"id": sid})).one()
    assert st[0] == "approved" and st[1] == res["arena_id"] and st[2] == res["city_id"] and st[3] is not None
    assert approved_notices == [sid]


@pytest.mark.asyncio
async def test_approve_in_inactive_city_keeps_it_hidden(db_session, approved_notices):
    from src.application.place_suggestion_use_cases import approve_place_suggestion

    hidden = await _city(db_session, "Пса-Москва", active=False, country="RU")
    sid = await _suggest(db_session, city_id=hidden, name="Каток в парке", kind="outdoor",
                         details={"link": "+7 (495) 123-45-67", "hours": "по выходным, днём"})
    res = await approve_place_suggestion(db_session, sid, admin_id=1)
    assert res["city_id"] == hidden and res["city_kept_inactive"] is True
    assert (await db_session.execute(text("SELECT is_active FROM cities WHERE id=:id"), {"id": hidden})).scalar() is False
    phone, hours, prices = (await db_session.execute(text(
        "SELECT phone, opening_hours, visitor_prices FROM arena_profiles WHERE arena_id=:id"),
        {"id": res["arena_id"]})).one()
    assert phone == "+7 (495) 123-45-67" and hours is None and prices is None


@pytest.mark.asyncio
async def test_approve_new_city_matching_existing_inactive_city_reuses_it(db_session, approved_notices):
    from src.application.place_suggestion_use_cases import approve_place_suggestion

    sid = await _suggest(db_session, new_city={"name": "Пса-Скрытоград", "country": "BY"})
    hidden = await _city(db_session, "Пса-Скрытоград", active=False)
    res = await approve_place_suggestion(db_session, sid, admin_id=1)
    assert res["city_id"] == hidden and res["city_kept_inactive"] is True


@pytest.mark.asyncio
async def test_approve_shop_maps_services_to_amenities(db_session, approved_notices):
    from src.application.place_suggestion_use_cases import approve_place_suggestion

    city_id = await _city(db_session, "Пса-Магазин")
    sid = await _suggest(db_session, city_id=city_id, kind="shop", name="Заточка-пса",
                         details={"services": ["sharpening", "sale"]})
    res = await approve_place_suggestion(db_session, sid, admin_id=1)
    venue, amenities = (await db_session.execute(text(
        "SELECT a.venue_type, p.amenities FROM arenas a JOIN arena_profiles p ON p.arena_id=a.id WHERE a.id=:id"),
        {"id": res["arena_id"]})).one()
    assert venue == "shop" and amenities == {"skate_sharpening": True, "retail": True}


@pytest.mark.asyncio
async def test_approve_closed_fails_and_notify_errors_are_swallowed(db_session, monkeypatch):
    from src.application.place_suggestion_use_cases import approve_place_suggestion

    async def _boom(*_a, **_kw):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(uc, "notify_author_approved", _boom)
    city_id = await _city(db_session, "Пса-Закрытая")
    sid = await _suggest(db_session, city_id=city_id, name="Каток-пса-сбой")
    res = await approve_place_suggestion(db_session, sid, admin_id=1)
    assert res["arena_id"]
    with pytest.raises(PlaceSuggestionAdminError) as exc:
        await approve_place_suggestion(db_session, sid, admin_id=1)
    assert exc.value.code == "closed"
    n = (await db_session.execute(text("SELECT count(*) FROM arenas WHERE name='Каток-пса-сбой'"))).scalar()
    assert n == 1


def test_daily_hours_and_link_parsing():
    assert uc.daily_hours_from_text("с 9 до 21") == {"daily": {"open": "09:00", "close": "21:00"}}
    assert uc.daily_hours_from_text("Пн-Пт 10:00-20:00") is None
    assert uc.link_profile_fields("ice.by") == {"website_url": "https://ice.by"}
    assert uc.link_profile_fields("+375 (29) 111-22-33") == {"phone": "+375 (29) 111-22-33"}
    assert uc.link_profile_fields("спросить на кассе") == {}


@pytest.mark.asyncio
async def test_approve_non_daily_hours_stay_out_of_profile(db_session, approved_notices):
    from src.application.place_suggestion_use_cases import approve_place_suggestion

    city_id = await _city(db_session, "Пса-Часы")
    sid = await _suggest(db_session, city_id=city_id, name="Каток-часы",
                         details={"hours": "Пн–Пт 18:00–22:00, Сб–Вс 10:00–22:00"})
    res = await approve_place_suggestion(db_session, sid, admin_id=1)
    hours, note, mode = (await db_session.execute(text(
        "SELECT opening_hours, schedule_mode_note, schedule_mode FROM arena_profiles WHERE arena_id=:id"),
        {"id": res["arena_id"]})).one()
    assert hours is None and note is None and mode == "phone"
    kept = (await db_session.execute(text(
        "SELECT details->>'hours' FROM place_suggestions WHERE id=:id"), {"id": sid})).scalar()
    assert kept.startswith("Пн–Пт")


@pytest.mark.asyncio
async def test_approve_new_city_invalidates_cache_and_flags(db_session, approved_notices, monkeypatch):
    from src.application.place_suggestion_use_cases import approve_place_suggestion

    monkeypatch.setenv("ICE_DISCOVERY_COUNTRIES", "BY,RU")
    cleared: list[bool] = []
    monkeypatch.setattr(uc, "invalidate_public_city_cache", lambda: cleared.append(True))
    sid = await _suggest(db_session, new_city={"name": "Пса-Алматы", "country": "KZ"},
                         details={"price_adult": "2000"})
    res = await approve_place_suggestion(db_session, sid, admin_id=1)
    assert cleared == [True] and res["city_created"] is True
    assert res["country_not_public"] is True
    assert res["profile_status"] == "published" and res["published"] is True
    prices = (await db_session.execute(text(
        "SELECT visitor_prices FROM arena_profiles WHERE arena_id=:id"), {"id": res["arena_id"]})).scalar()
    assert prices == {"adult": "2000", "currency": None, "source": "visitors"}

    by_city = await _city(db_session, "Пса-Кэш")
    sid2 = await _suggest(db_session, city_id=by_city, name="Каток-кэш")
    res2 = await approve_place_suggestion(db_session, sid2, admin_id=1)
    assert cleared == [True] and res2["city_created"] is False and res2["country_not_public"] is False


@pytest.mark.asyncio
async def test_approve_test_name_reports_draft(db_session, approved_notices):
    from src.application.place_suggestion_use_cases import approve_place_suggestion

    city_id = await _city(db_session, "Пса-Черновик")
    sid = await _suggest(db_session, city_id=city_id, name="Тестовая арена")
    res = await approve_place_suggestion(db_session, sid, admin_id=1)
    assert res["profile_status"] == "draft" and res["published"] is False


@pytest.mark.asyncio
async def test_patch_rejects_non_numeric_city_id(db_session):
    sid = await _suggest(db_session, new_city={"name": "Пса-Номер", "country": "BY"})
    with pytest.raises(PlaceSuggestionAdminError) as exc:
        await patch_place_suggestion(db_session, sid, {"city_id": "abc"})
    assert exc.value.code == "invalid"


@pytest.mark.asyncio
async def test_message_to_closed_suggestion_fails_and_keeps_status(db_session, monkeypatch):
    sent: list[dict] = []

    async def _fake_send(**kw):
        sent.append(kw)

    monkeypatch.setattr(uc, "send_client_plain_notification", _fake_send)
    sid = await _suggest(db_session, new_city={"name": "Пса-Закрытый-чат", "country": "BY"}, author=777002)
    await reject_place_suggestion(db_session, sid, "spam")
    with pytest.raises(PlaceSuggestionAdminError) as exc:
        await uc.send_message_to_author(db_session, sid, "Ещё вопрос")
    assert exc.value.code == "closed" and sent == []
    status, *_ = await _status(db_session, sid)
    n = (await db_session.execute(text(
        "SELECT count(*) FROM place_suggestion_messages WHERE suggestion_id=:id"), {"id": sid})).scalar()
    assert status == "rejected" and n == 0
