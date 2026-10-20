"""TASK-304: домашний матч Динамо как событие — компания друзей на движке льда, страница матча, слот главной."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.deps import get_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.api.routes import webapp_client_hockey_event as event_routes
from src.application.hockey_event import event_view
from src.application.hockey_hub import hub_card
from src.application.ice_company import service as company_service
from src.application.ice_company.codes import tg_participant_key
from src.application.ice_company.copy import card_text
from src.application.ice_company.lifecycle import _edit_dirty, buttons_for, reset_edit_debounce, tick
from src.application.ice_company.service import (
    CompanyRejected,
    _load,
    _responses,
    create_company,
    create_match_company,
    respond,
    snap_from,
)
from src.bot.handlers import ice_company_handlers as handlers
from src.shared.config import Settings
from tests.api.test_ice_invites import _insert_session
from tests.api.test_public_arenas import _insert_arena, _insert_city

ME = 880_304_001
FRIEND = 880_304_002
STRANGER = 880_304_003
BASE = "/api/webapp/client/hockey"


class as_client:
    """Подмена клиента Mini App: и ``with``, и ``async with`` (рядом с AsyncClient)."""

    def __init__(self, user_id: int, platform: MiniAppPlatform = MiniAppPlatform.TELEGRAM) -> None:
        self.principal = MiniAppPrincipal(platform=platform, user_id=user_id)

    def __enter__(self) -> None:
        app.dependency_overrides[get_client_miniapp_principal] = lambda: self.principal

    def __exit__(self, *exc) -> None:
        app.dependency_overrides.pop(get_client_miniapp_principal, None)

    async def __aenter__(self) -> None:
        self.__enter__()

    async def __aexit__(self, *exc) -> None:
        self.__exit__()


@pytest.fixture(autouse=True)
def _env(monkeypatch) -> None:
    monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "1")
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.test")
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "1")
    monkeypatch.delenv("CLIENT_MINI_APP_SHORT_NAME", raising=False)
    reset_edit_debounce()


@pytest.fixture
def prepared(monkeypatch) -> list[dict]:
    """Вместо Telegram: запоминаем, что ушло бы в savePreparedInlineMessage."""
    calls: list[dict] = []

    async def fake(token, user_id, code, text_, buttons, photo=None, title=""):
        calls.append({"user_id": user_id, "code": code, "text": text_, "buttons": buttons, "photo": photo})
        return "PM-1"

    monkeypatch.setattr(event_routes, "save_prepared", fake)
    return calls


@pytest.fixture
async def arena(db_session) -> dict:
    city_id = await _insert_city(db_session, name=f"Мин{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, city_id, name="Минск Арена", address="пр. Победителей, 111")
    return {"city_id": city_id, "arena_id": arena_id}


async def _match(
    db_session,
    *,
    starts_at: datetime | None = None,
    home: str = "Динамо-Минск",
    away: str = "СКА",
    status: str = "scheduled",
    source_match_id: str | None = None,
) -> int:
    return int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at, status)
                    VALUES ('hcdinamo', :mid, :home, :away, :starts_at, :status)
                    RETURNING id
                    """),
                {
                    "mid": source_match_id or uuid.uuid4().hex[:12],
                    "home": home,
                    "away": away,
                    "starts_at": starts_at or datetime.now(timezone.utc) + timedelta(days=2),
                    "status": status,
                },
            )
        ).scalar_one()
    )


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _events(db_session, match_id: int) -> int:
    return int(
        (
            await db_session.execute(
                text("SELECT COUNT(*) FROM ice_company_events WHERE source_ref = :s"),
                {"s": f"hockey_match:{match_id}"},
            )
        ).scalar_one()
    )


async def _companies(db_session, match_id: int) -> int:
    return int(
        (
            await db_session.execute(
                text("""
                    SELECT COUNT(*) FROM ice_companies c JOIN ice_company_events e ON e.id = c.event_id
                    WHERE e.source_ref = :s
                    """),
                {"s": f"hockey_match:{match_id}"},
            )
        ).scalar_one()
    )


