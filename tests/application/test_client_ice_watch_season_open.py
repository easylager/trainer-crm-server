"""season_open ice watches — subscribe, notify, interaction with sessions watches."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from src.application.client_ice_watch_use_cases import (
    compose_season_open_telegram_message,
    notify_ice_watches_after_arena_publish,
    notify_season_open_watches,
    subscribe_ice_watch,
)
from src.infrastructure.db.models import ICE_WATCH_KIND_SEASON_OPEN


async def _city(db_session) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO cities (name, country, price_group, is_active, sort_order)
            VALUES ('Season Watch City', 'BY', 'default', true, 0)
            RETURNING id
            """
        )
    )
    return int(r.scalar_one())


async def _client(db_session, *, telegram_id: int) -> int:
    await db_session.execute(
        text(
            """
            INSERT INTO client_sessions (telegram_id, state)
            VALUES (:tid, 'idle')
            ON CONFLICT (telegram_id) DO NOTHING
            """
        ),
        {"tid": telegram_id},
    )
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (first_name, telegram_id, is_sandbox)
            VALUES ('Season', :tid, false)
            RETURNING id
            """
        ),
        {"tid": telegram_id},
    )
    return int(r.scalar_one())


async def _arena(
    db_session,
    *,
    city_id: int,
    address: str = "ул. Ленинская, 50Б",
    phone: str = "+375291112233",
    season_start: int = 12,
    season_end: int = 3,
) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, latitude, longitude, is_active, is_confirmed, venue_type)
            VALUES (:cid, 'Стадион «Спартак»', :addr, 53.9, 27.5, true, true, 'outdoor')
            RETURNING id
            """
        ),
        {"cid": city_id, "addr": address},
    )
    arena_id = int(r.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO arena_profiles (
                arena_id, city_id, slug, timezone, status,
                season_start_month, season_end_month, phone
            )
            VALUES (:aid, :cid, 'spartak-season', 'Europe/Minsk', 'published', :s, :e, :phone)
            """
        ),
        {"aid": arena_id, "cid": city_id, "s": season_start, "e": season_end, "phone": phone},
    )
    return arena_id


async def _future_session(db_session, arena_id: int) -> None:
    starts = datetime.now(timezone.utc) + timedelta(days=2)
    ends = starts + timedelta(minutes=60)
    await db_session.execute(
        text(
            """
            INSERT INTO ice_sessions (
                arena_id, kind, status, starts_at_utc, ends_at_utc,
                starts_at_local, ends_at_local, local_date, schedule_basis, currency_code
            )
            VALUES (
                :aid, 'public_skate', 'active', :start, :end,
                '14:00', '15:00', :ld, 'live', 'BYN'
            )
            """
        ),
        {
            "aid": arena_id,
            "start": starts,
            "end": ends,
            "ld": starts.date(),
        },
    )


def test_compose_season_open_message_with_phone() -> None:
    msg = compose_season_open_telegram_message(
        arena_name='Стадион «Спартак»',
        address="ул. Ленинская, 50Б",
        season_start_month=12,
        has_phone=True,
    )
    assert "Пора проверять коньки" in msg
    assert "обычно открывается в декабре" in msg
    assert "на улице Ленинская, 50Б" in msg
    assert "на ул." not in msg
    assert "телефон" in msg
    assert "луже" in msg
    assert "начался сезон" not in msg.lower()
    assert "каток открыт" not in msg.lower()


def test_compose_season_open_message_without_phone() -> None:
    msg = compose_season_open_telegram_message(
        arena_name="Каток",
        address="площадь Ленина",
        season_start_month=12,
        has_phone=False,
    )
    assert "телефон" not in msg
    assert "на площади Ленина" in msg
    assert "на площадь " not in msg
    assert "лужа коньков не любит" in msg


def test_compose_season_open_message_declines_prospekt() -> None:
    msg = compose_season_open_telegram_message(
        arena_name="Каток на Немиге",
        address="пр-т Победителей, 4а",
        season_start_month=11,
        has_phone=False,
    )
    assert "на проспекте Победителей, 4а" in msg
    assert "в ноябре" in msg


@pytest.mark.asyncio
async def test_subscribe_season_open(db_session) -> None:
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id=city_id)
    client_id = await _client(db_session, telegram_id=7_700_000_001)
    await db_session.commit()

    watch = await subscribe_ice_watch(
        db_session,
        client_id=client_id,
        telegram_id=7_700_000_001,
        arena_id=arena_id,
        watch_kind=ICE_WATCH_KIND_SEASON_OPEN,
        filter_json={},
        city_id=city_id,
    )
    assert watch["kind"] == ICE_WATCH_KIND_SEASON_OPEN
    assert "декабре" in watch["status_label"]


@pytest.mark.asyncio
async def test_season_open_notify_sends_and_deactivates(db_session) -> None:
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id=city_id)
    client_id = await _client(db_session, telegram_id=7_700_000_002)
    await subscribe_ice_watch(
        db_session,
        client_id=client_id,
        telegram_id=7_700_000_002,
        arena_id=arena_id,
        watch_kind=ICE_WATCH_KIND_SEASON_OPEN,
        filter_json={},
        city_id=city_id,
    )
    await db_session.commit()

    send = AsyncMock()
    now = datetime(2026, 12, 5, 10, 0, tzinfo=timezone.utc)
    sent = await notify_season_open_watches(db_session, now=now, send_fn=send)
    assert sent == 1
    send.assert_awaited_once()
    body = send.await_args.args[1]
    assert "Пора проверять коньки" in body
    assert "на улице Ленинская, 50Б" in body
    assert "каток открыт" not in body.lower()

    active = await db_session.execute(
        text("SELECT active FROM client_ice_watches WHERE arena_id = :aid AND watch_kind = :k"),
        {"aid": arena_id, "k": ICE_WATCH_KIND_SEASON_OPEN},
    )
    assert active.scalar() is False


@pytest.mark.asyncio
async def test_season_open_skipped_when_future_sessions(db_session) -> None:
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id=city_id)
    client_id = await _client(db_session, telegram_id=7_700_000_003)
    await _future_session(db_session, arena_id)
    await subscribe_ice_watch(
        db_session,
        client_id=client_id,
        telegram_id=7_700_000_003,
        arena_id=arena_id,
        watch_kind=ICE_WATCH_KIND_SEASON_OPEN,
        filter_json={},
        city_id=city_id,
    )
    await db_session.commit()

    send = AsyncMock()
    now = datetime(2026, 12, 5, 10, 0, tzinfo=timezone.utc)
    sent = await notify_season_open_watches(db_session, now=now, send_fn=send)
    assert sent == 0
    send.assert_not_awaited()
    active = await db_session.execute(
        text("SELECT active FROM client_ice_watches WHERE arena_id = :aid AND watch_kind = :k"),
        {"aid": arena_id, "k": ICE_WATCH_KIND_SEASON_OPEN},
    )
    assert active.scalar() is False


@pytest.mark.asyncio
async def test_sessions_notify_clears_season_open(db_session) -> None:
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id=city_id)
    client_id = await _client(db_session, telegram_id=7_700_000_004)
    await _future_session(db_session, arena_id)
    await subscribe_ice_watch(
        db_session,
        client_id=client_id,
        telegram_id=7_700_000_004,
        arena_id=arena_id,
        watch_kind="sessions",
        filter_json={"when": "any", "intent": "skate"},
        city_id=city_id,
    )
    await subscribe_ice_watch(
        db_session,
        client_id=client_id,
        telegram_id=7_700_000_004,
        arena_id=arena_id,
        watch_kind=ICE_WATCH_KIND_SEASON_OPEN,
        filter_json={},
        city_id=city_id,
    )
    await db_session.commit()

    send = AsyncMock()
    sent = await notify_ice_watches_after_arena_publish(db_session, arena_id, send_fn=send)
    assert sent == 1
    assert send.await_count == 1
    assert "Появились сеансы" in send.await_args.args[1]

    season_active = await db_session.execute(
        text("SELECT active FROM client_ice_watches WHERE arena_id = :aid AND watch_kind = :k"),
        {"aid": arena_id, "k": ICE_WATCH_KIND_SEASON_OPEN},
    )
    assert season_active.scalar() is False
