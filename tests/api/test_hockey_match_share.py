"""TASK-304 (доделка): матч в общем движке шаринга — «Погнали?», «Компания», «Открытка»."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from sqlalchemy import text

from src.api.routes.public_ice_company import reset_company_rate_limits
from tests.api.test_hockey_event import _client, _companies, _env, _match, arena  # noqa: F401
from tests.api.test_ice_company_api import _init
from tests.api.test_ice_invites import _headers

START = datetime(2026, 12, 2, 16, 30, tzinfo=timezone.utc)  # ср, 2 декабря, 19:30 по Минску
SHARE = "/api/public/hockey/matches/{}/share"
_SHARE_KEYS = {
    "share_url",
    "share_body",
    "share_text",
    "invite_share_url",
    "invite_share_body",
    "invite_share_text",
    "place_share_url",
    "place_share_body",
    "place_share_text",
    "og_image_url",
    "story_image_url",
    "share_context",
    "match_id",
}


@pytest.fixture(autouse=True)
def _limits() -> None:
    reset_company_rate_limits()


async def _share_events(db_session, match_id: int) -> list[dict]:
    rows = (
        await db_session.execute(
            text("""
                SELECT kind, share_context, arena_id, payload FROM client_share_events
                WHERE payload->>'match_id' = :m ORDER BY id
                """),
            {"m": str(match_id)},
        )
    ).mappings()
    return [dict(row) for row in rows]


# ---------- /share ----------


@pytest.mark.asyncio
async def test_share_has_every_key_the_sheet_reads_and_both_tones(app_use_test_db, db_session, arena) -> None:
    match_id = await _match(db_session, starts_at=START)
    await db_session.commit()
    async with _client() as client:
        plain = (await client.get(SHARE.format(match_id), params={"record": "false"})).json()
        invited = (await client.get(SHARE.format(match_id), params={"record": "false", "invite": "true"})).json()
    assert _SHARE_KEYS <= set(plain) and _SHARE_KEYS <= set(invited)
    link = f"https://t.me/glide_test_bot?startapp=kkm_{match_id}"
    page = f"https://glide.test/kk/m/{match_id}"
    # В чат — только ссылка на страницу с открыткой. Текст не клеим: он уже на картинке.
    assert plain["share_url"] == plain["share_text"] == page
    assert invited["share_url"] == invited["share_text"] == f"{page}?i=1"
    assert plain["share_body"] == invited["share_body"] == ""
    assert plain["place_share_body"] == invited["invite_share_body"] == ""
    assert "Погнали" not in plain["share_text"] and "Погнали" not in invited["share_body"]
    assert plain["share_body"] == plain["place_share_body"]
    assert invited["share_body"] == invited["invite_share_body"]
    assert plain["app_url"] == invited["app_url"] == link
    assert plain["match_id"] == match_id and plain["share_context"] == "match_page"
    for body in (plain, invited):
        assert (
            body["og_image_url"].startswith(f"https://glide.test/kk/m/{match_id}/") and ".png" in body["og_image_url"]
        )
        assert body["story_image_url"].endswith(".story.png") or ".story.png?" in body["story_image_url"]
    assert invited["og_image_url"].endswith("?i=1") and not plain["og_image_url"].endswith("?i=1")


@pytest.mark.asyncio
async def test_share_record_writes_event_with_channel_and_preview_does_not(app_use_test_db, db_session, arena) -> None:
    match_id = await _match(db_session, starts_at=START)
    await db_session.commit()
    async with _client() as client:
        await client.get(SHARE.format(match_id), params={"record": "false"})
        assert await _share_events(db_session, match_id) == []
        ok = await client.get(
            SHARE.format(match_id),
            params={"invite": "true", "channel": "telegram", "share_context": "match_page"},
        )
        await client.get(SHARE.format(match_id), params={"channel": "мусор"})
    assert ok.status_code == 200
    events = await _share_events(db_session, match_id)
    assert len(events) == 2
    assert events[0]["kind"] == "place" and events[0]["share_context"] == "match_page"
    assert events[0]["arena_id"] == arena["arena_id"]
    assert events[0]["payload"] == {
        "surface": "hockey_match",
        "match_id": match_id,
        "invite": True,
        "channel": "telegram",
    }
    assert events[1]["payload"]["channel"] is None and events[1]["payload"]["invite"] is False


@pytest.mark.asyncio
async def test_share_404_for_away_unknown_and_flag_off(app_use_test_db, db_session, arena, monkeypatch) -> None:
    home = await _match(db_session, starts_at=START)
    away = await _match(db_session, starts_at=START, home="СКА", away="Динамо-Минск")
    await db_session.commit()
    async with _client() as client:
        assert (await client.get(SHARE.format(home))).status_code == 200
        assert (await client.get(SHARE.format(away))).status_code == 404
        assert (await client.get(SHARE.format(999_999_999))).status_code == 404
        monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "0")
        assert (await client.get(SHARE.format(home))).status_code == 404
    assert len(await _share_events(db_session, away)) == 0


@pytest.mark.asyncio
async def test_share_without_bot_falls_back_to_the_miniapp_page(
    app_use_test_db, db_session, arena, monkeypatch
) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "")
    match_id = await _match(db_session, starts_at=START)
    await db_session.commit()
    async with _client() as client:
        body = (await client.get(SHARE.format(match_id), params={"record": "false"})).json()
    assert body["share_url"] == f"https://glide.test/kk/m/{match_id}"
    assert body["app_url"] == f"https://glide.test/webapp/client-match?id={match_id}"
    assert body["share_body"] == ""


@pytest.mark.asyncio
async def test_match_share_page_previews_the_card_and_opens_the_app(
    app_use_test_db, db_session, arena
) -> None:
    match_id = await _match(db_session, starts_at=START)
    await db_session.commit()
    async with _client() as client:
        page = await client.get(f"/kk/m/{match_id}", params={"i": 1})
        bot = await client.get(f"/kk/m/{match_id}", headers={"User-Agent": "TelegramBot (like TwitterBot)"})
        missing = await client.get("/kk/m/999999999")
    assert page.status_code == 200
    assert "og:image" in page.text and f"/kk/m/{match_id}/" in page.text and ".png" in page.text
    assert "Погнали?" in page.text
    assert f"startapp=kkm_{match_id}" in page.text
    assert 'http-equiv="refresh"' in page.text
    assert bot.status_code == 200
    assert "og:image" in bot.text and "http-equiv" not in bot.text and "location.replace" not in bot.text
    assert missing.status_code == 404


# ---------- открытка-превью ----------


@pytest.mark.asyncio
async def test_match_card_png_is_public_and_sized(app_use_test_db, db_session, arena) -> None:
    match_id = await _match(db_session, starts_at=START, away="Шанхайские Драконы")
    away = await _match(db_session, starts_at=START, home="СКА", away="Динамо-Минск")
    await db_session.commit()
    async with _client() as client:
        share = (await client.get(SHARE.format(match_id), params={"record": "false", "invite": "true"})).json()
        og_path = share["og_image_url"].removeprefix("https://glide.test")
        story_path = share["story_image_url"].removeprefix("https://glide.test")
        og = await client.get(og_path)
        story = await client.get(story_path)
        plain = await client.get(f"/kk/m/{match_id}/x.png")
        foreign = await client.get(f"/kk/m/{away}/x.png")
    assert og.status_code == story.status_code == plain.status_code == 200
    assert og.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(og.content)).size == (1200, 630)
    assert Image.open(io.BytesIO(story.content)).size == (1080, 1920)
    assert og.content != plain.content, "тон «Погнали?» рисуется иначе, чем «Идём на матч?»"
    assert foreign.status_code == 404


# ---------- компания ----------


async def _post_company(client, user_id: int, **body):
    return await client.post(
        "/api/public/ice-companies",
        headers=_headers(**{"X-Telegram-Init-Data": _init(user_id)}),
        json={"display_name": "Макс", **body},
    )


@pytest.mark.asyncio
async def test_company_for_a_match_by_public_path(app_use_test_db, db_session, arena) -> None:
    match_id = await _match(db_session)
    await db_session.commit()
    async with _client() as client:
        first = await _post_company(client, 880_304_501, match_id=match_id)
        again = await _post_company(client, 880_304_501, match_id=match_id)
    assert first.status_code == 201, first.text
    view = first.json()
    assert again.json()["public_code"] == view["public_code"], "одна компания на организатора и матч"
    assert view["event"]["kind"] == "hockey_match" and view["name"] == "Динамо-Минск — СКА"
    assert view["card_text"].startswith("Идём на матч?")
    assert view["page_url"] == f"https://t.me/glide_test_bot?startapp=kkm_{match_id}_{view['public_code']}"
    assert "/k/" not in view["page_url"]
    assert await _companies(db_session, match_id) == 1


@pytest.mark.asyncio
async def test_company_name_lands_on_the_match_card(app_use_test_db, db_session, arena) -> None:
    match_id = await _match(db_session)
    await db_session.commit()
    async with _client() as client:
        res = await _post_company(client, 880_304_511, match_id=match_id, name="Офис на Динамо")
    assert res.status_code == 201, res.text
    view = res.json()
    assert view["name"] == "Офис на Динамо"
    assert "Офис на Динамо" in view["card_text"]
    assert view["card_text"].startswith("Идём на матч?")
    async with _client() as client:
        again = await _post_company(client, 880_304_511, match_id=match_id, name="Сектор Б")
        kept = await _post_company(client, 880_304_511, match_id=match_id)
    assert again.status_code == 201 and again.json()["public_code"] == view["public_code"]
    assert again.json()["name"] == "Сектор Б"
    assert kept.json()["name"] == "Сектор Б"


@pytest.mark.asyncio
async def test_company_needs_exactly_one_of_session_and_match(app_use_test_db, db_session, arena) -> None:
    match_id = await _match(db_session)
    await db_session.commit()
    async with _client() as client:
        both = await _post_company(client, 880_304_502, match_id=match_id, session_id=1)
        none = await _post_company(client, 880_304_502)
    assert both.status_code == 422 and none.status_code == 422
    assert await _companies(db_session, match_id) == 0


@pytest.mark.asyncio
async def test_company_for_away_started_or_flag_off_match(app_use_test_db, db_session, arena, monkeypatch) -> None:
    home = await _match(db_session)
    away = await _match(db_session, home="СКА", away="Динамо-Минск")
    started = await _match(db_session, starts_at=datetime.now(timezone.utc) - timedelta(hours=1))
    await db_session.commit()
    async with _client() as client:
        assert (await _post_company(client, 880_304_503, match_id=away)).status_code == 404
        assert (await _post_company(client, 880_304_503, match_id=started)).status_code == 409
        monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "0")
        assert (await _post_company(client, 880_304_503, match_id=home)).status_code == 404
    assert await _companies(db_session, home) == 0


@pytest.mark.asyncio
async def test_match_company_telegram_prepare_and_cancel(app_use_test_db, db_session, arena, monkeypatch) -> None:
    from src.api.routes import public_ice_company as routes

    sent: list[dict] = []

    async def fake(token, user_id, code, text_, buttons, photo=None, title=""):
        sent.append({"code": code, "text": text_, "photo": photo, "title": title, "buttons": buttons})
        return "PM-7"

    monkeypatch.setattr(routes, "_save_prepared", fake)
    match_id = await _match(db_session)
    await db_session.commit()
    organizer = 880_304_504
    async with _client() as client:
        code = (await _post_company(client, organizer, match_id=match_id)).json()["public_code"]
        init = {"X-Telegram-Init-Data": _init(organizer)}
        prepared = await client.post(f"/api/public/ice-companies/{code}/telegram-prepare", headers=_headers(**init))
        stranger = await client.post(
            f"/api/public/ice-companies/{code}/cancel", headers=_headers(**{"X-Telegram-Init-Data": _init(1)})
        )
        cancelled = await client.post(f"/api/public/ice-companies/{code}/cancel", headers=_headers(**init))
    assert prepared.status_code == 200 and prepared.json()["prepared_message_id"] == "PM-7"
    assert sent[0]["title"] == "Звать на матч" and sent[0]["photo"] is None
    assert sent[0]["text"].startswith("Идём на матч?")
    assert any(f"kkm_{match_id}_{code}" in str(b.get("url")) for b in sent[0]["buttons"])
    assert stranger.status_code in (403, 404)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
