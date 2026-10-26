"""TASK-300: «Кто кого» в чат — готовое сообщение, картинки карточек и воронка."""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.deps import get_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.api.routes import webapp_client_hockey_share as share_routes
from src.application.hockey_game import score_finished_matches
from src.application.hockey_matches import set_manual_result

ME = 880_300_001
FRIEND = 880_300_002
STRANGER = 880_300_003


@contextmanager
def patch_client_principal(user_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)
    app.dependency_overrides[get_client_miniapp_principal] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_client_miniapp_principal, None)


@pytest.fixture
def prepared(monkeypatch) -> list[dict]:
    """Вместо Telegram: запоминаем, что ушло бы в savePreparedInlineMessage."""
    calls: list[dict] = []

    async def fake(token, user_id, result_id, photo, caption, button):
        calls.append({"user_id": user_id, "result_id": result_id, "photo": photo, "caption": caption, "button": button})
        return "PM-1"

    monkeypatch.setattr(share_routes, "_prepare", fake)
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.test")
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "1")
    monkeypatch.delenv("CLIENT_MINI_APP_SHORT_NAME", raising=False)
    return calls


async def _insert_match(db_session, *, starts_at: datetime, away: str = "ХК Сочи") -> int:
    return int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at, status)
                    VALUES ('hcdinamo', :mid, 'Динамо-Минск', :away, :starts_at, 'scheduled')
                    RETURNING id
                    """),
                {"mid": uuid.uuid4().hex, "away": away, "starts_at": starts_at},
            )
        ).scalar_one()
    )


async def _events(db_session, kind: str, card: str) -> int:
    return int(
        (
            await db_session.execute(
                text("SELECT COUNT(*) FROM hockey_card_events WHERE kind = :k AND card = :c"), {"k": kind, "c": card}
            )
        ).scalar_one()
    )


def _path(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


@pytest.mark.asyncio
async def test_result_card_share_signed_image_and_miss(app_use_test_db, db_session, prepared) -> None:
    now = datetime.now(timezone.utc)
    match_id = await _insert_match(db_session, starts_at=now + timedelta(hours=1))
    await db_session.commit()
    before = await _events(db_session, "shared", "result")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            r = await client.put(
                f"/api/webapp/client/hockey/matches/{match_id}/pick", json={"home_score": 3, "away_score": 2}
            )
            assert r.status_code == 200, r.text
        with patch_client_principal(FRIEND):
            r = await client.put(f"/api/webapp/client/hockey/matches/{match_id}/pick", json={"side": "away"})
            assert r.status_code == 200, r.text
        with patch_client_principal(ME):
            early = await client.post("/api/webapp/client/hockey/share", json={"card": "result", "match_id": match_id})
            assert early.status_code == 404, "до итога хвастаться нечем"

        await set_manual_result(db_session, match_id, home_score=3, away_score=2, decided_in="regulation", now=now)
        await score_finished_matches(db_session, now=now)
        await db_session.commit()

        with patch_client_principal(ME):
            r = await client.post("/api/webapp/client/hockey/share", json={"card": "result", "match_id": match_id})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["prepared_message_id"] == "PM-1"
        assert body["url"] == "https://t.me/glide_test_bot?startapp=kkr"
        assert body["text"] == "Кто кого: в точку! Динамо-Минск — ХК Сочи 3:2, +50"
        call = prepared[-1]
        assert call["user_id"] == ME
        assert call["button"] == {"text": "А ты угадаешь?", "url": body["url"]}
        assert call["photo"].startswith(f"https://glide.test/kk/r/{match_id}/50/")
        assert await _events(db_session, "shared", "result") == before + 1

        png = await client.get(_path(call["photo"]))
        assert png.status_code == 200
        assert png.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(png.content)).size == (1200, 630)
        forged = await client.get(f"/kk/r/{match_id}/50/0000000000000000.png")
        assert forged.status_code == 404

        with patch_client_principal(FRIEND):
            miss = await client.post("/api/webapp/client/hockey/share", json={"card": "result", "match_id": match_id})
        assert miss.status_code == 404


@pytest.mark.asyncio
async def test_league_card_share_join_from_card_and_opened(app_use_test_db, db_session, prepared) -> None:
    now = datetime.now(timezone.utc)
    await _insert_match(db_session, starts_at=now + timedelta(days=2), away="Торпедо")
    await db_session.commit()
    joined_before = await _events(db_session, "joined", "league")
    opened_before = await _events(db_session, "opened", "league")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            created = await client.post(
                "/api/webapp/client/hockey/leagues", json={"name": "Хоккейные пенсионеры Уручья"}
            )
            assert created.status_code == 200, created.text
            league = created.json()
            r = await client.post("/api/webapp/client/hockey/share", json={"card": "league", "league_id": league["id"]})
        assert r.status_code == 200, r.text
        body = r.json()
        code = league["invite_url"].split("kk_", 1)[1]
        assert body["url"] == f"https://t.me/glide_test_bot?startapp=kkl_{code}"
        call = prepared[-1]
        assert call["button"]["text"] == "Вступить и угадать"
        assert call["photo"].startswith(f"https://glide.test/kk/l/{code}.png?v=")

        png = await client.get(_path(call["photo"]))
        assert png.status_code == 200
        assert Image.open(io.BytesIO(png.content)).size == (1200, 630)
        assert (await client.get("/kk/l/ZZZZZZZZ.png")).status_code == 404

        with patch_client_principal(STRANGER):
            denied = await client.post(
                "/api/webapp/client/hockey/share", json={"card": "league", "league_id": league["id"]}
            )
            assert denied.status_code == 403

        with patch_client_principal(FRIEND):
            opened = await client.post("/api/webapp/client/hockey/card-opened", json={"card": "league"})
            assert opened.status_code == 204
            first = await client.post(
                "/api/webapp/client/hockey/leagues/join", json={"code": code, "from_card": "league"}
            )
            assert first.status_code == 200, first.text
            again = await client.post(
                "/api/webapp/client/hockey/leagues/join", json={"code": code, "from_card": "league"}
            )
            assert again.status_code == 200, again.text

    assert await _events(db_session, "opened", "league") == opened_before + 1
    # Повторный вход по той же карточке — не новый человек.
    assert await _events(db_session, "joined", "league") == joined_before + 1
    stored = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'hockey_card_events' AND column_name = 'player_key'"
            )
        )
    ).scalar_one()
    assert stored == 0, "в воронке нет ключей игроков"


@pytest.mark.asyncio
async def test_share_without_telegram_photo_still_returns_link(
    app_use_test_db, db_session, prepared, monkeypatch
) -> None:
    monkeypatch.setenv("WEBAPP_BASE_URL", "http://localhost:8000")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            created = await client.post("/api/webapp/client/hockey/leagues", json={"name": "Двор"})
            league = created.json()
            r = await client.post("/api/webapp/client/hockey/share", json={"card": "league", "league_id": league["id"]})
    assert r.status_code == 200, r.text
    assert prepared[-1]["photo"] is None, "без https Telegram картинку не заберёт — шлём текст"
    assert r.json()["url"].endswith("startapp=kkl_" + league["invite_url"].split("kk_", 1)[1])


@pytest.mark.asyncio
async def test_crown_card_share_and_signed_image(app_use_test_db, db_session, prepared) -> None:
    """TASK-334: корона месяца в чат — подпись чемпиона и поздравление, картинка по подписанному адресу."""
    from src.application.hockey_game import make_pick
    from src.application.hockey_leagues import create_league, join_by_code
    from src.application.hockey_races import close_due_races, ensure_month_race
    from src.ingestion.hockey_sources import MINSK_TZ

    nov = datetime(2026, 11, 10, 12, 0, tzinfo=MINSK_TZ)
    dec = datetime(2026, 12, 1, 12, 0, tzinfo=MINSK_TZ)
    league = await create_league(db_session, owner_key=ME, owner_name="Саша", name="ОХМ")
    await join_by_code(db_session, player_key=FRIEND, display_name="Катя", code=league.invite_code)
    await db_session.execute(
        text("UPDATE hockey_league_members SET joined_at = :at WHERE league_id = :l"),
        {"at": datetime(2026, 11, 1, tzinfo=MINSK_TZ), "l": league.id},
    )
    race = await ensure_month_race(db_session, now=nov)
    starts = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    match_id = await _insert_match(db_session, starts_at=starts)
    for player, score in ((ME, (3, 1)), (FRIEND, (2, 1))):
        await make_pick(
            db_session,
            player_key=player,
            display_name="x",
            match_id=match_id,
            home_score=score[0],
            away_score=score[1],
            now=starts - timedelta(hours=1),
        )
    await set_manual_result(db_session, match_id, home_score=3, away_score=1, decided_in="regulation", now=dec)
    await score_finished_matches(db_session, now=dec)
    assert await close_due_races(db_session, now=dec) == [race.id]
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            mine = await client.post("/api/webapp/client/hockey/share", json={"card": "crown", "race_id": race.id})
        assert mine.status_code == 200, mine.text
        assert mine.json()["text"].startswith("Кто кого: корона за ноябрь в «ОХМ» — моя.")
        assert mine.json()["url"] == f"https://t.me/glide_test_bot?startapp=kkl_{league.invite_code}"
        photo = prepared[-1]["photo"]
        assert photo.startswith(f"https://glide.test/kk/c/{race.id}/{league.id}/")
        png = await client.get(_path(photo))
        assert png.status_code == 200 and Image.open(io.BytesIO(png.content)).size == (1200, 630)
        assert (await client.get(f"/kk/c/{race.id}/{league.id}/0000000000000000.png")).status_code == 404

        with patch_client_principal(FRIEND):
            theirs = await client.post("/api/webapp/client/hockey/share", json={"card": "crown", "race_id": race.id})
        assert theirs.status_code == 200, theirs.text
        assert "Поздравляю" in theirs.json()["text"]
