"""Ручной ввод итога матча Динамо в админке."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.deps import get_admin_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.hockey_matches import upsert_calendar_match
from tests.application.test_hockey_matches import _match, _minsk


@contextmanager
def patch_admin_principal(user_id: int = 4242) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)
    app.dependency_overrides[get_admin_miniapp_principal] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_admin_miniapp_principal, None)


async def _seed(db_session) -> tuple[int, int]:
    now = _minsk(2026, 10, 19, 12, 0)
    await upsert_calendar_match(db_session, _match("final", "1218869"), now=now)
    await upsert_calendar_match(db_session, _match("upcoming", "1218873"), now=now)
    played = (
        await db_session.execute(text("SELECT id FROM hockey_matches WHERE source_match_id = '1218869'"))
    ).scalar_one()
    upcoming = (
        await db_session.execute(text("SELECT id FROM hockey_matches WHERE source_match_id = '1218873'"))
    ).scalar_one()
    await db_session.execute(
        text("UPDATE hockey_matches SET status = 'review', review_reason = 'счёт не совпал' WHERE id = :id"),
        {"id": played},
    )
    await db_session.flush()
    return int(played), int(upcoming)


@pytest.mark.asyncio
async def test_admin_hockey_list_review_manual_and_errors(app_use_test_db, db_session) -> None:
    played, upcoming = await _seed(db_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.get("/api/webapp/admin/hockey/matches")
        assert denied.status_code in (401, 403)

        with patch_admin_principal():
            listed = await client.get("/api/webapp/admin/hockey/matches")
            assert listed.status_code == 200, listed.text
            items = listed.json()["items"]
            assert [item["id"] for item in items] == [upcoming, played]
            assert items[0]["starts_at"].startswith("2026-10-22T")
            assert items[0]["home_team"] == "ХК Сочи"
            assert items[1]["status"] == "review"
            assert items[1]["review_reason"] == "счёт не совпал"

            review = await client.get("/api/webapp/admin/hockey/matches", params={"status": "review"})
            assert review.status_code == 200, review.text
            assert [item["id"] for item in review.json()["items"]] == [played]

            closed = await client.post(
                f"/api/webapp/admin/hockey/matches/{played}/result",
                json={"home_score": 1, "away_score": 4, "decided_in": "regulation"},
            )
            assert closed.status_code == 200, closed.text
            body = closed.json()
            assert (body["status"], body["home_score"], body["away_score"], body["result_source"]) == (
                "final",
                1,
                4,
                "manual",
            )
            assert body["review_reason"] is None

            row = (
                await db_session.execute(
                    text("SELECT status, result_source, home_score, away_score FROM hockey_matches WHERE id = :id"),
                    {"id": played},
                )
            ).one()
            assert tuple(row) == ("final", "manual", 1, 4)

            tie = await client.post(
                f"/api/webapp/admin/hockey/matches/{upcoming}/result",
                json={"home_score": 2, "away_score": 2, "decided_in": "regulation"},
            )
            assert tie.status_code == 400, tie.text
            assert "ничь" in tie.json()["detail"]

            missing = await client.post(
                "/api/webapp/admin/hockey/matches/987654/result",
                json={"home_score": 2, "away_score": 1, "decided_in": "regulation"},
            )
            assert missing.status_code == 404, missing.text
            assert missing.json()["detail"] == "Матч не найден"
