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
    from src.application.arena_public_use_cases import get_public_arena_card

    cid = await _insert_city(db_session, name=f"Phone-{uuid.uuid4().hex[:6]}")

    # Арена с невалидным телефоном (было на проде: "unknown (только email/соцсети)")
    invalid_id = await _insert_arena(
        db_session, cid, name="Без телефона", phone="unknown (только email/соцсети)"
    )
    await _set_mode(db_session, invalid_id, mode="phone")

    # Арена с коротким телефоном (6 цифр - граница)
    short_id = await _insert_arena(db_session, cid, name="Короткий 6", phone="123-456")
    await _set_mode(db_session, short_id, mode="phone")

    # Арена с минимально валидным телефоном (7 цифр)
    min_valid_id = await _insert_arena(db_session, cid, name="Минимум 7", phone="1234567")
    await _set_mode(db_session, min_valid_id, mode="phone")

    # Арена с полностью валидным телефоном
    valid_id = await _insert_arena(db_session, cid, name="Валидный", phone="+375291234567")
    await _set_mode(db_session, valid_id, mode="phone")

    await db_session.commit()

    # Проверяем публичный API карточки: невалидный телефон возвращается как null
    card_invalid = await get_public_arena_card(db_session, str(invalid_id))
    assert card_invalid is not None
    assert card_invalid["phone"] is None
    assert card_invalid["contacts"]["phone"] is None

    card_short = await get_public_arena_card(db_session, str(short_id))
    assert card_short is not None
    assert card_short["phone"] is None  # 6 цифр недостаточно

    card_min = await get_public_arena_card(db_session, str(min_valid_id))
    assert card_min is not None
    assert card_min["phone"] == "1234567"  # 7 цифр - граница, валиден

    card_valid = await get_public_arena_card(db_session, str(valid_id))
    assert card_valid is not None
    assert card_valid["phone"] == "+375291234567"
    assert card_valid["contacts"]["phone"] == "+375291234567"

    # Проверяем HTTP API /api/public/arenas/{id}
    r_invalid = await client.get(f"/api/public/arenas/{invalid_id}")
    assert r_invalid.status_code == 200
    assert r_invalid.json()["phone"] is None
    assert r_invalid.json()["contacts"]["phone"] is None

    r_short = await client.get(f"/api/public/arenas/{short_id}")
    assert r_short.status_code == 200
    assert r_short.json()["phone"] is None

    r_min = await client.get(f"/api/public/arenas/{min_valid_id}")
    assert r_min.status_code == 200
    assert r_min.json()["phone"] == "1234567"

    r_valid = await client.get(f"/api/public/arenas/{valid_id}")
    assert r_valid.status_code == 200
    assert r_valid.json()["phone"] == "+375291234567"

    # Проверяем SSR страницы места через HTTP GET (используем public_path из card)
    r_ssr_invalid = await client.get(card_invalid["public_path"] or f"/p/{invalid_id}")
    assert r_ssr_invalid.status_code == 200
    html_invalid = r_ssr_invalid.text
    assert "tel:" not in html_invalid
    # Сырой телефон «unknown (только email/…)» не должен попасть в HTML.
    # Класс .pick__open--unknown — состояние часов, не этот телефон.
    assert "только email/соцсети" not in html_invalid.lower()

    r_ssr_short = await client.get(card_short["public_path"] or f"/p/{short_id}")
    assert r_ssr_short.status_code == 200
    assert "tel:" not in r_ssr_short.text

    r_ssr_valid = await client.get(card_valid["public_path"] or f"/p/{valid_id}")
    assert r_ssr_valid.status_code == 200
    assert "tel:+375291234567" in r_ssr_valid.text

    # Проверяем списочный API /api/public/ice/arenas
    r_list = await client.get(f"/api/public/ice/arenas?city_id={cid}&intent=skate")
    assert r_list.status_code == 200
    items_by_id = {item["id"]: item for item in r_list.json()["items"]}

    assert invalid_id in items_by_id
    assert items_by_id[invalid_id]["phone"] is None

    assert short_id in items_by_id
    assert items_by_id[short_id]["phone"] is None

    assert valid_id in items_by_id
    assert items_by_id[valid_id]["phone"] == "+375291234567"