# ---------- сервис ----------


@pytest.mark.asyncio
async def test_event_is_created_once_and_company_is_one_per_organizer(db_session, arena) -> None:
    starts = datetime.now(timezone.utc) + timedelta(days=2)
    match_id = await _match(db_session, starts_at=starts)

    first = await create_match_company(
        db_session, telegram_user_id=ME, match_id=match_id, home_team="Динамо-Минск", display_name="Макс"
    )
    again = await create_match_company(
        db_session, telegram_user_id=ME, match_id=match_id, home_team="Динамо-Минск", display_name="Макс"
    )
    other = await create_match_company(
        db_session, telegram_user_id=FRIEND, match_id=match_id, home_team="Динамо-Минск", display_name="Аня"
    )

    assert first["public_code"] == again["public_code"]
    assert other["public_code"] != first["public_code"]
    assert await _events(db_session, match_id) == 1
    assert await _companies(db_session, match_id) == 2
    event = (
        (
            await db_session.execute(
                text("SELECT * FROM ice_company_events WHERE source_ref = :s"), {"s": f"hockey_match:{match_id}"}
            )
        )
        .mappings()
        .one()
    )
    assert event["kind"] == "hockey_match"
    assert event["venue_ref"] == f"arena:{arena['arena_id']}"
    assert event["venue_label"] == "Минск-Арена"
    assert event["city_id"] == arena["city_id"]
    assert event["ends_at"] - event["starts_at"] == timedelta(hours=2, minutes=30)
    assert first["going_count"] == 1 and first["going"] == [{"display_name": "Макс"}]
    assert first["name"] == "Динамо-Минск — СКА"


@pytest.mark.asyncio
async def test_away_started_and_cancelled_matches_are_refused(db_session, arena) -> None:
    away = await _match(db_session, home="СКА", away="Динамо-Минск")
    started = await _match(db_session, starts_at=datetime.now(timezone.utc) - timedelta(minutes=5))

    for match_id, code in ((away, 404), (started, 409), (10**9, 404)):
        with pytest.raises(CompanyRejected) as exc:
            await create_match_company(
                db_session, telegram_user_id=ME, match_id=match_id, home_team="Динамо-Минск", display_name="Макс"
            )
        assert exc.value.status_code == code
    assert await _events(db_session, away) == 0


@pytest.mark.asyncio
async def test_answers_are_written_and_texts_do_not_mix_with_ice(db_session, arena) -> None:
    match_id = await _match(db_session)
    view = await create_match_company(
        db_session, telegram_user_id=ME, match_id=match_id, home_team="Динамо-Минск", display_name="Макс"
    )
    code = view["public_code"]
    for who, name, status in ((FRIEND, "Аня", "going"), (STRANGER, "Дима", "maybe")):
        await respond(
            db_session,
            code=code,
            status=status,
            display_name=name,
            participant_key=tg_participant_key(who),
            source="tg",
            consent=True,
        )
    await respond(
        db_session,
        code=code,
        status="cant",
        display_name=None,
        participant_key=tg_participant_key(ME),
        source="tg",
        consent=True,
    )

    company = await _load(db_session, code)
    rows = await _responses(db_session, int(company["id"]))
    assert {r["display_name"]: r["status"] for r in rows} == {"Макс": "cant", "Аня": "going", "Дима": "maybe"}

    body = card_text(snap_from(company, rows))
    lines = body.split("\n")
    assert lines[0] == "Идём на матч?"
    assert lines[1].startswith("Динамо-Минск — СКА · ") and lines[1].endswith(" · Минск-Арена")
    assert lines[2] == "Идут: Аня · Смотрит дома: Дима"
    assert "На льду" not in body and "Лёд" not in body

    labels = [b["text"] for b in buttons_for(company, snap_from(company, rows), "https://x")]
    assert labels == ["Иду", "Смотрю дома", "Не смогу", "Подробнее"]


