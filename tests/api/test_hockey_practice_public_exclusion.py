"""TASK-201-A AC-2: hockey_practice is stored but never shown on skate surfaces."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_session_use_cases import KIND_HOCKEY_PRACTICE, KIND_PUBLIC_SKATE, STATUS_ACTIVE
from tests.db_catalog_helpers import require_seed_city_id
from src.ingestion.jobs import SqlAlchemyParserJobStore
from src.ingestion.publish import SqlAlchemyIceSessionPublisher
from src.ingestion.types import CanonicalSlotDraft, RUN_STATUS_OK, ScrapeRunRecord

_MINSK = ZoneInfo("Europe/Minsk")
_NOW = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
_FUTURE_DAY = date(2026, 10, 15)


def _utc(day: date, hhmm: time) -> datetime:
    return datetime.combine(day, hhmm, tzinfo=_MINSK).astimezone(timezone.utc)


def _draft(arena_id: int, kind: str, start: time) -> CanonicalSlotDraft:
    starts = _utc(_FUTURE_DAY, start)
    ends = starts + timedelta(hours=1)
    end_local = ends.astimezone(_MINSK).time().replace(tzinfo=None)
    return CanonicalSlotDraft(
        arena_id=arena_id,
        kind=kind,
        starts_at_utc=starts,
        ends_at_utc=ends,
        local_date=_FUTURE_DAY,
        starts_at_local=start,
        ends_at_local=end_local,
        price_adult_minor=1700,
        price_child_minor=None,
        price_rental_minor=None,
        currency_code="BYN",
        status=STATUS_ACTIVE,
        observed_at=_NOW,
        valid_until=ends,
        source_id=f"test:{kind}:{start.isoformat()}",
    )


async def _arena_with_profile(db_session, city_id: int) -> int:
    arena_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                    VALUES (:cid, 'ОХМ-тест', 'ул. Льда, 1', true, true)
                    RETURNING id
                    """
                ),
                {"cid": city_id},
            )
        ).scalar_one()
    )
    await db_session.execute(
        text(
            """
            INSERT INTO arena_profiles (arena_id, city_id, slug, status, timezone)
            VALUES (:aid, :cid, 'ohm-test-arena', 'published', 'Europe/Minsk')
            """
        ),
        {"aid": arena_id, "cid": city_id},
    )
    return arena_id


