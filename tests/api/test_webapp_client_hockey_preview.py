"""«Перед матчем» в игре «Кто кого»: место, последние пять, личные встречи — только то, что есть."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.hockey_matches import DINAMO, set_manual_result
from tests.api.test_webapp_client_hockey import patch_client_principal
from tests.api.test_webapp_client_hockey_screens import _match

ME = 880_336_001
API = "/api/webapp/client/hockey"
T0 = datetime(2026, 12, 20, 16, 0, tzinfo=timezone.utc)


async def _final(db, days_ago: int, home: str, away: str, score: tuple[int, int], **kw) -> int:
    at = T0 - timedelta(days=days_ago)
    mid = await _match(db, at, home=home, away=away, **kw)
    await set_manual_result(
        db, mid, home_score=score[0], away_score=score[1], decided_in="regulation", now=at + timedelta(hours=3)
    )
    return mid


async def _get(match_id: int) -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            r = await client.get(f"{API}/matches/{match_id}/preview")
    assert r.status_code == 200
    return r.json()


async def test_preview_all_parts(app_use_test_db, db_session) -> None:
    home, away = "ПвЮность", "ПвНеман"
    await db_session.execute(text("DELETE FROM hockey_standings WHERE team IN (:a, :b)"), {"a": home, "b": away})
    await db_session.execute(
        text("""INSERT INTO hockey_standings (league, team, place, games, points)
                VALUES ('extraliga', :a, 3, 20, 30), ('extraliga', :b, 7, 20, 22)"""),
        {"a": home, "b": away},
    )
    for i in range(6):
        await _final(db_session, 30 - i, home, f"ПвДругой{i}", (2, 1) if i % 2 else (0, 4))
    for i, s in enumerate(((3, 2), (1, 5), (4, 0), (2, 1))):
        await _final(db_session, 10 - i, home if i % 2 == 0 else away, away if i % 2 == 0 else home, s)
    mid = await _match(db_session, T0, home=home, away=away)
    await db_session.commit()

    p = await _get(mid)
    assert p["home"]["place"] == 3 and p["away"]["place"] == 7
    assert len(p["home"]["form"]) == 5
    # Старые слева, свежий справа: последний — встреча 2:1, где «Неман» был дома и выиграл.
    last = p["home"]["form"][-1]
    assert (last["win"], last["mark"], last["opponent"], last["home"]) == (False, "П", away, False)
    assert len(p["away"]["form"]) == 4
    assert [(m["home_score"], m["away_score"]) for m in p["meetings"]] == [(2, 1), (4, 0), (1, 5)]


async def test_preview_partial_and_khl_opponent_has_no_form(app_use_test_db, db_session) -> None:
    rival = "ПвСКА"
    await db_session.execute(text("DELETE FROM hockey_standings WHERE league = 'khl' AND team = :t"), {"t": rival})
    await db_session.execute(
        text("INSERT INTO hockey_standings (league, team, place, games, points) VALUES ('khl', :t, 2, 30, 40)"),
        {"t": rival},
    )
    kw = {"source": "hcdinamo", "league": "khl"}
    await _final(db_session, 5, DINAMO, rival, (1, 3), **kw)
    mid = await _match(db_session, T0, home=rival, away=DINAMO, **kw)
    await db_session.commit()

    p = await _get(mid)
    # У соперника Динамо только место: его «форма» была бы одними матчами с Динамо.
    assert p["home"] == {"place": 2}
    assert [f["win"] for f in p["away"]["form"]][-1] is False
    assert len(p["meetings"]) == 1


async def test_preview_nothing_known_is_empty(app_use_test_db, db_session) -> None:
    mid = await _match(db_session, T0, home="ПвНикто1", away="ПвНикто2")
    await db_session.commit()
    assert await _get(mid) == {}
    assert await _get(999_999_999) == {}