@pytest.mark.asyncio
async def test_ice_card_keeps_its_own_texts_and_buttons(db_session, monkeypatch) -> None:
    city_id = await _insert_city(db_session, name=f"Лёд{uuid.uuid4().hex[:6]}")
    ice_arena = await _insert_arena(db_session, city_id, name="Каток")
    session_id = await _insert_session(db_session, ice_arena, starts_at=datetime.now(timezone.utc) + timedelta(days=2))
    monkeypatch.setenv("ICE_COMPANY_CITY_IDS", str(city_id))
    view = await create_company(db_session, telegram_user_id=ME, session_id=session_id, display_name="Макс")
    await respond(
        db_session,
        code=view["public_code"],
        status="maybe",
        display_name="Дима",
        participant_key=tg_participant_key(STRANGER),
        source="tg",
        consent=True,
    )
    company = await _load(db_session, view["public_code"])
    snap = snap_from(company, await _responses(db_session, int(company["id"])))
    body = card_text(snap)
    assert "Массовое катание" in body and "На льду Макс." in body
    assert "Дима" not in body and "Смотрит дома" not in body
    assert [b["text"] for b in buttons_for(company, snap, "https://x")] == [
        "Иду",
        "Не могу",
        "В другой чат →",
        "На лёд",
    ]


@pytest.mark.asyncio
async def test_match_company_does_not_use_up_the_ice_limit(db_session, arena) -> None:
    for _ in range(6):
        match_id = await _match(db_session)
        await create_match_company(
            db_session, telegram_user_id=ME, match_id=match_id, home_team="Динамо-Минск", display_name="Макс"
        )
    assert await _companies(db_session, match_id) == 1


