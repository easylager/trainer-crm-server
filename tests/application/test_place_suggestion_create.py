import pytest
from sqlalchemy import text

from src.application import place_suggestion_use_cases as uc
from src.application.place_suggestion_notify import (
    format_place_suggestion_notice,
    place_suggestion_keyboard,
)
from src.application.place_suggestion_use_cases import create_place_suggestion
from src.shared.place_suggestion import PLACE_SUGGEST_APPROVE_PREFIX, PlaceSuggestionError


async def _noop():
    return None


@pytest.fixture(autouse=True)
def _no_admin_push(monkeypatch):
    """Никаких реальных сообщений в Telegram из тестов: .env держит боевой токен админ-бота."""
    sent: list[int] = []
    monkeypatch.setattr(uc, "notify_admins_new_place_suggestion", lambda sid: sent.append(sid) or _noop())
    return sent


async def _any_city_id(db_session) -> int:
    row = (await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))).fetchone()
    if row:
        return int(row[0])
    r = await db_session.execute(text(
        "INSERT INTO cities (name, sort_order, is_active, country) VALUES ('Тестград', 1, true, 'BY') RETURNING id"
    ))
    await db_session.commit()
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_create_for_new_city_stores_raw_and_token(db_session):
    res = await create_place_suggestion(
        db_session, source="site", kind="ice", city_id=None,
        new_city={"name": "Уфа-тест-psg", "country": "ru", "region": "Башкортостан", "lat": 54.73, "lon": 55.96},
        name="Ледовая арена", address=None, details={"price_adult": "500"},
        contact="@anna_skate", author_telegram_id=None, client_ip="1.2.3.4",
    )
    row = (await db_session.execute(text(
        "SELECT status, new_city_name, new_city_country, contact_kind, details->>'price_adult', bind_token, "
        "new_city_region, new_city_lat, city_id "
        "FROM place_suggestions WHERE id=:id"), {"id": res["id"]})).one()
    assert row[0] == "new" and row[1] == "Уфа-тест-psg" and row[2] == "RU" and row[3] == "telegram"
    assert row[4] == "500" and row[5] and res["bind_token"] == row[5]
    assert row[6] == "Башкортостан" and row[7] == pytest.approx(54.73) and row[8] is None


@pytest.mark.asyncio
async def test_create_rejects_unknown_city_id(db_session):
    with pytest.raises(PlaceSuggestionError):
        await create_place_suggestion(
            db_session, source="site", kind="ice", city_id=999999, new_city=None,
            name="X", address=None, details={}, contact=None, author_telegram_id=None, client_ip=None,
        )


@pytest.mark.asyncio
async def test_create_rejects_empty_name(db_session):
    with pytest.raises(PlaceSuggestionError):
        await create_place_suggestion(
            db_session, source="site", kind="ice", city_id=None, new_city={"name": "Город", "country": "BY"},
            name="  ", address=None, details={}, contact=None, author_telegram_id=None, client_ip=None,
        )


@pytest.mark.asyncio
async def test_new_city_matching_existing_city_is_linked(db_session):
    city_id = await _any_city_id(db_session)
    name, country = (await db_session.execute(
        text("SELECT name, country FROM cities WHERE id=:id"), {"id": city_id})).one()
    res = await create_place_suggestion(
        db_session, source="site", kind="outdoor", city_id=None,
        new_city={"name": f"  {name.upper()} ", "country": country.lower()},
        name="Каток во дворе", address="ул. Ленина, 1", details={}, contact=None,
        author_telegram_id=None, client_ip=None,
    )
    row = (await db_session.execute(text(
        "SELECT city_id, new_city_name FROM place_suggestions WHERE id=:id"), {"id": res["id"]})).one()
    assert row[0] == city_id and row[1] is None


