"""TASK-436 AC-5: «Позвонить и забронировать» (аренда льда) пишет public_contact_click с action=rink_call."""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.catalog_consumer_events import KIND_PUBLIC_CONTACT_CLICK
from src.application.place_visit_blocks import more_html
from src.application.public_web_cta import CONTACT_ACTION_RINK_CALL, contact_click_beacon_url, phone_beacon_script
from tests.api.test_public_arenas import _insert_arena, _insert_city


def test_rink_button_carries_rink_call_beacon() -> None:
    beacon = contact_click_beacon_url(action=CONTACT_ACTION_RINK_CALL, surface="place_page", city_id=3, arena_id=7)
    vv = {"more": [{"key": "rink", "title": "Аренда льда", "detail": {"rows": [{"label": "Час", "price": "300 BYN"}]}}]}
    html = more_html(vv, tel_href="tel:+375291112233", rink_beacon=beacon)
    assert 'href="tel:+375291112233" data-catalog-phone-beacon="/api/public/catalog/contact-click?action=rink_call' in html
    assert "arena_id=7" in html
    # Слушатель кликов на страницу ставится, раз кнопка с маяком есть.
    assert phone_beacon_script(html)


@pytest.mark.asyncio
async def test_rink_call_recorded_apart_from_phone(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "test-catalog-actor-secret-0123456789abcdef")
    city_id = await _insert_city(db_session, name=f"Аренда {uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, city_id, name="Каток")
    await db_session.commit()
    headers = {"User-Agent": f"Mozilla/5.0 (iPhone) Rink {uuid.uuid4().hex[:8]}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for action in ("phone", CONTACT_ACTION_RINK_CALL):
            url = contact_click_beacon_url(action=action, surface="place_page", city_id=city_id, arena_id=arena_id)
            resp = await client.post(url, headers=headers)
            assert resp.status_code == 204
    rows = (
        await db_session.execute(
            text(
                "SELECT payload->>'action', payload->>'ua_class' FROM catalog_consumer_events "
                "WHERE kind = :k AND arena_id = :a ORDER BY id"
            ),
            {"k": KIND_PUBLIC_CONTACT_CLICK, "a": arena_id},
        )
    ).all()
    assert [tuple(r) for r in rows] == [("phone", "human"), ("rink_call", "human")]