@pytest.mark.asyncio
async def test_web_answers_to_a_match_are_refused(db_session, arena) -> None:
    match_id = await _match(db_session)
    view = await create_match_company(
        db_session, telegram_user_id=ME, match_id=match_id, home_team="Динамо-Минск", display_name="Макс"
    )
    with pytest.raises(CompanyRejected) as exc:
        await respond(
            db_session,
            code=view["public_code"],
            status="going",
            display_name="Гость",
            participant_key="web:abc",
            source="web",
            consent=True,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_moved_and_cancelled_match_reach_the_card(db_session, arena) -> None:
    match_id = await _match(db_session)
    view = await create_match_company(
        db_session, telegram_user_id=ME, match_id=match_id, home_team="Динамо-Минск", display_name="Макс"
    )
    new_start = datetime.now(timezone.utc) + timedelta(days=5)
    await db_session.execute(
        text("UPDATE hockey_matches SET starts_at = :s WHERE id = :i"), {"s": new_start, "i": match_id}
    )
    sent: list[str] = []

    class _Sender:
        async def dm(self, chat_id, text_, buttons):
            return 1

        async def edit(self, ref, text_, buttons):
            sent.append(text_)

    await tick(db_session, _Sender(), debounce_sec=0)
    moved = (await _read(db_session, view["public_code"]))["event"]
    assert moved["version"] == 2 and moved["starts_at"] == new_start.isoformat()
    assert moved["ends_at"] == (new_start + timedelta(hours=2, minutes=30)).isoformat()

    await db_session.execute(text("UPDATE hockey_matches SET status = 'cancelled' WHERE id = :i"), {"i": match_id})
    await tick(db_session, _Sender(), debounce_sec=0)
    cancelled = await _read(db_session, view["public_code"])
    assert cancelled["status"] == "cancelled" and cancelled["event"]["cancelled"] is True
    assert "Матч отменён" in cancelled["card_text"] or "Сбор снят" in cancelled["card_text"]


async def _read(db_session, code: str) -> dict:
    return await company_service.read_company(db_session, code)


# ---------- бот ----------


@pytest.mark.asyncio
async def test_bot_callback_maybe_on_match_company(db_session, arena, monkeypatch) -> None:
    match_id = await _match(db_session)
    view = await create_match_company(
        db_session, telegram_user_id=ME, match_id=match_id, home_team="Динамо-Минск", display_name="Макс"
    )
    code = view["public_code"]

    class _Ctx:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    edits: list[tuple[dict, str, list]] = []

    class _Sender:
        def __init__(self, bot, settings=None) -> None:
            pass

        async def edit(self, ref, text_, buttons):
            edits.append((ref, text_, buttons))

    monkeypatch.setattr(handlers, "async_session_factory", lambda: _Ctx())
    monkeypatch.setattr(handlers, "AiogramSender", _Sender)
    answers: list[str] = []

    async def answer(toast=None, show_alert=False):
        answers.append(toast)

    query = SimpleNamespace(
        data=f"ic:{code}:m",
        from_user=SimpleNamespace(id=FRIEND, first_name="Дима", username=None),
        inline_message_id="inline-1",
        bot=object(),
        answer=answer,
    )
    await handlers.on_company_callback(query)

    assert answers == ["Записали, смотришь дома"]
    company = await _load(db_session, code)
    rows = await _responses(db_session, int(company["id"]))
    assert {r["display_name"]: r["status"] for r in rows}["Дима"] == "maybe"
    assert len(edits) == 1
    assert edits[0][0]["inline_message_id"] == "inline-1"
    assert "Смотрит дома: Дима" in edits[0][1]
    assert "photo_url" not in edits[0][0]
    assert [b["text"] for b in edits[0][2]] == ["Иду", "Смотрю дома", "Не смогу", "Подробнее"]

    # Лёд отвечает своим тостом на «Может»: тексты не перепутаны.
    from src.application.ice_company.copy import toast_for

    assert toast_for("public_skate", "m") == "Записали, может быть"


# ---------- API ----------


@pytest.mark.asyncio
async def test_event_404_for_away_unknown_and_flag_off(app_use_test_db, db_session, arena, monkeypatch) -> None:
    home = await _match(db_session)
    away = await _match(db_session, home="СКА", away="Динамо-Минск")
    await db_session.commit()
    async with _client() as client, as_client(ME):
        assert (await client.get(f"{BASE}/matches/{home}/event")).status_code == 200
        assert (await client.get(f"{BASE}/matches/{away}/event")).status_code == 404
        assert (await client.get(f"{BASE}/matches/999999999/event")).status_code == 404
        assert (await client.put(f"{BASE}/matches/{away}/rsvp", json={"status": "going"})).status_code == 404
        assert (await client.post(f"{BASE}/matches/{away}/invite")).status_code == 404

        monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "0")
        assert (await client.get(f"{BASE}/matches/{home}/event")).status_code == 404
        assert (await client.put(f"{BASE}/matches/{home}/rsvp", json={"status": "going"})).status_code == 404
        assert (await client.post(f"{BASE}/matches/{home}/invite")).status_code == 404
        assert (await client.put(f"{BASE}/prefs", json={"kk_hidden": True})).status_code == 404
        assert (await client.get(f"{BASE}/prefs")).status_code == 404
    assert await _events(db_session, home) == 0


