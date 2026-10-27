"""Publish a hand-entered schedule (a ``data/manual-schedules/*.json`` spec) through the ingest pipeline.

Shared by ``scripts/load_manual_schedule.py`` and the admin inbox «Опубликовать» button, so both
go through the same normalizer → validator → publisher as parsed sources (TTL, diff and watch
delivery behave identically). A non-empty run replaces the arena's future sessions except
``admin`` / ``etalon_*``; an empty spec erases nothing.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

from src.ingestion.manual_schedule_v1 import PARSER_KEY_MANUAL_SCHEDULE
from src.ingestion.parsers import IceParser, ParserRegistry
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob


class SpecError(ValueError):
    """The spec cannot become sessions (bad shape, time or date)."""


class PublishBusyError(RuntimeError):
    """The ingest scheduler holds the lock; try again in a minute."""


def _hhmm(value: Any) -> datetime:
    try:
        return datetime.strptime(str(value), "%H:%M")
    except ValueError as exc:
        raise SpecError(f"Неверное время: {value!r}") from exc


def slots_from_spec(spec: dict) -> list[ExtractedSlot]:
    sessions = spec.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise SpecError("В расписании нет сеансов")
    defaults = spec.get("defaults") or {}
    slots: list[ExtractedSlot] = []
    for row in sessions:
        merged = {**defaults, **row}
        for key in ("date", "start"):
            if not merged.get(key):
                raise SpecError(f"У сеанса нет поля {key}")
        try:
            datetime.strptime(str(merged["date"]), "%Y-%m-%d")
        except ValueError as exc:
            raise SpecError(f"Неверная дата: {merged['date']!r}") from exc
        start = _hhmm(merged["start"])
        end = start + timedelta(minutes=int(merged.get("duration_minutes") or 45))
        slots.append(
            ExtractedSlot(
                local_date=merged["date"],
                starts_at_local=merged["start"],
                ends_at_local=end.strftime("%H:%M"),
                kind_raw=merged.get("kind", "public_skate"),
                price_adult=merged.get("price_adult"),
                price_child=merged.get("price_child"),
                price_rental=merged.get("price_rental"),
                session_label=merged.get("label"),
                age_note=merged.get("age_note"),
                capacity_note=merged.get("capacity_note"),
                external_url=merged.get("external_url"),
            )
        )
    return slots


class SpecParser(IceParser):
    parser_key = PARSER_KEY_MANUAL_SCHEDULE

    def __init__(self, slots: list[ExtractedSlot], source: str) -> None:
        self._slots = slots
        self._source = source

    async def extract(self, job: ParserJob) -> Extraction:
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"source": "manual", "note": self._source},
            slots=list(self._slots),
            observed_at=datetime.now(timezone.utc),
        )


def preview_spec(spec: dict) -> list[Any]:
    """Normalize without a database: the drafts that would be published."""
    from src.ingestion.normalize import IceSessionNormalizer

    job = ParserJob(
        id=0, arena_id=int(spec["arena_id"]), parser_key=PARSER_KEY_MANUAL_SCHEDULE, is_enabled=True,
        cadence="weekly", next_run_at=datetime.now(timezone.utc), last_run_at=None,
        config={"kind": "public_skate", "timezone": "Europe/Minsk"}, notes=None, arena_timezone="Europe/Minsk",
    )
    extraction = Extraction(
        arena_id=job.arena_id, parser_key=PARSER_KEY_MANUAL_SCHEDULE, snapshot={"source": "manual"},
        slots=slots_from_spec(spec), observed_at=datetime.now(timezone.utc),
    )
    drafts, _report = IceSessionNormalizer().normalize_with_report(extraction, job, now=datetime.now(timezone.utc))
    return drafts


async def publish_spec(spec: dict) -> list[Any]:
    """Run the arena's enabled ``manual_schedule_v1`` job with the spec's sessions. Returns run records."""
    from sqlalchemy import text

    from src.application.schedule_waves import parser_wave_recorder
    from src.infrastructure.db.session import async_session_factory, engine
    from src.ingestion.jobs import SqlAlchemyParserJobStore
    from src.ingestion.publish import SqlAlchemyIceSessionPublisher
    from src.ingestion.scheduler import IceIngestScheduler
    from src.ingestion.scheduler_lock import run_with_ice_ingest_lock
    from src.ingestion.scrape_runs import SqlAlchemyScrapeRunRecorder

    arena_id = int(spec["arena_id"])
    registry = ParserRegistry()
    registry.register(SpecParser(slots_from_spec(spec), str(spec.get("source", ""))))

    class _OneArenaStore(SqlAlchemyParserJobStore):
        async def list_due(self, now):  # only this arena's manual job, never the rest
            return [j for j in await super().list_due(now) if j.arena_id == arena_id]

    async def run():
        async with async_session_factory() as session:
            now = datetime.now(timezone.utc)
            res = await session.execute(
                text(
                    "UPDATE ice_parser_jobs SET next_run_at = :now "
                    "WHERE arena_id = :a AND parser_key = :k AND is_enabled = true"
                ),
                {"now": now, "a": arena_id, "k": PARSER_KEY_MANUAL_SCHEDULE},
            )
            if res.rowcount != 1:
                raise SpecError(f"У катка {arena_id} нет включённого задания {PARSER_KEY_MANUAL_SCHEDULE}")
            await session.commit()
            scheduler = IceIngestScheduler(
                store=_OneArenaStore(session),
                recorder=SqlAlchemyScrapeRunRecorder(session),
                registry=registry,
                publisher=SqlAlchemyIceSessionPublisher(session),
                checkpoint=session.commit,
                job_savepoint=session.begin_nested,
                schedule_wave_recorder=parser_wave_recorder(async_session_factory),
                max_jobs_per_tick=None,
                tick_budget_s=None,
            )
            outcomes = await scheduler.run_due(now)
            await session.commit()
            return outcomes

    acquired, outcomes = await run_with_ice_ingest_lock(engine, run)
    if not acquired:
        raise PublishBusyError("Планировщик расписаний сейчас работает")
    return outcomes
