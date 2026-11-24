"""TASK-450 (5.3): my_open_companies — приватность и фильтры моих компаний."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from src.application.ice_company.codes import new_public_code, tg_participant_key
from src.application.ice_company.mine import my_open_companies
from src.shared.config import Settings
from tests.api.test_ice_invites import _at, _insert_session, _place

_MINSK = ZoneInfo("Europe/Minsk")
_NOW = datetime.now(timezone.utc)


async def _company(db, *, event_session_id: int, organizer: str, name: str = "Каток") -> str:
    """Компания + ответ организатора «going» напрямую в базу (обход API — тест формирования списка)."""
    ev = (
        await db.execute(
            text(
                """
                SELECT s.id, s.kind, s.status, s.starts_at_utc, s.ends_at_utc, s.arena_id,
                       a.name AS arena_name, a.city_id
                FROM ice_sessions s JOIN arenas a ON a.id = s.arena_id WHERE s.id = :id
                """
            ),
            {"id": event_session_id},
        )
    ).mappings().one()
    event_id = (
        await db.execute(
            text(
                """
                INSERT INTO ice_company_events (kind, source_ref, starts_at, ends_at, venue_ref, venue_label, city_id, cancelled)
                VALUES (:k, :src, :st, :en, :vref, :vlabel, :cid, false) RETURNING id
                """
            ),
            {
                "k": str(ev["kind"]), "src": f"ice_session:{event_session_id}",
                "st": ev["starts_at_utc"], "en": ev["ends_at_utc"],
                "vref": f"arena:{int(ev['arena_id'])}", "vlabel": str(ev["arena_name"]),
                "cid": int(ev["city_id"]),
            },
        )
    ).scalar_one()
    code = new_public_code()
    global _LAST_CODE
    _LAST_CODE = code
    cid = (
        await db.execute(
            text(
                """
                INSERT INTO ice_companies (public_code, name, organizer_ref, event_id, event_version, status, expires_at)
                VALUES (:code, :name, :org, :eid, 1, 'open', :exp) RETURNING id
                """
            ),
            {"code": code, "name": name, "org": organizer, "eid": event_id, "exp": ev["ends_at_utc"] + timedelta(days=30)},
        )
    ).scalar_one()
    await db.execute(
        text(
            """
            INSERT INTO ice_company_responses (company_id, participant_key, display_name, status, source)
            VALUES (:c, :k, :n, 'going', 'tg')
            """
        ),
        {"c": cid, "k": organizer, "n": "Организатор"},
    )
    return code


async def _respond(db, code: str, key: str, name: str, status: str) -> None:
    await db.execute(
        text(
            """
            INSERT INTO ice_company_responses (company_id, participant_key, display_name, status, source)
            SELECT c.id, :k, :n, :st, 'tg' FROM ice_companies c WHERE c.public_code = :code
            """
        ),
        {"code": code, "k": key, "n": name, "st": status},
    )


@pytest.mark.asyncio
async def test_mine_returns_own_and_answered(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    me, other = 42_001, 42_002
    sid = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=1))
    # я организатор
    code1 = await _company(db_session, event_session_id=sid, organizer=tg_participant_key(me))
    await _respond(db_session, code1, tg_participant_key(other), "Аня", "going")
    # чужая, где я «maybe»
    sid2 = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=2))
    code2 = await _company(db_session, event_session_id=sid2, organizer=tg_participant_key(other))
    await _respond(db_session, code2, tg_participant_key(me), "Я", "maybe")
    # чужая, где я «cant» — не моя
    sid3 = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=3))
    code3 = await _company(db_session, event_session_id=sid3, organizer=tg_participant_key(other))
    await _respond(db_session, code3, tg_participant_key(me), "Я", "cant")
    # чужая вообще — приватность
    sid4 = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=4))
    await _company(db_session, event_session_id=sid4, organizer=tg_participant_key(other))

    got = await my_open_companies(db_session, me, _NOW, settings=Settings())
    codes = {c["code"] for c in got}
    assert codes == {code1, code2}
    own = next(c for c in got if c["code"] == code1)
    assert own["my_status"] == "organizer"
    assert own["going_count"] == 2
    assert own["going_names"] == ["Аня"]  # себя из имён убираем, в счёт идём
    assert own["session_id"] == sid
    assert own["arena_id"] == place["arena_id"]
    assert own["day_label"] == "завтра"
    assert own["page_url"].endswith(f"/k/{own['code']}")
    assert own["crowd_line"]
    assert set(own["photo"]) == {"thumb", "card"}
    mine2 = next(c for c in got if c["code"] == code2)
    assert mine2["my_status"] == "maybe"


@pytest.mark.asyncio
async def test_mine_excludes_cancelled_expired_far(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    me = 42_010
    # далеко за горизонтом
    sid_far = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=30))
    await _company(db_session, event_session_id=sid_far, organizer=tg_participant_key(me))
    # прошедший (ends_at < now)
    sid_past = await _insert_session(
        db_session, place["arena_id"], starts_at=datetime.now(timezone.utc) - timedelta(hours=3)
    )
    await _company(db_session, event_session_id=sid_past, organizer=tg_participant_key(me))
    # отменённый сеанс
    sid_cx = await _insert_session(
        db_session, place["arena_id"], starts_at=_at(days=1), status="cancelled"
    )
    code_cx = await _company(db_session, event_session_id=sid_cx, organizer=tg_participant_key(me))
    # lifecycle переносит отмену сеанса в событие
    await db_session.execute(
        text("UPDATE ice_company_events SET cancelled = true WHERE source_ref = :src"),
        {"src": f"ice_session:{sid_cx}"},
    )

    got = await my_open_companies(db_session, me, _NOW, settings=Settings())
    assert got == []


@pytest.mark.asyncio
async def test_mine_empty_for_stranger(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    sid = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=1))
    await _company(db_session, event_session_id=sid, organizer=tg_participant_key(99_001))
    assert await my_open_companies(db_session, 42_999, _NOW, settings=Settings()) == []
