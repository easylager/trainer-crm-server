"""TASK-304 (доделка): именная открытка «Зови» на домашний матч Динамо."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from sqlalchemy import text

from tests.api.test_hockey_event import _client, _env, _match, arena  # noqa: F401
from tests.api.test_ice_invites import _headers

START = datetime(2026, 12, 2, 16, 30, tzinfo=timezone.utc)  # ср, 2 декабря, 19:30 по Минску


async def _invite(client, **body):
    return await client.post(
        "/api/public/invites", json={"from_name": "Макс", "to_name": "Лера", **body}, headers=_headers()
    )


@pytest.mark.asyncio
async def test_postcard_for_a_match_is_created_read_and_rendered(app_use_test_db, db_session, arena) -> None:
    match_id = await _match(db_session, starts_at=START)
    await db_session.commit()
    async with _client() as client:
        created = await _invite(client, match_id=match_id)
        assert created.status_code == 201, created.text
        code = created.json()["code"]
        card = (await client.get(f"/api/public/invites/{code}")).json()
        page = await client.get(f"/zovi/{code}")
        og = await client.get(f"/zovi/{code}/og.png")
        ticket = await client.get(f"/zovi/{code}/ticket.png?t=2&s=5&f=1&k=0")
        ics = await client.get(f"/zovi/{code}/event.ics")
    assert card["kind"] == "hockey_match" and card["state"] == "ok"
    assert card["match"]["title"] == "Динамо-Минск — СКА" and card["match"]["start_param"] == f"kkm_{match_id}"
    assert card["session"]["id"] is None and card["session"]["arena"]["id"] == arena["arena_id"]
    assert card["session"]["starts_at_local"] == "19:30" and card["next_session"] is None
    assert page.status_code == 200
    assert "пойдёшь со мной на матч?" in page.text and "Динамо-Минск — СКА" in page.text
    assert f"https://t.me/glide_test_bot?startapp=kkm_{match_id}" in page.text, "страница ведёт на матч"
    assert Image.open(io.BytesIO(og.content)).size == (1200, 630)
    assert Image.open(io.BytesIO(ticket.content)).size == (1080, 1350)
    assert ics.status_code == 200 and "SUMMARY:Матч с" in ics.text
    row = (
        await db_session.execute(
            text("SELECT session_id, match_id, kind FROM ice_invites WHERE code = :c"), {"c": code}
        )
    ).one()
    assert row.session_id is None and row.match_id == match_id and row.kind == "hockey_match"


@pytest.mark.asyncio
async def test_postcard_answer_works_and_state_follows_the_match(app_use_test_db, db_session, arena) -> None:
    match_id = await _match(db_session, starts_at=START)
    await db_session.commit()
    async with _client() as client:
        code = (await _invite(client, match_id=match_id)).json()["code"]
        answer = await client.post(
            f"/api/public/invites/{code}/answer",
            json={"device_token": "d" * 20, "tries": 1, "resist_ms": 900, "falls": 0, "tricked": False},
            headers=_headers(),
        )
        assert answer.status_code == 200, answer.text
        await db_session.execute(text("UPDATE hockey_matches SET status = 'cancelled' WHERE id = :i"), {"i": match_id})
        await db_session.commit()
        gone = (await client.get(f"/api/public/invites/{code}")).json()
        late = await client.post(
            f"/api/public/invites/{code}/answer",
            json={"device_token": "e" * 20, "tries": 1, "resist_ms": 900, "falls": 0, "tricked": False},
            headers=_headers(),
        )
    assert gone["state"] == "gone" and late.status_code == 409


@pytest.mark.asyncio
async def test_postcard_needs_exactly_one_target_and_a_real_home_match(
    app_use_test_db, db_session, arena, monkeypatch
) -> None:
    home = await _match(db_session, starts_at=START)
    away = await _match(db_session, starts_at=START, home="СКА", away="Динамо-Минск")
    started = await _match(db_session, starts_at=datetime.now(timezone.utc) - timedelta(hours=1))
    await db_session.commit()
    async with _client() as client:
        assert (await _invite(client)).status_code == 422
        assert (await _invite(client, match_id=home, session_id=1)).status_code == 422
        assert (await _invite(client, match_id=away)).status_code == 422
        assert (await _invite(client, match_id=started)).status_code == 422
        assert (await _invite(client, match_id=999_999_999)).status_code == 422
        monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "0")
        assert (await _invite(client, match_id=home)).status_code == 404
    count = (await db_session.execute(text("SELECT COUNT(*) FROM ice_invites WHERE match_id IS NOT NULL"))).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_invite_row_cannot_point_at_a_session_and_a_match_at_once(db_session, arena) -> None:
    from sqlalchemy.exc import IntegrityError

    from tests.api.test_ice_invites import _at, _insert_session

    match_id = await _match(db_session, starts_at=START)
    session_id = await _insert_session(db_session, arena["arena_id"], starts_at=_at(days=3))
    with pytest.raises(IntegrityError, match="ck_ice_invites_one_target"):
        await db_session.execute(
            text("""
                INSERT INTO ice_invites (code, status_key_hash, session_id, match_id, arena_id, kind,
                                         starts_at_utc, ends_at_utc, from_name)
                VALUES ('abcd2345', :h, :s, :m, :a, 'hockey_match', now(), now(), 'Макс')
                """),
            {"h": "0" * 64, "s": session_id, "m": match_id, "a": arena["arena_id"]},
        )