@pytest.mark.asyncio
async def test_event_shape_tickets_and_empty_state(app_use_test_db, db_session, arena) -> None:
    starts = datetime.now(timezone.utc) + timedelta(days=2)
    match_id = await _match(db_session, starts_at=starts, source_match_id="1218846")
    await db_session.commit()
    async with _client() as client, as_client(ME):
        r = await client.get(f"{BASE}/matches/{match_id}/event")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["match"]["id"] == match_id
    assert body["match"]["is_home"] is True and body["match"]["status"] == "scheduled"
    assert body["match"]["home"]["name"] == "Динамо-Минск" and body["match"]["away"]["name"] == "СКА"
    assert {"color", "logo", "short"} <= set(body["match"]["home"])
    assert body["match"]["result"] is None
    assert body["arena"] == {"name": "Минск-Арена", "arena_id": arena["arena_id"], "address": "пр. Победителей, 111"}
    assert body["my_status"] is None and body["people"] == []
    assert body["kk"] == {"hidden": False, "phase": "open", "my_pick": None, "points": None, "company_names": []}
    assert body["tickets_url"] == "https://hcdinamo.by/tickets/?match=1218846"
    assert body["ice_after"] == []
    # GET ничего не создаёт.
    assert await _events(db_session, match_id) == 0

    async with _client() as client, as_client(ME):
        other = await _match(db_session, source_match_id="не-число")
        await db_session.commit()
        r = await client.get(f"{BASE}/matches/{other}/event")
    assert r.json()["tickets_url"] == "https://hcdinamo.by/tickets/"


@pytest.mark.asyncio
async def test_rsvp_flow_people_privacy_and_invited_answer(app_use_test_db, db_session, arena, prepared) -> None:
    match_id = await _match(db_session)
    await db_session.commit()
    async with _client() as client:
        with as_client(ME):
            r = await client.put(f"{BASE}/matches/{match_id}/rsvp", json={"status": "maybe", "display_name": "Макс"})
            assert r.status_code == 200, r.text
            assert r.json()["my_status"] == "maybe"
            assert r.json()["people"] == [], "один я — это не «кто из ваших»"
            bad = await client.put(f"{BASE}/matches/{match_id}/rsvp", json={"status": "yes"})
            assert bad.status_code == 422
            invite = await client.post(f"{BASE}/matches/{match_id}/invite", json={"display_name": "Макс"})
        code = prepared[-1]["code"]
        assert invite.status_code == 200, invite.text

        with as_client(FRIEND):
            before = await client.get(f"{BASE}/matches/{match_id}/event")
            assert before.json()["people"] == [] and before.json()["my_status"] is None
            r = await client.put(
                f"{BASE}/matches/{match_id}/rsvp", json={"status": "going", "display_name": "Аня", "company": code}
            )
            assert r.status_code == 200, r.text
            friend_view = r.json()
        with as_client(STRANGER):
            stranger = await client.get(f"{BASE}/matches/{match_id}/event")
        with as_client(ME):
            mine = await client.get(f"{BASE}/matches/{match_id}/event")

    assert friend_view["my_status"] == "going"
    assert {(p["name"], p["status"], p["is_me"]) for p in friend_view["people"]} == {
        ("Аня", "going", True),
        ("Макс", "maybe", False),
    }
    assert {(p["name"], p["status"], p["is_me"]) for p in mine.json()["people"]} == {
        ("Аня", "going", False),
        ("Макс", "maybe", True),
    }
    assert stranger.json()["people"] == [] and stranger.json()["my_status"] is None
    for payload in (friend_view, mine.json(), stranger.json(), invite.json()):
        raw = str(payload)
        for key in (ME, FRIEND, STRANGER):
            assert str(key) not in raw and f"tg:{key}" not in raw
        assert all(set(p) == {"name", "status", "is_me"} for p in payload.get("people", []))
    assert await _companies(db_session, match_id) == 2, "у Ани своя компания, у Макса своя"

    # Ответ в приложении догоняет карточку друга: Аня передумала — у Макса в компании тоже.
    async with _client() as client, as_client(FRIEND):
        await client.put(f"{BASE}/matches/{match_id}/rsvp", json={"status": "cant"})
    async with _client() as client, as_client(ME):
        again = await client.get(f"{BASE}/matches/{match_id}/event")
    assert ("Аня", "cant", False) in {(p["name"], p["status"], p["is_me"]) for p in again.json()["people"]}


