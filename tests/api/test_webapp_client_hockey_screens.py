"""TASK-334 S5: данные экранов — клубы, один матч, «куда сдвинулась», карточка болельщика, лига по месяцу."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.hockey_game import make_pick, score_finished_matches
from src.application.hockey_matches import set_manual_result
from src.application.hockey_screens import favorite_club, rank_without, streaks
from src.application.hockey_slices import Row
from tests.api.test_webapp_client_hockey import patch_client_principal

ME, B, C = 880_335_001, 880_335_002, 880_335_003
API = "/api/webapp/client/hockey"


async def _match(db, starts_at, *, home="Юность", away="Неман", status="scheduled") -> int:
    return int(
        (
            await db.execute(
                text("""
                    INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at, status)
                    VALUES ('hockeyby', 'extraliga', :mid, :h, :a, :t, :st) RETURNING id
                    """),
                {"mid": uuid.uuid4().hex, "h": home, "a": away, "t": starts_at, "st": status},
            )
        ).scalar_one()
    )


async def _play(db, starts_at, picks: dict[int, tuple[int, int] | None], result=(3, 1), **kw) -> int:
    match = await _match(db, starts_at, **kw)
    for who, score in picks.items():
        await make_pick(
            db,
            player_key=who,
            display_name=f"И{who % 10}",
            match_id=match,
            home_score=None if score is None else score[0],
            away_score=None if score is None else score[1],
            side="home" if score is None else None,
            now=starts_at - timedelta(days=1),
        )
    await set_manual_result(
        db,
        match,
        home_score=result[0],
        away_score=result[1],
        decided_in="regulation",
        now=starts_at + timedelta(hours=3),
    )
    await score_finished_matches(db, now=starts_at + timedelta(hours=3))
    return match


def _row(rank, key, points, exact, played) -> Row:
    return Row(rank=rank, player_key=key, display_name=str(key), points=points, exact=exact, played=played, correct=0)


def test_rank_without_drops_the_match_and_keeps_ties_together() -> None:
    rows = [_row(1, 1, 70, 1, 2), _row(2, 2, 50, 1, 1), _row(3, 3, 20, 0, 2)]
    # Матч принёс 1-му 50 (точный), 2-му 50 (точный), 3-му 0: без него 1-й — 20, 2-й выпал, 3-й — 20.
    ranks = rank_without(rows, {1: (50, 1), 2: (50, 1), 3: (0, 0)})
    assert ranks == {1: 1, 3: 1}


def test_streaks_and_favorite_club() -> None:
    assert streaks([0, 20, 30, 50, 10, 20]) == (1, 3)
    assert streaks([]) == (0, 0)

    class R:
        def __init__(self, h, a):
            self.home_team, self.away_team = h, a

    assert favorite_club([R("Юность", "Неман"), R("Юность", "Лида"), R("Брест", "Неман")]) == "Неман"
    assert favorite_club([]) is None


@pytest.mark.asyncio
async def test_clubs_one_match_movement_and_profile(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=2)
    prev = await _play(db_session, start - timedelta(days=1), {ME: (1, 0), B: (3, 1), C: (2, 0)}, result=(3, 1))
    last = await _play(db_session, start, {ME: (3, 1), B: (0, 2), C: (2, 1)}, result=(3, 1))
    cancelled = await _match(db_session, now + timedelta(days=1), status="cancelled")
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            clubs = (await client.get(f"{API}/clubs")).json()["items"]
            names = [c["name"] for c in clubs]
            assert names[0] == "Динамо-Минск" and "Юность" in names and "Шахтер" in names
            assert clubs[0]["league"] == "khl" and clubs[1]["league"] == "extraliga"

            one = await client.get(f"{API}/matches/{last}")
            assert one.status_code == 200 and one.json()["result"]["home_score"] == 3
            assert one.json()["my_pick"]["points"] == 50 and "arena" in one.json()
            # Отменённый матч в списке не виден, но по ссылке открывается.
            gone = (await client.get(f"{API}/matches/{cancelled}")).json()
            assert gone["status"] == "cancelled"
            assert (await client.get(f"{API}/matches/99999999")).status_code == 404

            move = (await client.get(f"{API}/matches/{last}/movement")).json()
            assert move["points"] == 50 and move["items"], move
            for item in move["items"]:
                assert item["rank_after"] <= item["rank_before"] or item["rank_before"] is None
            # У этого игрока на втором матче 50 очков и первое место во всех срезах.
            assert all(x["rank_after"] == 1 for x in move["items"] if x["kind"] == "slice")
            assert (await client.get(f"{API}/matches/99999999/movement")).status_code == 404
            first_only = (await client.get(f"{API}/matches/{prev}/movement")).json()
            assert first_only["items"] is not None

            prof = (await client.get(f"{API}/profile")).json()
            assert prof["played"] == 2 and prof["streak"] == 2 and prof["best_streak"] == 2
            assert prof["overall"]["rank"] == 1 and prof["club"]["name"] in ("Юность", "Неман")
            assert prof["crowns"] == [] and prof["duels"] == []
        with patch_client_principal(B):
            move_b = (await client.get(f"{API}/matches/{last}/movement")).json()
            assert move_b["points"] < 50


@pytest.mark.asyncio
async def test_league_table_by_month(app_use_test_db, db_session) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            made = await client.post(f"{API}/leagues", json={"name": "Месяц", "display_name": "Я"})
            league_id = made.json()["id"]
            whole = (await client.get(f"{API}/leagues/{league_id}")).json()
            assert whole["period"] is None
            month = (await client.get(f"{API}/leagues/{league_id}", params={"period": "month"})).json()
            assert month["period"]["key"] and len(month["items"]) == 1
            bad = await client.get(f"{API}/leagues/{league_id}", params={"period": "когда-нибудь"})
            assert bad.status_code == 400


@pytest.mark.asyncio
async def test_moved_match_is_marked_until_played(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    old, new = now + timedelta(days=2), now + timedelta(days=5)
    match = await _match(db_session, new)
    plain = await _match(db_session, new, home="Гомель", away="Витебск")
    await db_session.execute(
        text("UPDATE hockey_matches SET previous_starts_at = :p WHERE id = :id"), {"p": old, "id": match}
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            one = (await client.get(f"{API}/matches/{match}")).json()
            assert datetime.fromisoformat(one["moved_from"]) == old and one["open"] is True
            assert (await client.get(f"{API}/matches/{plain}")).json()["moved_from"] is None
            # Список хаба строится из тех же строк: колонка previous_starts_at в них есть.
            from src.application.hockey_game import player_matches

            rows = {r["id"]: r for r in await player_matches(db_session, ME, since=now - timedelta(days=1))}
            assert not rows or rows[match]["previous_starts_at"] is not None
            # Не состоится или сыгран: пометка уходит.
            await db_session.execute(text("UPDATE hockey_matches SET status = 'cancelled' WHERE id = :id"), {"id": match})
            await db_session.commit()
            assert (await client.get(f"{API}/matches/{match}")).json()["moved_from"] is None
