"""Admin/manual CMS announce upsert: no sibling wipe, skip live keys."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from src.application.admin_announced_ice_sessions import upsert_admin_announced_sessions
from src.ingestion.publish import SqlAlchemyIceSessionPublisher
from src.ingestion.scrape_runs import SqlAlchemyScrapeRunRecorder
from src.ingestion.types import RUN_STATUS_OK, CanonicalSlotDraft, ScrapeRunRecord

_MINSK = ZoneInfo("Europe/Minsk")
_NOW = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
_SPEC = json.loads(
    (Path(__file__).resolve().parents[2] / "data/announced-schedules/minsk-speed-oval-weekend-2026-11-07.json").read_text(
        encoding="utf-8"
    )
)


async def _arena(db_session, city_id: int) -> int:
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                    VALUES (:cid, :name, 'пр-т Победителей, 111', true, true)
                    RETURNING id
                    """
                ),
                {"cid": city_id, "name": f"Овал-{uuid.uuid4().hex[:6]}"},
            )
        ).scalar_one()
    )


async def _profile(db_session, arena_id: int, city_id: int) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO arena_profiles (arena_id, city_id, slug, timezone, tickets_url, status)
            VALUES (:a, :cid, :slug, 'Europe/Minsk', 'https://saleframe.minskarena.by/service/139', 'published')
            ON CONFLICT (arena_id) DO UPDATE SET timezone = 'Europe/Minsk'
            """
        ),
        {"a": arena_id, "cid": city_id, "slug": f"oval-{arena_id}"},
    )


@pytest.mark.asyncio
async def test_seed_weekend_admin_manual_without_wiping_live(db_session, seed_city_id) -> None:
    arena_id = await _arena(db_session, seed_city_id)
    await _profile(db_session, arena_id, seed_city_id)
    live_start = datetime.combine(date(2026, 11, 6), time(18, 0), tzinfo=_MINSK).astimezone(timezone.utc)
    live_end = live_start + timedelta(minutes=45)
    await db_session.execute(
        text(
            """
            INSERT INTO ice_sessions (
                arena_id, kind, starts_at_utc, ends_at_utc, local_date, starts_at_local, ends_at_local,
                price_adult_minor, price_minor, currency_code, status, source_id, schedule_basis,
                external_url, observed_at
            ) VALUES (
                :a, 'public_skate', :s, :e, '2026-11-06', '18:00', '18:45',
                900, 900, 'BYN', 'active', 'abws:weekday', 'live',
                'https://saleframe.minskarena.by/service/139', :obs
            )
            """
        ),
        {"a": arena_id, "s": live_start, "e": live_end, "obs": _NOW},
    )
    await db_session.commit()

    spec = {**_SPEC, "arena_id": arena_id}
    counts = await upsert_admin_announced_sessions(db_session, spec)
    await db_session.commit()
    assert counts["inserted"] == 7
    assert counts["skipped_live"] == 0

    rows = (
        await db_session.execute(
            text(
                """
                SELECT local_date::text, starts_at_local::text, source_id, schedule_basis, external_url,
                       price_adult_minor, price_child_minor, price_rental_minor, hall
                FROM ice_sessions WHERE arena_id = :a ORDER BY local_date, starts_at_local
                """
            ),
            {"a": arena_id},
        )
    ).mappings().all()
    assert len(rows) == 8
    live = rows[0]
    assert live["local_date"] == "2026-11-06"
    assert live["source_id"] == "abws:weekday"
    assert live["schedule_basis"] == "live"
    assert live["external_url"] == "https://saleframe.minskarena.by/service/139"

    weekend = [r for r in rows if r["local_date"] in ("2026-11-07", "2026-11-08")]
    assert len(weekend) == 7
    assert all(r["source_id"] == "admin" for r in weekend)
    assert all(r["schedule_basis"] == "manual" for r in weekend)
    assert all(r["external_url"] is None for r in weekend)
    assert all(r["price_adult_minor"] == 900 for r in weekend)
    assert all(r["price_child_minor"] == 650 for r in weekend)
    assert all(r["price_rental_minor"] == 650 for r in weekend)
    assert all(r["hall"] == "Конькобежная дорожка" for r in weekend)


@pytest.mark.asyncio
async def test_parser_adopt_flips_manual_admin_to_live_buy(db_session, seed_city_id) -> None:
    arena_id = await _arena(db_session, seed_city_id)
    await _profile(db_session, arena_id, seed_city_id)
    spec = {
        "arena_id": arena_id,
        "defaults": {
            "kind": "public_skate",
            "duration_minutes": 45,
            "price_adult": "9.00",
            "price_child": "6.50",
            "price_rental": "6.50",
            "hall": "Конькобежная дорожка",
        },
        "sessions": [{"date": "2026-11-07", "start": "15:00"}],
    }
    await upsert_admin_announced_sessions(db_session, spec)
    await db_session.commit()

    job_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs
                        (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                    VALUES (:a, 'minskarena_speed_oval_v1', true, 'daily', :n, '{}'::jsonb)
                    RETURNING id
                    """
                ),
                {"a": arena_id, "n": _NOW},
            )
        ).scalar_one()
    )
    starts = datetime.combine(date(2026, 11, 7), time(15, 0), tzinfo=_MINSK).astimezone(timezone.utc)
    ends = starts + timedelta(minutes=45)
    draft = CanonicalSlotDraft(
        arena_id=arena_id,
        kind="public_skate",
        starts_at_utc=starts,
        ends_at_utc=ends,
        local_date=date(2026, 11, 7),
        starts_at_local=time(15, 0),
        ends_at_local=time(15, 45),
        price_adult_minor=900,
        price_child_minor=650,
        price_rental_minor=650,
        currency_code="BYN",
        status="active",
        observed_at=_NOW,
        valid_until=ends,
        source_id="abws:event-1",
        schedule_basis="live",
        external_url="https://saleframe.minskarena.by/service/139",
        hall="Конькобежная дорожка",
    )
    run = ScrapeRunRecord(
        job_id=job_id,
        arena_id=arena_id,
        parser_key="minskarena_speed_oval_v1",
        status=RUN_STATUS_OK,
        slot_count=1,
        slots_dropped=0,
        error_message=None,
        started_at=_NOW - timedelta(seconds=10),
        finished_at=_NOW,
        publish_horizon_days=14,
        publish_timezone="Europe/Minsk",
    )
    run_id = await SqlAlchemyScrapeRunRecorder(db_session).record(run)
    published = await SqlAlchemyIceSessionPublisher(db_session).publish(run, [draft], run_id=run_id)
    await db_session.commit()
    assert published == 1

    row = (
        await db_session.execute(
            text(
                """
                SELECT id, source_id, schedule_basis, external_url, price_adult_minor
                FROM ice_sessions WHERE arena_id = :a
                """
            ),
            {"a": arena_id},
        )
    ).mappings().one()
    assert row["source_id"] == "admin"
    assert row["schedule_basis"] == "live"
    assert row["external_url"] == "https://saleframe.minskarena.by/service/139"
    assert row["price_adult_minor"] == 900