@pytest.mark.asyncio
async def test_rsvp_refuses_started_match_and_non_telegram(app_use_test_db, db_session, arena) -> None:
    started = await _match(db_session, starts_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    future = await _match(db_session)
    await db_session.commit()
    async with _client() as client:
        with as_client(ME):
            assert (await client.put(f"{BASE}/matches/{started}/rsvp", json={"status": "going"})).status_code == 409
        with as_client(ME, MiniAppPlatform.MAX):
            assert (await client.put(f"{BASE}/matches/{future}/rsvp", json={"status": "going"})).status_code == 403
            assert (await client.post(f"{BASE}/matches/{future}/invite")).status_code == 403
            assert (await client.get(f"{BASE}/matches/{future}/event")).status_code == 200


@pytest.mark.asyncio
async def test_invite_card_buttons_link_and_idempotence(app_use_test_db, db_session, arena, prepared) -> None:
    match_id = await _match(db_session)
    await db_session.commit()
    async with _client() as client, as_client(ME):
        first = await client.post(f"{BASE}/matches/{match_id}/invite", json={"display_name": "Макс"})
        second = await client.post(f"{BASE}/matches/{match_id}/invite")
    assert first.status_code == 200, first.text
    body = first.json()
    code = prepared[0]["code"]
    assert body["prepared_message_id"] == "PM-1"
    assert body["text"].startswith("Идём на матч?\nДинамо-Минск — СКА · ")
    assert body["text"].endswith("Минск-Арена\nИдут: Макс")
    assert body["url"] == f"https://t.me/glide_test_bot?startapp=kkm_{match_id}_{code}"
    buttons = prepared[0]["buttons"]
    assert [b.get("data") for b in buttons[:3]] == [f"ic:{code}:g", f"ic:{code}:m", f"ic:{code}:x"]
    assert buttons[3] == {"text": "Подробнее", "url": body["url"]}
    assert prepared[0]["photo"] is None and prepared[0]["user_id"] == ME
    assert second.json()["url"] == body["url"], "та же компания"
    assert await _companies(db_session, match_id) == 1


@pytest.mark.asyncio
async def test_invite_without_bot_gives_text_and_web_link(app_use_test_db, db_session, arena, monkeypatch) -> None:
    monkeypatch.delenv("CLIENT_BOT_USERNAME", raising=False)
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "")
    match_id = await _match(db_session)
    await db_session.commit()
    async with _client() as client, as_client(ME):
        r = await client.post(f"{BASE}/matches/{match_id}/invite", json={"display_name": "Макс"})
    assert r.status_code == 200, r.text
    assert r.json()["prepared_message_id"] is None
    assert r.json()["url"].startswith(f"https://glide.test/webapp/client-match?id={match_id}&c=")


