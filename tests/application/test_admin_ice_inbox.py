"""Admin ice inbox: upload → parsed (Claude) → publish/reject, and the HTTP surface."""

from __future__ import annotations

import io
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from src.application import admin_ice_inbox as inbox


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, "PNG")
    return buf.getvalue()


def _spec(arena_id: int, *, days_ahead: int = 3) -> dict:
    d = (date.today() + timedelta(days=days_ahead)).isoformat()
    return {
        "arena_id": arena_id,
        "source": "тест",
        "defaults": {"kind": "public_skate", "duration_minutes": 45, "price_adult": "6.50"},
        "sessions": [{"date": d, "start": "14:00"}, {"date": d, "start": "15:30", "label": "Малая арена"}],
        "notes": ["Проверьте дату"],
    }


@pytest.fixture
async def arena(db_session, monkeypatch):
    await db_session.execute(text("INSERT INTO cities (id, name, country, is_active) VALUES (9921, 'ТестГород3', 'BY', true)"))
    await db_session.execute(
        text(
            "INSERT INTO arenas (id, name, city_id, is_active, is_confirmed, venue_type) "
            "VALUES (9922, 'Тест-арена 3', 9921, true, true, 'ice')"
        )
    )
    await db_session.commit()
    monkeypatch.setattr(inbox.s3, "upload_ice_inbox_image", lambda body, ct: "ice-inbox/test.png")
    monkeypatch.setattr(inbox.s3, "get_file", lambda key, allowed_prefixes=(): (_png(), "image/png"))
    return 9922


@pytest.mark.asyncio
async def test_upload_validation(db_session, arena):
    with pytest.raises(inbox.InboxError) as e:
        await inbox.add_upload(db_session, arena_id=arena, body=b"not an image", content_type="image/png", admin_telegram_id=1)
    assert e.value.code == "not_image"
    with pytest.raises(inbox.InboxError) as e:
        await inbox.add_upload(db_session, arena_id=arena, body=b"", content_type="image/png", admin_telegram_id=1)
    assert e.value.code == "empty"
    with pytest.raises(inbox.InboxError) as e:
        await inbox.add_upload(db_session, arena_id=999999, body=_png(), content_type="image/png", admin_telegram_id=1)
    assert e.value.code == "arena_not_found"


@pytest.mark.asyncio
async def test_full_flow_publish(db_session, arena, monkeypatch):
    new_id = await inbox.add_upload(db_session, arena_id=arena, body=_png(), content_type="image/png", admin_telegram_id=7)
    item = await inbox.get_item(db_session, new_id)
    assert item["status"] == "pending" and item["summary"] is None

    with pytest.raises(inbox.InboxError) as e:  # cannot publish before it is parsed
        await inbox.publish(db_session, new_id)
    assert e.value.code == "not_parsed"
    with pytest.raises(inbox.InboxError) as e:  # a spec for another arena is refused
        await inbox.submit_parsed(db_session, new_id, _spec(arena + 1))
    assert e.value.code == "arena_mismatch"

    assert await inbox.submit_parsed(db_session, new_id, _spec(arena)) == 2
    item = await inbox.get_item(db_session, new_id)
    assert item["status"] == "parsed" and item["summary"]["count"] == 2
    assert item["summary"]["notes"] == ["Проверьте дату"]
    assert item["summary"]["days"][0]["times"] == ["14:00", "15:30 · Малая арена"]

    async def fake_publish(spec):
        assert spec["arena_id"] == arena
        return [SimpleNamespace(status="ok", slot_count=2, error_message=None)]

    monkeypatch.setattr(inbox, "publish_spec", fake_publish)
    assert await inbox.publish(db_session, new_id) == 2
    item = await inbox.get_item(db_session, new_id)
    assert item["status"] == "published" and item["published_count"] == 2
    with pytest.raises(inbox.InboxError) as e:  # a closed item cannot be re-parsed
        await inbox.submit_parsed(db_session, new_id, _spec(arena))
    assert e.value.code == "closed"


@pytest.mark.asyncio
async def test_publish_failure_keeps_it_open(db_session, arena, monkeypatch):
    new_id = await inbox.add_upload(db_session, arena_id=arena, body=_png(), content_type="image/png", admin_telegram_id=7)
    await inbox.submit_parsed(db_session, new_id, _spec(arena))

    async def failing(spec):
        return [SimpleNamespace(status="error", slot_count=0, error_message="boom")]

    monkeypatch.setattr(inbox, "publish_spec", failing)
    with pytest.raises(inbox.InboxError) as e:
        await inbox.publish(db_session, new_id)
    assert e.value.code == "publish_failed"
    assert (await inbox.get_item(db_session, new_id))["status"] == "parsed"