@pytest.mark.asyncio
async def test_skate_surfaces_exclude_hockey_practice(app_use_test_db, db_session) -> None:
    seed_city_id = await require_seed_city_id(db_session)
    arena_id = await _arena_with_profile(db_session, seed_city_id)
    job_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                    VALUES (:aid, 'test_parser', true, 'daily', :next, '{}'::jsonb)
                    RETURNING id
                    """
                ),
                {"aid": arena_id, "next": _NOW},
            )
        ).scalar_one()
    )
    publisher = SqlAlchemyIceSessionPublisher(db_session)
    run = ScrapeRunRecord(
        job_id=job_id,
        arena_id=arena_id,
        parser_key="test_parser",
        status=RUN_STATUS_OK,
        slot_count=2,
        slots_dropped=0,
        error_message=None,
        started_at=_NOW,
        finished_at=_NOW,
    )
    drafts = [
        _draft(arena_id, KIND_PUBLIC_SKATE, time(18, 0)),
        _draft(arena_id, KIND_HOCKEY_PRACTICE, time(10, 0)),
    ]
    await publisher.publish(run, drafts, run_id=1)
    await db_session.commit()

    kinds_public = (
        await db_session.execute(
            text("SELECT DISTINCT kind FROM ice_sessions WHERE arena_id = :aid ORDER BY kind"),
            {"aid": arena_id},
        )
    ).scalars().all()
    assert set(kinds_public) == {KIND_PUBLIC_SKATE, KIND_HOCKEY_PRACTICE}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        list_resp = await client.get(
            "/api/public/ice/arenas",
            params={"city_id": seed_city_id, "intent": "skate", "limit": 50},
        )
        assert list_resp.status_code == 200
        listed = [a for a in list_resp.json()["items"] if a["id"] == arena_id]
        assert listed and listed[0].get("tier") == "A"

        card = await client.get(
            f"/api/public/arenas/{arena_id}/sessions",
            params={"city_id": seed_city_id},
        )
        assert card.status_code == 200
        payload = card.json()
        flat: list[dict] = []
        for day in payload.get("days") or []:
            flat.extend(day.get("sessions") or [])
        assert flat
        assert all(s["kind"] == KIND_PUBLIC_SKATE for s in flat)

        city = (
            await db_session.execute(text("SELECT name FROM cities WHERE id = :id"), {"id": seed_city_id})
        ).scalar_one()
        ice_day = await client.get(f"/ice/{city}/today")
        assert ice_day.status_code == 200
        assert KIND_HOCKEY_PRACTICE not in ice_day.text

        hub = await client.get("/api/client/hub/bootstrap")
        assert hub.status_code == 200
        teaser = hub.json().get("ice_teaser")
        if teaser and teaser.get("arena_id") == arena_id:
            assert teaser.get("kind") == KIND_PUBLIC_SKATE

    shown = await SqlAlchemyParserJobStore(db_session).count_shown_sessions(arena_id, _NOW)
    assert shown == 1


@pytest.mark.asyncio
async def test_hockey_only_publish_is_ok_for_job_health(db_session) -> None:
    """ОХМ без МК не считается empty-прогоном и не ломает count_shown (только МК)."""
    seed_city_id = await require_seed_city_id(db_session)
    arena_id = await _arena_with_profile(db_session, seed_city_id)
    job_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                    VALUES (:aid, 'test_parser', true, 'daily', :next, '{}'::jsonb)
                    RETURNING id
                    """
                ),
                {"aid": arena_id, "next": _NOW},
            )
        ).scalar_one()
    )
    publisher = SqlAlchemyIceSessionPublisher(db_session)
    run = ScrapeRunRecord(
        job_id=job_id,
        arena_id=arena_id,
        parser_key="test_parser",
        status=RUN_STATUS_OK,
        slot_count=1,
        slots_dropped=0,
        error_message=None,
        started_at=_NOW,
        finished_at=_NOW,
    )
    await publisher.publish(run, [_draft(arena_id, KIND_HOCKEY_PRACTICE, time(11, 0))], run_id=2)
    await db_session.commit()
    shown = await SqlAlchemyParserJobStore(db_session).count_shown_sessions(arena_id, _NOW)
    assert shown == 0
    ohm_count = (
        await db_session.execute(
            text("SELECT COUNT(*)::int FROM ice_sessions WHERE arena_id = :aid AND kind = :k"),
            {"aid": arena_id, "k": KIND_HOCKEY_PRACTICE},
        )
    ).scalar_one()
    assert ohm_count == 1


@pytest.mark.asyncio
async def test_hockey_practice_publish_twice_no_duplicates(db_session) -> None:
    seed_city_id = await require_seed_city_id(db_session)
    arena_id = await _arena_with_profile(db_session, seed_city_id)
    job_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                    VALUES (:aid, 'test_parser', true, 'daily', :next, '{}'::jsonb)
                    RETURNING id
                    """
                ),
                {"aid": arena_id, "next": _NOW},
            )
        ).scalar_one()
    )
    publisher = SqlAlchemyIceSessionPublisher(db_session)
    draft = _draft(arena_id, KIND_HOCKEY_PRACTICE, time(9, 30))
    for run_id in (3, 4):
        run = ScrapeRunRecord(
            job_id=job_id,
            arena_id=arena_id,
            parser_key="test_parser",
            status=RUN_STATUS_OK,
            slot_count=1,
            slots_dropped=0,
            error_message=None,
            started_at=_NOW,
            finished_at=_NOW,
        )
        await publisher.publish(run, [draft], run_id=run_id)
    await db_session.commit()
    count = (
        await db_session.execute(
            text(
                """
                SELECT COUNT(*)::int FROM ice_sessions
                WHERE arena_id = :aid AND kind = :k AND local_date = :d
                """
            ),
            {"aid": arena_id, "k": KIND_HOCKEY_PRACTICE, "d": _FUTURE_DAY},
        )
    ).scalar_one()
    assert count == 1