@pytest.mark.asyncio
async def test_kk_block_phases_picks_and_prefs(app_use_test_db, db_session, arena, prepared) -> None:
    match_id = await _match(db_session)
    await db_session.commit()
    async with _client() as client:
        with as_client(ME):
            await client.put(f"{BASE}/matches/{match_id}/rsvp", json={"status": "going", "display_name": "Макс"})
            code = (await client.post(f"{BASE}/matches/{match_id}/invite")).json()["url"].rsplit("_", 1)[1]
        with as_client(FRIEND):
            await client.put(
                f"{BASE}/matches/{match_id}/rsvp", json={"status": "going", "display_name": "Аня", "company": code}
            )
            await client.put(f"{BASE}/matches/{match_id}/pick", json={"home_score": 3, "away_score": 2})
        with as_client(STRANGER):
            await client.put(f"{BASE}/matches/{match_id}/pick", json={"side": "home"})
        with as_client(ME):
            open_ = (await client.get(f"{BASE}/matches/{match_id}/event")).json()["kk"]
            assert open_["phase"] == "open" and open_["my_pick"] is None
            assert open_["company_names"] == ["Аня"], "посторонний без компании в списке не светится"
            await client.put(f"{BASE}/matches/{match_id}/pick", json={"side": "away"})
            picked = (await client.get(f"{BASE}/matches/{match_id}/event")).json()["kk"]
            assert picked["phase"] == "picked" and picked["my_pick"]["side"] == "away"

            assert (await client.get(f"{BASE}/prefs")).json() == {"kk_hidden": False}
            assert (await client.put(f"{BASE}/prefs", json={"kk_hidden": True})).json() == {"kk_hidden": True}
            assert (await client.get(f"{BASE}/prefs")).json() == {"kk_hidden": True}
            hidden = (await client.get(f"{BASE}/matches/{match_id}/event")).json()["kk"]
            assert hidden["hidden"] is True
        with as_client(FRIEND):
            assert (await client.get(f"{BASE}/matches/{match_id}/event")).json()["kk"]["hidden"] is False

        await db_session.execute(
            text("UPDATE hockey_matches SET starts_at = :s WHERE id = :i"),
            {"s": datetime.now(timezone.utc) - timedelta(minutes=10), "i": match_id},
        )
        with as_client(ME):
            assert (await client.get(f"{BASE}/matches/{match_id}/event")).json()["kk"]["phase"] == "live"
        await db_session.execute(
            text(
                "UPDATE hockey_matches SET status = 'final', home_score = 3, away_score = 2, decided_in = 'regulation',"
                " result_source = 'manual', finalized_at = now() WHERE id = :i"
            ),
            {"i": match_id},
        )
        with as_client(ME):
            final = (await client.get(f"{BASE}/matches/{match_id}/event")).json()
    assert final["kk"]["phase"] == "final"
    assert final["match"]["result"] == {"home_score": 3, "away_score": 2, "decided_in": "regulation"}


@pytest.mark.asyncio
async def test_ice_after_lists_two_sessions_after_the_match(app_use_test_db, db_session, arena) -> None:
    starts = datetime.now(timezone.utc) + timedelta(days=2)
    match_id = await _match(db_session, starts_at=starts)
    await _insert_session(db_session, arena["arena_id"], starts_at=starts + timedelta(hours=1))  # идёт матч
    later = [
        await _insert_session(db_session, arena["arena_id"], starts_at=starts + timedelta(hours=4 + i * 3))
        for i in range(3)
    ]
    await db_session.commit()
    async with _client() as client, as_client(ME):
        r = await client.get(f"{BASE}/matches/{match_id}/event")
    items = r.json()["ice_after"]
    assert [item["session_id"] for item in items] == later[:2]
    assert {"time", "day", "badge", "place", "price", "arena_id", "href", "photo", "invite_url"} <= set(items[0])
    assert items[0]["arena_id"] == arena["arena_id"]
    assert items[0]["href"] == f"arena?ref={arena['arena_id']}&s={later[0]}"


# ---------- слот главной ----------


@pytest.mark.asyncio
async def test_hub_slot_marks_home_match_only(db_session, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    home = await _match(db_session, starts_at=now + timedelta(hours=5))
    card = await hub_card(db_session, ME, now=now)
    assert card["mode"] == "before" and card["match"]["id"] == home
    assert card["is_home"] is True and card["event_href"] == f"client-match?id={home}"

    monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "0")
    off = await hub_card(db_session, ME, now=now)
    assert off["is_home"] is True and "event_href" not in off

    monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "1")
    await db_session.execute(
        text("UPDATE hockey_matches SET home_team = 'СКА', away_team = 'Динамо-Минск' WHERE id = :i"), {"i": home}
    )
    away = await hub_card(db_session, ME, now=now)
    assert away["mode"] == "before" and away["is_home"] is False and "event_href" not in away