@pytest.mark.asyncio
async def test_past_only_spec_is_refused(db_session, arena):
    new_id = await inbox.add_upload(db_session, arena_id=arena, body=_png(), content_type="image/png", admin_telegram_id=7)
    with pytest.raises(inbox.InboxError) as e:
        await inbox.submit_parsed(db_session, new_id, _spec(arena, days_ahead=-10))
    assert e.value.code == "empty_spec"


@pytest.mark.asyncio
async def test_reject_and_list(db_session, arena):
    a = await inbox.add_upload(db_session, arena_id=arena, body=_png(), content_type="image/png", admin_telegram_id=7)
    b = await inbox.add_upload(db_session, arena_id=arena, body=_png(), content_type="image/png", admin_telegram_id=7)
    assert await inbox.reject(db_session, a, "не тот каток")
    assert not await inbox.reject(db_session, a, "ещё раз")
    data = await inbox.list_inbox(db_session)
    by_id = {i["id"]: i for i in data["items"]}
    assert by_id[a]["status"] == "rejected" and by_id[a]["note"] == "не тот каток"
    assert by_id[b]["status"] == "pending" and data["open"] >= 1


@pytest.mark.asyncio
async def test_http_surface(db_session, arena, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from src.api.app import app
    from src.api.miniapp_auth.deps import get_admin_miniapp_principal
    from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal

    app.dependency_overrides[get_admin_miniapp_principal] = lambda: MiniAppPrincipal(
        platform=MiniAppPlatform.TELEGRAM, user_id=4242
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            bad = await c.post("/api/webapp/admin/ice-inbox", data={"arena_id": str(arena)},
                               files={"file": ("x.png", b"nope", "image/png")})
            assert bad.status_code == 400
            ok = await c.post("/api/webapp/admin/ice-inbox", data={"arena_id": str(arena)},
                              files={"file": ("x.png", _png(), "image/png")})
            assert ok.status_code == 200
            new_id = ok.json()["id"]
            assert (await c.get(f"/api/webapp/admin/ice-inbox/{new_id}/image")).status_code == 200
            assert (await c.get("/api/webapp/admin/ice-inbox/999999/image")).status_code == 404
            assert (await c.post(f"/api/webapp/admin/ice-inbox/{new_id}/publish")).status_code == 409
            lst = await c.get("/api/webapp/admin/ice-inbox")
            assert any(i["id"] == new_id for i in lst.json()["items"])
            rej = await c.post(f"/api/webapp/admin/ice-inbox/{new_id}/reject", json={"note": "тест"})
            assert rej.status_code == 200
            assert (await c.post(f"/api/webapp/admin/ice-inbox/{new_id}/reject", json={})).status_code == 409
            assert (await c.get("/webapp/admin-ice-inbox")).status_code == 200
    finally:
        app.dependency_overrides.pop(get_admin_miniapp_principal, None)


@pytest.mark.asyncio
async def test_publish_spec_through_real_pipeline(db_session, arena):
    """No mocks: the spec becomes real ice_sessions through scheduler → normalizer → publisher."""
    from src.application.manual_schedule_publish import publish_spec

    await db_session.execute(
        text(
            "INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config) "
            "VALUES (:a, 'manual_schedule_v1', true, 'weekly', now() + interval '7 days', "
            "CAST('{\"kind\": \"public_skate\", \"timezone\": \"Europe/Minsk\"}' AS jsonb))"
        ),
        {"a": arena},
    )
    await db_session.commit()
    outcomes = await publish_spec(_spec(arena))
    assert outcomes and outcomes[0].status == "ok" and outcomes[0].slot_count == 2
    rows = (
        await db_session.execute(
            text("SELECT starts_at_local, session_label, price_adult_minor FROM ice_sessions WHERE arena_id = :a ORDER BY 1"),
            {"a": arena},
        )
    ).all()
    assert [(str(r.starts_at_local)[:5], r.session_label, r.price_adult_minor) for r in rows] == [
        ("14:00", None, 650), ("15:30", "Малая арена", 650),
    ]