@pytest.mark.asyncio
async def test_create_from_miniapp_has_author_and_no_token(db_session, _no_admin_push):
    city_id = await _any_city_id(db_session)
    res = await create_place_suggestion(
        db_session, source="miniapp", kind="shop", city_id=city_id, new_city=None,
        name="Заточка у арены", address=None, details={"services": ["sharpening"]},
        contact=None, author_telegram_id=1304982166, client_ip=None,
    )
    assert res["bind_token"] is None
    assert _no_admin_push == [res["id"]]
    row = (await db_session.execute(text(
        "SELECT author_telegram_id, source, details->'services' FROM place_suggestions WHERE id=:id"),
        {"id": res["id"]})).one()
    assert row[0] == 1304982166 and row[1] == "miniapp" and row[2] == ["sharpening"]


@pytest.mark.asyncio
async def test_notify_failure_does_not_break_create(db_session, monkeypatch):
    async def boom(_sid):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(uc, "notify_admins_new_place_suggestion", boom)
    city_id = await _any_city_id(db_session)
    res = await create_place_suggestion(
        db_session, source="site", kind="school", city_id=city_id, new_city=None,
        name="Школа фигурного катания", address=None, details={"disciplines": ["figure"]},
        contact="anna@example.com", author_telegram_id=None, client_ip=None,
    )
    assert res["id"]


def test_notice_text_escapes_and_lists_signals():
    notice = format_place_suggestion_notice({
        "id": 7, "kind": "ice", "city_name": None, "new_city_name": "Уфа <b>",
        "name": "x", "details": {"price_adult": "500"}, "contact": "@anna_skate", "author_telegram_id": None,
    })
    assert notice.startswith("Новая заявка №7 · Каток · Уфа &lt;b&gt; (новый город)")
    assert "есть цены" in notice and "есть контакт" in notice


def test_notice_text_without_prices_or_contact():
    notice = format_place_suggestion_notice({
        "id": 8, "kind": "school", "city_name": "Минск", "new_city_name": None,
        "name": "x", "details": {}, "contact": None, "author_telegram_id": None,
    })
    assert notice == "Новая заявка №8 · Школа · Минск"


def test_keyboard_offers_approve_only_without_duplicates():
    kb = place_suggestion_keyboard(9, base_url="https://x.test", can_approve=True)
    buttons = [b for row in kb.inline_keyboard for b in row]
    assert buttons[0].web_app.url == "https://x.test/webapp/admin-place-suggestions?id=9"
    assert buttons[1].callback_data == f"{PLACE_SUGGEST_APPROVE_PREFIX}9"

    kb = place_suggestion_keyboard(9, base_url="https://x.test", can_approve=False)
    assert [b.text for row in kb.inline_keyboard for b in row] == ["Открыть"]


@pytest.mark.asyncio
async def test_same_name_city_in_another_country_stays_new(db_session):
    cid = int((await db_session.execute(text(
        "INSERT INTO cities (name, sort_order, is_active, country) VALUES ('Пситест-Пушкино', 1, true, 'BY') "
        "RETURNING id"))).scalar_one())
    res = await create_place_suggestion(
        db_session, source="site", kind="ice", city_id=None,
        new_city={"name": "Пситест-Пушкино", "country": "RU"},
        name="Каток", address=None, details={}, contact=None, author_telegram_id=None, client_ip=None,
    )
    row = (await db_session.execute(text(
        "SELECT city_id, new_city_name, new_city_country FROM place_suggestions WHERE id=:id"),
        {"id": res["id"]})).one()
    assert row == (None, "Пситест-Пушкино", "RU")
    assert cid


@pytest.mark.asyncio
@pytest.mark.parametrize("country", ["RUS", "R1", "", None, "р"])
async def test_invalid_new_city_country_is_rejected(db_session, country):
    with pytest.raises(PlaceSuggestionError):
        await create_place_suggestion(
            db_session, source="site", kind="ice", city_id=None,
            new_city={"name": "Пситест-Город", "country": country},
            name="Каток", address=None, details={}, contact=None, author_telegram_id=None, client_ip=None,
        )


@pytest.mark.asyncio
async def test_non_list_services_do_not_break_create(db_session):
    city_id = await _any_city_id(db_session)
    res = await create_place_suggestion(
        db_session, source="site", kind="shop", city_id=city_id, new_city=None,
        name="Заточка", address=None, details={"services": 5}, contact=None,
        author_telegram_id=None, client_ip=None,
    )
    assert res["id"]
