"""Компания на лёд: API, initData, лимиты, страница, перенос сеанса."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
import io
from sqlalchemy import text

from src.api.routes.public_ice_company import reset_company_rate_limits
from src.application.ice_company.lifecycle import _edit_dirty, remember_inline_card, reset_edit_debounce, tick
from src.shared.config import Settings
from tests.api.test_ice_invites import _at, _client, _headers, _insert_session, _place
from tests.shared.test_telegram_webapp import _build_signed_init_data


class _Sender:
    def __init__(self) -> None:
        self.dms: list[tuple[int, str]] = []
        self.edits: list[str] = []

    async def dm(self, chat_id: int, text: str, buttons: list) -> int:
        self.dms.append((chat_id, text))
        return 100 + len(self.dms)

    async def edit(self, ref: dict, text: str, buttons: list) -> None:
        self.edits.append(text)


def _init(user_id: int, *, age_sec: int = 0) -> str:
    token = Settings().telegram_bot_token_client
    return _build_signed_init_data(token, user_id=user_id, auth_date=int(time.time()) - age_sec)


@pytest.fixture(autouse=True)
def _limits() -> None:
    reset_company_rate_limits()
    reset_edit_debounce()
    yield
    reset_company_rate_limits()


async def _enable(monkeypatch: pytest.MonkeyPatch, city_id: int) -> None:
    monkeypatch.setenv("ICE_COMPANY_CITY_IDS", str(city_id))


async def _create(db_session, monkeypatch, *, user_id: int = 501):
    place = await _place(db_session)
    await _enable(monkeypatch, place["city_id"])
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=3))
    async with _client() as client:
        res = await client.post(
            "/api/public/ice-companies",
            headers=_headers(**{"X-Telegram-Init-Data": _init(user_id)}),
            json={"session_id": session_id, "display_name": "Аня"},
        )
    return res, place, session_id


@pytest.mark.asyncio
async def test_create_requires_fresh_init_data_and_city_flag(app_use_test_db, db_session, monkeypatch) -> None:
    place = await _place(db_session)
    session_id = await _insert_session(db_session, place["arena_id"], starts_at=_at(days=2))
    async with _client() as client:
        off = await client.post(
            "/api/public/ice-companies",
            headers=_headers(**{"X-Telegram-Init-Data": _init(7)}),
            json={"session_id": session_id, "display_name": "Аня"},
        )
        assert off.status_code == 404
        await _enable(monkeypatch, place["city_id"])
        missing = await client.post(
            "/api/public/ice-companies",
            headers=_headers(),
            json={"session_id": session_id, "display_name": "Аня"},
        )
        assert missing.status_code == 401
        stale = await client.post(
            "/api/public/ice-companies",
            headers=_headers(**{"X-Telegram-Init-Data": _init(7, age_sec=90000)}),
            json={"session_id": session_id, "display_name": "Аня"},
        )
        assert stale.status_code == 401
        tampered = _init(7)
        bad = tampered.replace("hash=", "hash=dead", 1)
        forged = await client.post(
            "/api/public/ice-companies",
            headers=_headers(**{"X-Telegram-Init-Data": bad}),
            json={"session_id": session_id, "display_name": "Аня"},
        )
        assert forged.status_code == 401


@pytest.mark.asyncio
async def test_create_without_threshold_fields(app_use_test_db, db_session, monkeypatch) -> None:
    created, _, _ = await _create(db_session, monkeypatch)
    assert created.status_code == 201, created.text
    body = created.json()
    assert "min_people" not in body
    assert "max_people" not in body
    assert "needs_reconfirm" not in body
    assert body["status"] == "open"


@pytest.mark.asyncio
async def test_repeat_and_weekly_are_gone(app_use_test_db, db_session, monkeypatch) -> None:
    created, _, _ = await _create(db_session, monkeypatch)
    code = created.json()["public_code"]
    async with _client() as client:
        weekly = await client.post(
            f"/api/public/ice-companies/{code}/weekly",
            headers=_headers(**{"X-Telegram-Init-Data": _init(501)}),
            json={"enabled": True},
        )
        assert weekly.status_code == 404
        repeat = await client.post(
            f"/api/public/ice-companies/{code}/repeat",
            headers=_headers(**{"X-Telegram-Init-Data": _init(501)}),
            json={},
        )
        assert repeat.status_code == 404


@pytest.mark.asyncio
async def test_response_is_idempotent_and_marks_card_dirty(app_use_test_db, db_session, monkeypatch) -> None:
    created, _, _ = await _create(db_session, monkeypatch)
    assert created.status_code == 201, created.text
    code = created.json()["public_code"]
    async with _client() as client:
        first = await client.post(
            f"/api/public/ice-companies/{code}/responses",
            headers=_headers(**{"X-Telegram-Init-Data": _init(777)}),
            json={"status": "going", "display_name": "Макс", "consent": True},
        )
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "open"
        assert first.json()["going_count"] == 2
        dirty = (
            await db_session.execute(
                text("SELECT card_dirty FROM ice_companies WHERE public_code = :code"),
                {"code": code},
            )
        ).scalar_one()
        assert dirty is True
        again = await client.post(
            f"/api/public/ice-companies/{code}/responses",
            headers=_headers(**{"X-Telegram-Init-Data": _init(777)}),
            json={"status": "maybe", "display_name": "Макс", "consent": True},
        )
        assert again.status_code == 200
        assert again.json()["status"] == "open"
        assert again.json()["maybe_count"] == 1
        page = await client.get(f"/k/{code}")
        assert page.status_code == 200
        assert 'name="robots" content="noindex, nofollow"' in page.text
        png = await client.get(f"/k/{code}/og.png")
        assert png.status_code == 200
        with Image.open(io.BytesIO(png.content)) as img:
            assert img.size == (1080, 1080)
        ics = await client.get(f"/k/{code}/event.ics")
        assert "BEGIN:VEVENT" in ics.text
        honeypot = await client.post(
            f"/api/public/ice-companies/{code}/responses",
            headers=_headers(),
            json={"status": "going", "display_name": "Бот", "consent": True, "website": "http://spam"},
        )
        assert honeypot.status_code == 200
        assert honeypot.json()["going_count"] == 1


@pytest.mark.asyncio
async def test_web_needs_consent_and_rate_limit(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("ICE_COMPANY_WEB_RATE_PER_MINUTE", "3")
    created, _, _ = await _create(db_session, monkeypatch)
    code = created.json()["public_code"]
    async with _client() as client:
        denied = await client.post(
            f"/api/public/ice-companies/{code}/responses",
            headers=_headers(),
            json={"status": "going", "display_name": "Оля", "consent": False},
        )
        assert denied.status_code == 422
        ok = await client.post(
            f"/api/public/ice-companies/{code}/responses",
            headers=_headers(),
            json={"status": "going", "display_name": "Оля", "consent": True, "source": "viber"},
        )
        assert ok.status_code == 200, ok.text
        token = ok.json()["participant_token"]
        assert token
        moved = await client.post(
            f"/api/public/ice-companies/{code}/responses",
            headers=_headers(),
            json={"status": "cant", "display_name": "Оля", "consent": True, "participant_token": token, "source": "viber"},
        )
        assert moved.json()["cant_count"] == 1
        assert "participant_token" not in moved.json() or moved.json().get("participant_token") in (None, token)
        limited = await client.post(
            f"/api/public/ice-companies/{code}/responses",
            headers=_headers(),
            json={"status": "maybe", "display_name": "Оля", "consent": True, "participant_token": token},
        )
        assert limited.status_code == 429


@pytest.mark.asyncio
async def test_join_rewrites_the_shared_card_only(app_use_test_db, db_session, monkeypatch) -> None:
    created, _, _ = await _create(db_session, monkeypatch)
    assert created.status_code == 201, created.text
    code = created.json()["public_code"]
    company_id = (
        await db_session.execute(
            text("SELECT id FROM ice_companies WHERE public_code = :code"),
            {"code": code},
        )
    ).scalar_one()
    await db_session.execute(
        text(
            """
            INSERT INTO ice_company_messages (company_id, chat_id, message_id, is_group)
            VALUES (:id, 1304982166, 2820, false)
            """
        ),
        {"id": company_id},
    )
    await remember_inline_card(db_session, company_id=int(company_id), inline_message_id="inline-shared")
    await db_session.commit()
    async with _client() as client:
        joined = await client.post(
            f"/api/public/ice-companies/{code}/responses",
            headers=_headers(**{"X-Telegram-Init-Data": _init(777)}),
            json={"status": "going", "display_name": "Кирил", "consent": True},
        )
    assert joined.status_code == 200, joined.text
    assert joined.json()["going_count"] == 2

    class _Refs(_Sender):
        def __init__(self) -> None:
            super().__init__()
            self.refs: list[dict] = []

        async def edit(self, ref: dict, text: str, buttons: list) -> None:
            self.refs.append(ref)
            await super().edit(ref, text, buttons)

    sender = _Refs()
    await _edit_dirty(db_session, sender, settings=Settings(), debounce_sec=0, now=datetime.now(timezone.utc))
    assert len(sender.edits) == 1
    assert sender.refs[0]["inline_message_id"] == "inline-shared"
    assert "Двое — это уже не катание, а свидание" in sender.edits[0]
    assert "Кирил" in sender.edits[0]
    assert "Аня" in sender.edits[0]


@pytest.mark.asyncio
async def test_tick_only_sync_expire_edit_purge(app_use_test_db, db_session, monkeypatch) -> None:
    created, _, _ = await _create(db_session, monkeypatch, user_id=42)
    assert created.status_code == 201, created.text
    sender = _Sender()
    stats = await tick(db_session, sender, debounce_sec=0)
    assert sender.dms == []
    assert set(stats.keys()) == {"synced", "expired", "edits"}


@pytest.mark.asyncio
async def test_schedule_move_updates_card_without_reconfirm(app_use_test_db, db_session, monkeypatch) -> None:
    created, _, session_id = await _create(db_session, monkeypatch, user_id=42)
    assert created.status_code == 201, created.text
    code = created.json()["public_code"]
    sender = _Sender()
    await tick(db_session, sender, debounce_sec=0)
    assert sender.dms == []
    new_start = datetime.now(timezone.utc) + timedelta(days=4)
    await db_session.execute(
        text("UPDATE ice_sessions SET starts_at_utc = :start, ends_at_utc = :end WHERE id = :id"),
        {"start": new_start, "end": new_start + timedelta(hours=1), "id": session_id},
    )
    await db_session.commit()
    await tick(db_session, sender, debounce_sec=0)
    assert sender.dms == []
    async with _client() as client:
        view = await client.get(f"/api/public/ice-companies/{code}")
    body = view.json()
    assert "needs_reconfirm" not in body
    assert "Подтвердите ещё раз" not in body["card_text"]
    assert body["event"]["version"] == 2
