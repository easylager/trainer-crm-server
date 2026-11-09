"""Рекламный вход в «Кто кого»: метка первого хода, заходы без ключа игрока, срез по меткам."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.hockey_game import make_pick
from src.application.hockey_promo import clean_src
from tests.api.test_admin_hockey import patch_admin_principal
from tests.api.test_webapp_client_hockey import _insert_match, patch_client_principal

A = 880_312_001
B = 880_312_002
C = 880_312_003


def test_clean_src_accepts_only_valid_labels() -> None:
    assert clean_src("push1") == "push1"
    assert clean_src(" Push1 ") == "push1"
    assert clean_src("ab") == "ab"
    for bad in (None, "", "a", "a" * 17, "a-b", "a b", "пуш", "x;drop"):
        assert clean_src(bad) is None


async def _src_of(db_session, key: int) -> str | None:
    return (
        await db_session.execute(text("SELECT first_src FROM hockey_players WHERE player_key = :k"), {"k": key})
    ).scalar_one()


@pytest.mark.asyncio
async def test_make_pick_writes_first_src_once_and_ignores_garbage(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    m1 = await _insert_match(db_session, starts_at=now + timedelta(days=1))
    m2 = await _insert_match(db_session, starts_at=now + timedelta(days=2))
    common = {"display_name": "x", "side": "home", "now": now}

    await make_pick(db_session, player_key=A, match_id=m1, src="Push1", **common)
    assert await _src_of(db_session, A) == "push1"
    # Существующему игроку метку не перезаписываем — ни другой, ни повторной.
    await make_pick(db_session, player_key=A, match_id=m2, src="insta", **common)
    assert await _src_of(db_session, A) == "push1"
    # Мусорная метка игнорируется, ход при этом записан.
    await make_pick(db_session, player_key=B, match_id=m1, src="a-b!", **common)
    assert await _src_of(db_session, B) is None
    # Игрок без метки метку позже не получает.
    await make_pick(db_session, player_key=B, match_id=m2, src="insta", **common)
    assert await _src_of(db_session, B) is None


@pytest.mark.asyncio
async def test_put_pick_body_src_reaches_new_player(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    m1 = await _insert_match(db_session, starts_at=now + timedelta(days=1))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(A):
            ok = await client.put(f"/api/webapp/client/hockey/matches/{m1}/pick", json={"side": "away", "src": "push1"})
            assert ok.status_code == 200, ok.text
        with patch_client_principal(B):
            # Некорректная метка — не 422: ход важнее метки.
            bad = await client.put(f"/api/webapp/client/hockey/matches/{m1}/pick", json={"side": "away", "src": "<b>"})
            assert bad.status_code == 200, bad.text
    assert await _src_of(db_session, A) == "push1"
    assert await _src_of(db_session, B) is None


@pytest.mark.asyncio
async def test_entry_event_counts_label_without_player_key(app_use_test_db, db_session) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(A):
            ok = await client.post("/api/webapp/client/hockey/entry", json={"src": "Push1"})
            assert ok.status_code == 204
            junk = await client.post("/api/webapp/client/hockey/entry", json={"src": "a b"})
            assert junk.status_code == 204
    rows = (await db_session.execute(text("SELECT src FROM hockey_entry_events"))).scalars().all()
    assert rows == ["push1"]
    # В таблице нет ничего, что вело бы к человеку.
    cols = (
        (
            await db_session.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'hockey_entry_events'")
            )
        )
        .scalars()
        .all()
    )
    assert set(cols) == {"id", "src", "created_at"}


@pytest.mark.asyncio
async def test_admin_promo_report_per_label(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    m1 = await _insert_match(db_session, starts_at=now + timedelta(days=1))
    m2 = await _insert_match(db_session, starts_at=now + timedelta(days=2))
    for _ in range(5):
        await db_session.execute(text("INSERT INTO hockey_entry_events (src) VALUES ('push1')"))
    await db_session.execute(text("INSERT INTO hockey_entry_events (src) VALUES ('insta')"))
    common = {"display_name": "x", "side": "home", "now": now}
    await make_pick(db_session, player_key=A, match_id=m1, src="push1", **common)
    await make_pick(db_session, player_key=A, match_id=m2, src="push1", **common)
    await make_pick(db_session, player_key=B, match_id=m1, src="push1", **common)
    # C пришёл по метке, но ходов не сделал.
    await db_session.execute(
        text("INSERT INTO hockey_players (player_key, display_name, first_src) VALUES (:k, 'c', 'push1')"),
        {"k": C},
    )
    # A вернулся на следующий день: второй ход создан днём позже.
    await db_session.execute(
        text(
            "UPDATE hockey_picks SET created_at = created_at + interval '1 day' WHERE match_id = :m AND player_key = :k"
        ),
        {"m": m2, "k": A},
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/webapp/admin/hockey/promo")).status_code in (401, 403)
        with patch_admin_principal():
            resp = await client.get("/api/webapp/admin/hockey/promo")
            assert resp.status_code == 200, resp.text
    items = {row["src"]: row for row in resp.json()["items"]}
    assert items["push1"] == {"src": "push1", "entries": 5, "new_players": 3, "picked": 2, "returned": 1}
    assert items["insta"] == {"src": "insta", "entries": 1, "new_players": 0, "picked": 0, "returned": 0}


@pytest.mark.asyncio
async def test_platform_stats_carry_promo_rows_for_the_stats_page(app_use_test_db, db_session) -> None:
    from src.application.stats_use_cases import get_platform_stats

    await db_session.execute(text("INSERT INTO hockey_entry_events (src) VALUES ('statsx')"))
    data = await get_platform_stats(db_session)
    row = next(r for r in data["kk_promo"] if r["src"] == "statsx")
    assert row == {"src": "statsx", "entries": 1, "new_players": 0, "picked": 0, "returned": 0}
