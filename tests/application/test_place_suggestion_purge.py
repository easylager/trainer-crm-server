"""PDEC-028 Task 16: контакты закрытых заявок стираются через 30 дней."""
import asyncio
import uuid

import pytest
from sqlalchemy import text

from src.application import place_suggestion_use_cases as uc
from src.application.place_suggestion_use_cases import create_place_suggestion, purge_closed_contacts
from src.bot import notification_loops


async def _noop(*_a, **_kw):
    return None


@pytest.fixture(autouse=True)
def _no_telegram(monkeypatch):
    """Никаких реальных сообщений в Telegram: .env держит боевые токены ботов."""
    monkeypatch.setattr(uc, "notify_admins_new_place_suggestion", _noop)


async def _suggest(db_session, *, status: str, closed_days_ago: int | None, author=None) -> int:
    res = await create_place_suggestion(
        db_session, source="site", kind="ice", city_id=None,
        new_city={"name": f"Пса-Стирание-{uuid.uuid4().hex[:6]}", "country": "BY"}, name="Каток-стирание",
        address=None, details={}, contact="@purge_me", author_telegram_id=None, client_ip=None,
    )
    sid = int(res["id"])
    await db_session.execute(
        text(
            "UPDATE place_suggestions SET status=:st, author_telegram_id=:a, "
            "closed_at = CASE WHEN CAST(:d AS int) IS NULL THEN NULL ELSE now() - make_interval(days => CAST(:d AS int)) END "
            "WHERE id=:id"
        ),
        {"st": status, "a": author, "d": closed_days_ago, "id": sid},
    )
    await db_session.commit()
    return sid


async def _row(db_session, sid: int):
    return (await db_session.execute(
        text("SELECT contact, contact_kind, bind_token, author_telegram_id FROM place_suggestions WHERE id=:id"),
        {"id": sid},
    )).one()


@pytest.mark.asyncio
async def test_purge_only_old_closed_and_keeps_author(db_session):
    old = await _suggest(db_session, status="rejected", closed_days_ago=31, author=7_700_000_001)
    fresh = await _suggest(db_session, status="approved", closed_days_ago=5)
    still_open = await _suggest(db_session, status="new", closed_days_ago=None)

    assert await purge_closed_contacts(db_session) >= 1
    contact, kind, token, author = await _row(db_session, old)
    assert (contact, kind, token) == (None, None, None) and int(author) == 7_700_000_001
    assert (await _row(db_session, fresh))[0] == "@purge_me"
    assert (await _row(db_session, still_open))[2] is not None
    # Открытая заявка сохраняет и контакт, и ссылку привязки.
    assert (await _row(db_session, still_open))[0] == "@purge_me"


@pytest.mark.asyncio
async def test_purge_loop_runs_purge_then_sleeps(monkeypatch):
    calls: list[int] = []
    sleeps: list[float] = []

    async def _fake_purge(_session, **_kw):
        calls.append(1)
        return 2

    class _Factory:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_a):
            return False

    async def _sleep(sec):
        sleeps.append(sec)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(uc, "purge_closed_contacts", _fake_purge)
    monkeypatch.setattr(notification_loops, "async_session_factory", lambda: _Factory())
    monkeypatch.setattr(notification_loops.asyncio, "sleep", _sleep)
    with pytest.raises(asyncio.CancelledError):
        await notification_loops.run_place_suggestion_purge_loop()
    assert calls == [1]
    assert sleeps == [
        notification_loops.PLACE_SUGGESTION_PURGE_FIRST_DELAY_SEC,
        notification_loops.PLACE_SUGGESTION_PURGE_INTERVAL_SEC,
    ]
