"""TASK-204: arena schedule_mode on public API, SSR, admin, ice day."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import get_city_ice_day
from src.application.place_page import _schedule_html, load_place_view
from src.shared.arena_schedule_mode import PHONE_LINE, SEASON_CLOSED_LINE
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_city


async def _set_mode(
    db_session,
    arena_id: int,
    *,
    mode: str,
    reopen: date | None = None,
    note: str | None = None,
) -> None:
    await db_session.execute(
        text(
            """
            UPDATE arena_profiles
            SET schedule_mode = :mode, reopen_date = :reopen, schedule_mode_note = :note
            WHERE arena_id = :id
            """
        ),
        {"id": arena_id, "mode": mode, "reopen": reopen, "note": note},
    )


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_public_list_exposes_schedule_mode(app_use_test_db, db_session, client) -> None:
    cid = await _insert_city(db_session, name=f"Mode-{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, cid, name="Телефонный каток", phone="+375291112233")
    await _set_mode(db_session, arena_id, mode="phone")
    await db_session.commit()

    r = await client.get(f"/api/public/ice/arenas?city_id={cid}&intent=skate")
    assert r.status_code == 200
    item = next(x for x in r.json()["items"] if x["id"] == arena_id)
    assert item["schedule_mode"] == "phone"
    assert item["live"]["kind"] == "phone"
    assert item["live"]["text"] == PHONE_LINE


@pytest.mark.asyncio
async def test_season_closed_excluded_from_ice_day(app_use_test_db, db_session) -> None:
    cid = await _insert_city(db_session, name=f"Day-{uuid.uuid4().hex[:6]}")
    open_arena = await _insert_arena(db_session, cid, name="Открытый")
    closed_arena = await _insert_arena(db_session, cid, name="Закрытый сезон")
    await _set_mode(db_session, closed_arena, mode="season_closed", note="ремонт")
    target = date.today() + timedelta(days=1)
    await _add_future_session(db_session, open_arena, days_ahead=1, starts_at_local="19:00")
    await _add_future_session(db_session, closed_arena, days_ahead=1, starts_at_local="18:00")
    await db_session.commit()

    now = datetime.now(timezone.utc)
    day = await get_city_ice_day(db_session, city_id=cid, on_date=target, now=now)
    arena_ids = {a["arena_id"] for a in day.get("arenas") or []}
    assert open_arena in arena_ids
    assert closed_arena not in arena_ids


@pytest.mark.asyncio
async def test_place_page_phone_mode_ssr(app_use_test_db, db_session) -> None:
    cid = await _insert_city(db_session, name=f"Place-{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, cid, name="По телефону", phone="+375291112233")
    await _set_mode(db_session, arena_id, mode="phone")
    await db_session.commit()

    view = await load_place_view(db_session, str(arena_id))
    assert view is not None
    html = _schedule_html(view, base_path=f"/p/{arena_id}", invite=False)
    assert PHONE_LINE in html
    assert "tel:+375291112233" in html


@pytest.mark.asyncio
async def test_place_page_season_closed_ssr(app_use_test_db, db_session) -> None:
    cid = await _insert_city(db_session, name=f"Closed-{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, cid, name="Каток Жодино закрыт")
    reopen = date.today() + timedelta(days=60)  # всегда в будущем, иначе «откроется» пропадёт
    await _set_mode(
        db_session,
        arena_id,
        mode="season_closed",
        reopen=reopen,
        note="ремонт",
    )
    await db_session.commit()

    view = await load_place_view(db_session, str(arena_id))
    html = _schedule_html(view, base_path=f"/p/{arena_id}", invite=False)
    assert SEASON_CLOSED_LINE in html
    assert f"откроется {reopen:%d.%m}" in html
    assert "ремонт" in html


@pytest.mark.asyncio
async def test_admin_patch_schedule_mode(app_use_test_db, db_session) -> None:
    from src.api.miniapp_auth.deps import get_admin_miniapp_principal
    from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal

    cid = await _insert_city(db_session, name=f"Admin-{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, cid, name="Админ режим")
    reopen_iso = (date.today() + timedelta(days=90)).isoformat()
    await db_session.commit()

    app.dependency_overrides[get_admin_miniapp_principal] = lambda: MiniAppPrincipal(
        platform=MiniAppPlatform.TELEGRAM, user_id=4242
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bad = await client.patch(
            f"/api/webapp/admin/arenas/{arena_id}",
            json={"schedule_mode": "nope"},
        )
        assert bad.status_code == 400
        ok = await client.patch(
            f"/api/webapp/admin/arenas/{arena_id}",
            json={
                "schedule_mode": "season_closed",
                "reopen_date": reopen_iso,
                "schedule_mode_note": "тест",
            },
        )
        assert ok.status_code == 200
    app.dependency_overrides.pop(get_admin_miniapp_principal, None)

    row = (
        await db_session.execute(
            text(
                "SELECT schedule_mode, reopen_date, schedule_mode_note FROM arena_profiles WHERE arena_id = :id"
            ),
            {"id": arena_id},
        )
    ).one()
    assert row[0] == "season_closed"
    assert str(row[1]) == reopen_iso
    assert row[2] == "тест"


@pytest.mark.asyncio
async def test_invalid_phone_not_shown_in_ssr_and_api(app_use_test_db, db_session, client) -> None:
    """TASK-207: телефоны без минимум 7 цифр не показываются на SSR и в публичном API."""
    from src.application.place_page import _contacts_html, _schedule_mode_call_html
    from src.application.arena_public_use_cases import get_public_arena_card

    cid = await _insert_city(db_session, name=f"Phone-{uuid.uuid4().hex[:6]}")

    # Арена с невалидным телефоном (было на проде: "unknown (только email/соцсети)")
    invalid_id = await _insert_arena(
        db_session, cid, name="Без телефона", phone="unknown (только email/соцсети)"
    )
    await _set_mode(db_session, invalid_id, mode="phone")

    # Арена с коротким телефоном (меньше 7 цифр)
    short_id = await _insert_arena(db_session, cid, name="Короткий", phone="123-45")
    await _set_mode(db_session, short_id, mode="phone")

    # Арена с валидным телефоном
    valid_id = await _insert_arena(db_session, cid, name="Валидный", phone="+375291234567")
    await _set_mode(db_session, valid_id, mode="phone")

    await db_session.commit()

    # Проверяем SSR place_page для арены с невалидным телефоном
    view_invalid = await load_place_view(db_session, str(invalid_id))
    assert view_invalid is not None
    contacts_html = _contacts_html(view_invalid["card"])
    assert "tel:" not in contacts_html  # Не должно быть ссылки tel:
    assert "unknown" not in contacts_html  # Не должен показываться невалидный телефон

    call_html = _schedule_mode_call_html(view_invalid["card"])
    assert call_html == ""  # Режим phone без валидного телефона — пустая кнопка "Позвонить"

    # Проверяем SSR для арены с коротким телефоном
    view_short = await load_place_view(db_session, str(short_id))
    assert view_short is not None
    contacts_short = _contacts_html(view_short["card"])
    assert "tel:" not in contacts_short
    call_short = _schedule_mode_call_html(view_short["card"])
    assert call_short == ""

    # Проверяем SSR для арены с валидным телефоном
    view_valid = await load_place_view(db_session, str(valid_id))
    assert view_valid is not None
    contacts_valid = _contacts_html(view_valid["card"])
    assert "tel:+375291234567" in contacts_valid
    call_valid = _schedule_mode_call_html(view_valid["card"])
    assert "tel:+375291234567" in call_valid
    assert call_valid != ""

    # Проверяем публичный API
    card_invalid = await get_public_arena_card(db_session, str(invalid_id))
    assert card_invalid is not None
    assert card_invalid["phone"] is None  # Невалидный телефон не возвращается
    assert card_invalid["contacts"]["phone"] is None

    card_short = await get_public_arena_card(db_session, str(short_id))
    assert card_short is not None
    assert card_short["phone"] is None

    card_valid = await get_public_arena_card(db_session, str(valid_id))
    assert card_valid is not None
    assert card_valid["phone"] == "+375291234567"
    assert card_valid["contacts"]["phone"] == "+375291234567"

    # Проверяем HTTP API /api/public/ice/arenas/{id}
    r_invalid = await client.get(f"/api/public/ice/arenas/{invalid_id}")
    assert r_invalid.status_code == 200
    assert r_invalid.json()["phone"] is None

    r_valid = await client.get(f"/api/public/ice/arenas/{valid_id}")
    assert r_valid.status_code == 200
    assert r_valid.json()["phone"] == "+375291234567"