@pytest.mark.asyncio
async def test_edit_dirty_uses_text_card_for_match(db_session, arena) -> None:
    match_id = await _match(db_session)
    view = await create_match_company(
        db_session, telegram_user_id=ME, match_id=match_id, home_team="Динамо-Минск", display_name="Макс"
    )
    company = await _load(db_session, view["public_code"])
    await db_session.execute(
        text("INSERT INTO ice_company_messages (company_id, inline_message_id) VALUES (:c, 'inl')"),
        {"c": company["id"]},
    )
    refs: list[dict] = []

    class _Sender:
        async def edit(self, ref, text_, buttons):
            refs.append(ref)

    await _edit_dirty(db_session, _Sender(), settings=Settings(), debounce_sec=0, now=datetime.now(timezone.utc))
    assert len(refs) == 1 and "photo_url" not in refs[0]


@pytest.mark.asyncio
async def test_match_company_has_no_public_ice_page_or_poster(app_use_test_db, db_session, arena) -> None:
    match_id = await _match(db_session)
    view = await create_match_company(
        db_session, telegram_user_id=ME, match_id=match_id, home_team="Динамо-Минск", display_name="Макс"
    )
    code = view["public_code"]
    await db_session.commit()
    async with _client() as client:
        assert (await client.get(f"/k/{code}")).status_code == 404
        assert (await client.get(f"/k/{code}/card.png")).status_code == 404
        assert (await client.get(f"/k/{code}/event.ics")).status_code == 200
        web = await client.post(
            f"/api/public/ice-companies/{code}/responses",
            json={"status": "going", "display_name": "Гость", "consent": True},
        )
    assert web.status_code == 403


@pytest.mark.asyncio
async def test_client_match_page_route_serves_the_stub() -> None:
    async with _client() as client:
        r = await client.get("/webapp/client-match")
    assert r.status_code == 200
    assert "<title>Матч</title>" in r.text


@pytest.mark.asyncio
async def test_event_counts_the_crowd_and_names_the_next_home_match(db_session, arena) -> None:
    starts = datetime.now(timezone.utc) + timedelta(days=2)
    match_id = await _match(db_session, starts_at=starts)
    away_later = await _match(db_session, starts_at=starts + timedelta(days=1), home="СКА", away="Динамо-Минск")
    next_home = await _match(db_session, starts_at=starts + timedelta(days=3), away="Трактор")
    view = await create_match_company(
        db_session, telegram_user_id=ME, match_id=match_id, home_team="Динамо-Минск", display_name="Макс"
    )
    # Друг ответил в двух компаниях — считается один раз, по последнему ответу.
    other = await create_match_company(
        db_session, telegram_user_id=STRANGER, match_id=match_id, home_team="Динамо-Минск", display_name="Дима"
    )
    for code, status in ((view["public_code"], "going"), (other["public_code"], "maybe")):
        await respond(
            db_session,
            code=code,
            status=status,
            display_name="Аня",
            participant_key=tg_participant_key(FRIEND),
            source="tg",
            consent=True,
        )
    ev = await event_view(db_session, player_key=ME, match_id=match_id, now=datetime.now(timezone.utc))
    assert ev["crowd"] == {"going": 2, "maybe": 1}, "Макс и Дима идут (организаторы), Аня — дома"
    assert ev["next_home"]["id"] == next_home and ev["next_home"]["id"] != away_later
    assert ev["next_home"]["away"]["name"] == "Трактор"
    assert ev["next_home"]["event_href"] == f"client-match?id={next_home}"


@pytest.mark.asyncio
async def test_event_says_a_company_is_waiting_before_anyone_answers(db_session, arena) -> None:
    match_id = await _match(db_session)
    now = datetime.now(timezone.utc)
    assert (await event_view(db_session, player_key=ME, match_id=match_id, now=now))["company_open"] is False
    await create_match_company(
        db_session, telegram_user_id=ME, match_id=match_id, home_team="Динамо-Минск", display_name="Макс"
    )
    ev = await event_view(db_session, player_key=ME, match_id=match_id, now=now)
    assert ev["company_open"] is True and ev["people"] == []
