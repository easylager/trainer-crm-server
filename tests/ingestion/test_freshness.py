"""TASK-146: каденс опроса, бэкофф, состояние источника и флаг schedule_stale."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.ingestion.freshness import (
    BLOCKED_RETRY_MINUTES,
    DAY_POLL_MINUTES,
    ERROR_CODE_EMPTY_AFTER_FILTER,
    ERROR_CODE_EMPTY_AFTER_SLOTS,
    ERROR_CODE_EMPTY_SOURCE,
    MINSK_TZ,
    NIGHT_POLL_MINUTES,
    failure_retry_interval,
    is_schedule_stale,
    next_poll_at,
    next_source_state,
    schedule_freshness_fields,
)
from src.ingestion.jobs import InMemoryParserJobStore, SqlAlchemyParserJobStore
from src.ingestion.parsers import IceParser, ParserRegistry
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import InMemoryScrapeRunRecorder
from src.ingestion.types import (
    RUN_STATUS_BLOCKED,
    RUN_STATUS_EMPTY,
    RUN_STATUS_ERROR,
    RUN_STATUS_OK,
    ExtractedSlot,
    Extraction,
    ParserJob,
    ScrapeRunRecord,
    SourceState,
)

# 13:00 по Минску — день.
_NOW = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


class _NoJitter:
    def uniform(self, a: float, b: float) -> float:
        return 0.0


class _LowestJitter:
    def uniform(self, a: float, b: float) -> float:
        return a


def _record(status: str, *, at: datetime = _NOW, slots: int = 0, code: str | None = None) -> ScrapeRunRecord:
    return ScrapeRunRecord(
        job_id=1,
        arena_id=100,
        parser_key="p_v1",
        status=status,
        slot_count=slots,
        slots_dropped=0,
        error_message="boom" if status == RUN_STATUS_ERROR else None,
        started_at=at,
        finished_at=at,
        error_code=code,
    )


def _poll(status: str, *, now: datetime = _NOW, streak: int = 0, config: dict | None = None, job_id: int = 1):
    return next_poll_at(
        job_id=job_id,
        config=config or {},
        status=status,
        state=SourceState(failure_streak=streak),
        now=now,
        rng=_NoJitter(),
    )


# ── Каденс опроса ────────────────────────────────────────────────────────


def test_daytime_poll_is_45_minutes_regardless_of_cadence() -> None:
    assert _poll(RUN_STATUS_OK) == _NOW + timedelta(minutes=DAY_POLL_MINUTES)
    assert _poll(RUN_STATUS_EMPTY) == _NOW + timedelta(minutes=DAY_POLL_MINUTES)


def test_night_poll_is_sparser_but_morning_refresh_is_guaranteed() -> None:
    # 01:00 по Минску: 120 минут — до 03:00, утро ещё далеко.
    night = datetime(2026, 10, 1, 1, 0, tzinfo=MINSK_TZ).astimezone(timezone.utc)
    assert _poll(RUN_STATUS_OK, now=night) == night + timedelta(minutes=NIGHT_POLL_MINUTES)
    # 06:00 по Минску: +120 = 08:00, но источник должен быть перечитан к 07:00–07:30.
    early = datetime(2026, 10, 1, 6, 0, tzinfo=MINSK_TZ).astimezone(timezone.utc)
    nxt = _poll(RUN_STATUS_OK, now=early, job_id=7).astimezone(MINSK_TZ)
    assert (nxt.hour, nxt.minute) == (7, 7)
    # 23:30 по Минску — уже ночь, следующий прогон до утра.
    late = datetime(2026, 10, 1, 23, 30, tzinfo=MINSK_TZ).astimezone(timezone.utc)
    assert _poll(RUN_STATUS_OK, now=late) == late + timedelta(minutes=NIGHT_POLL_MINUTES)


def test_error_backoff_doubles_up_to_three_hours() -> None:
    got = [failure_retry_interval(n).total_seconds() / 60 for n in range(1, 8)]
    assert got == [15, 30, 60, 120, 180, 180, 180]
    assert _poll(RUN_STATUS_ERROR, streak=1) == _NOW + timedelta(minutes=15)
    assert _poll(RUN_STATUS_ERROR, streak=3) == _NOW + timedelta(minutes=60)


def test_blocked_retries_every_six_hours() -> None:
    assert _poll(RUN_STATUS_BLOCKED, streak=1) == _NOW + timedelta(minutes=BLOCKED_RETRY_MINUTES)


def test_manual_poll_minutes_is_respected_for_polite_sources() -> None:
    cfg = {"poll_minutes": 240}
    assert _poll(RUN_STATUS_OK, config=cfg) == _NOW + timedelta(minutes=240)
    # Ошибка не повторяется чаще, чем сайт разрешил.
    assert _poll(RUN_STATUS_ERROR, streak=1, config=cfg) == _NOW + timedelta(minutes=240)


def test_manual_poll_minimum_is_not_reduced_by_lowest_jitter_on_error_retry() -> None:
    manual_minutes = 240
    nxt = next_poll_at(
        job_id=1,
        config={"poll_minutes": manual_minutes},
        status=RUN_STATUS_ERROR,
        state=SourceState(failure_streak=1),
        now=_NOW,
        rng=_LowestJitter(),
    )

    assert nxt >= _NOW + timedelta(minutes=manual_minutes)


def test_jitter_stays_within_fifteen_percent() -> None:
    import random

    rng = random.Random(42)
    for _ in range(200):
        nxt = next_poll_at(
            job_id=1, config={}, status=RUN_STATUS_OK, state=SourceState(), now=_NOW, rng=rng
        )
        delta = (nxt - _NOW).total_seconds() / 60
        assert DAY_POLL_MINUTES * 0.85 <= delta <= DAY_POLL_MINUTES * 1.15


# ── Состояние источника ──────────────────────────────────────────────────


def test_ok_resets_failure_streak_and_moves_last_ok() -> None:
    failing = SourceState(failing_since=_NOW - timedelta(hours=2), failure_streak=3, last_error_code="x")
    st = next_source_state(failing, _record(RUN_STATUS_OK, slots=12), shown_sessions=0)
    assert st.last_ok_at == _NOW
    assert st.last_ok_slot_count == 12
    assert st.failure_streak == 0
    assert st.failing_since is None
    assert st.last_error_code is None


def test_error_extends_streak_and_keeps_first_failure_time() -> None:
    first = _NOW - timedelta(minutes=30)
    st = next_source_state(SourceState(), _record(RUN_STATUS_ERROR, at=first, code="extract_error"), shown_sessions=5)
    assert (st.failure_streak, st.failing_since, st.last_error_code) == (1, first, "extract_error")
    st = next_source_state(st, _record(RUN_STATUS_ERROR, code="extract_error"), shown_sessions=5)
    assert (st.failure_streak, st.failing_since) == (2, first)


def test_empty_is_failure_only_while_old_sessions_are_shown() -> None:
    prev = SourceState(last_ok_at=_NOW - timedelta(hours=1), last_ok_slot_count=10)
    st = next_source_state(prev, _record(RUN_STATUS_EMPTY), shown_sessions=8)
    assert st.failure_streak == 1
    assert st.last_error_code == ERROR_CODE_EMPTY_AFTER_SLOTS
    assert "8" in (st.last_error_summary or "")
    # Витрина опустела (старые сеансы истекли): пустой прогон — не новый сбой, но и не
    # выздоровление (TASK-178). Серия остаётся, last_ok_at не двигается.
    st2 = next_source_state(st, _record(RUN_STATUS_EMPTY), shown_sessions=0)
    assert st2.failure_streak == 1
    assert st2.failing_since == st.failing_since
    assert st2.last_ok_at == prev.last_ok_at
    assert st2.last_error_code == ERROR_CODE_EMPTY_SOURCE


def test_empty_on_empty_storefront_never_resets_an_error_series() -> None:
    """TASK-178 п.1: error, error → потом пусто при пустой витрине — серия не обнуляется."""
    st = SourceState(last_ok_at=_NOW - timedelta(days=2))
    for _ in range(3):
        st = next_source_state(st, _record(RUN_STATUS_ERROR, code="extract_error"), shown_sessions=4)
    assert st.failure_streak == 3
    for _ in range(5):
        st = next_source_state(st, _record(RUN_STATUS_EMPTY), shown_sessions=0)
    assert st.failure_streak == 3
    assert st.failing_since is not None
    assert st.last_ok_at == _NOW - timedelta(days=2)


def test_empty_reason_code_is_kept_from_the_run() -> None:
    rec = replace(
        _record(RUN_STATUS_EMPTY),
        error_code=ERROR_CODE_EMPTY_AFTER_FILTER,
        slots_dropped=16,
        error_message="извлечено 16, опубликовано 0: в прошлом 16",
    )
    st = next_source_state(SourceState(), rec, shown_sessions=0)
    assert st.failure_streak == 0
    assert st.last_error_code == ERROR_CODE_EMPTY_AFTER_FILTER
    assert "в прошлом 16" in (st.last_error_summary or "")
    # Если же у нас ещё висят сеансы, это сбой «источник перестал их подтверждать».
    st = next_source_state(SourceState(), rec, shown_sessions=3)
    assert st.failure_streak == 1
    assert st.last_error_code == ERROR_CODE_EMPTY_AFTER_SLOTS
    assert "в прошлом 16" in (st.last_error_summary or "")


# ── Флаг устаревания для публичного API ──────────────────────────────────


def test_schedule_stale_flag() -> None:
    assert not is_schedule_stale(has_enabled_job=False, last_ok_at=None, config={}, now=_NOW)
    assert not is_schedule_stale(
        has_enabled_job=True, last_ok_at=_NOW - timedelta(hours=1), config={}, now=_NOW
    )
    assert is_schedule_stale(
        has_enabled_job=True, last_ok_at=_NOW - timedelta(hours=7), config={}, now=_NOW
    )
    assert not is_schedule_stale(
        has_enabled_job=True,
        last_ok_at=_NOW - timedelta(hours=7),
        config={"stale_after_hours": 24},
        now=_NOW,
    )
    # Новый источник ещё ни разу не прочитан — не «устаревший» с первой минуты.
    assert not is_schedule_stale(
        has_enabled_job=True, last_ok_at=None, config={}, now=_NOW, created_at=_NOW - timedelta(hours=1)
    )
    # Свежие сеансы в БД важнее старого last_ok парсера.
    assert not is_schedule_stale(
        has_enabled_job=True,
        last_ok_at=_NOW - timedelta(hours=7),
        sessions_observed_at=_NOW - timedelta(hours=1),
        config={},
        now=_NOW,
    )


def test_schedule_freshness_fields_prefers_latest_confirmation() -> None:
    fields = schedule_freshness_fields(
        has_enabled_job=True,
        last_ok_at=_NOW - timedelta(minutes=20),
        sessions_observed_at=_NOW - timedelta(days=2),
        config={},
        now=_NOW,
    )
    assert fields == {
        "schedule_observed_at": (_NOW - timedelta(minutes=20)).isoformat(),
        "schedule_auto": True,
        "schedule_stale": False,
    }
    manual = schedule_freshness_fields(
        has_enabled_job=False, last_ok_at=None, sessions_observed_at=None, config=None, now=_NOW
    )
    assert manual == {"schedule_observed_at": None, "schedule_auto": False, "schedule_stale": False}


# ── Планировщик ──────────────────────────────────────────────────────────


class _ScriptedParser(IceParser):
    """Отдаёт заранее заданную последовательность исходов: 'raise' | 'empty' | 'ok'."""

    parser_key = "scripted_v1"

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)

    async def extract(self, job: ParserJob) -> Extraction:
        step = self.script.pop(0)
        if step == "raise":
            raise RuntimeError("site layout changed")
        slots = []
        if step == "past":
            slots = [
                ExtractedSlot(
                    local_date="2026-09-29",
                    starts_at_local=f"{10 + i}:00",
                    ends_at_local=f"{10 + i}:45",
                    kind_raw="Массовое катание",
                )
                for i in range(3)
            ] + [
                ExtractedSlot(local_date="2026-10-03", starts_at_local="12:00", kind_raw="хоккей"),
            ]
        if step == "ok":
            slots = [
                ExtractedSlot(
                    local_date="2026-10-03",
                    starts_at_local="12:00",
                    ends_at_local="13:00",
                    kind_raw="Массовое катание",
                    price_adult=1000,
                )
            ]
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot={}, slots=slots)


def _job(**overrides) -> ParserJob:
    base = ParserJob(
        id=1,
        arena_id=100,
        parser_key=_ScriptedParser.parser_key,
        is_enabled=True,
        cadence="weekly",
        next_run_at=_NOW - timedelta(minutes=1),
        last_run_at=None,
        config={"prices_already_minor": True},
    )
    return replace(base, **overrides)


def _sched(store, parser, **kwargs) -> IceIngestScheduler:
    registry = ParserRegistry()
    registry.register(parser)
    return IceIngestScheduler(
        store=store, recorder=InMemoryScrapeRunRecorder(), registry=registry, rng=_NoJitter(), **kwargs
    )


async def _run_at(sched, store, at: datetime) -> None:
    job = store.get(1)
    store._jobs[1] = replace(job, next_run_at=at - timedelta(seconds=1))
    await sched.run_due(at)


@pytest.mark.asyncio
async def test_scheduler_tracks_failure_series_and_recovery() -> None:
    store = InMemoryParserJobStore([_job()])
    sched = _sched(store, _ScriptedParser(["raise", "raise", "ok"]))
    t1, t2, t3 = _NOW, _NOW + timedelta(minutes=15), _NOW + timedelta(minutes=45)

    await _run_at(sched, store, t1)
    st = store.get(1).state
    assert (st.failure_streak, st.failing_since, st.last_error_code) == (1, t1, "extract_error")
    assert store.get(1).next_run_at == t1 + timedelta(minutes=15)

    await _run_at(sched, store, t2)
    st = store.get(1).state
    assert (st.failure_streak, st.failing_since) == (2, t1)
    assert store.get(1).next_run_at == t2 + timedelta(minutes=30)

    await _run_at(sched, store, t3)
    st = store.get(1).state
    assert st.failure_streak == 0
    assert st.last_ok_at == t3
    assert st.last_ok_slot_count == 1
    assert store.get(1).next_run_at == t3 + timedelta(minutes=DAY_POLL_MINUTES)


@pytest.mark.asyncio
async def test_scheduler_flags_zero_slots_when_old_sessions_still_shown() -> None:
    store = InMemoryParserJobStore([_job()], shown_sessions={100: 6})
    sched = _sched(store, _ScriptedParser(["empty"]))
    await sched.run_due(_NOW)
    st = store.get(1).state
    assert st.failure_streak == 1
    assert st.last_error_code == ERROR_CODE_EMPTY_AFTER_SLOTS


@pytest.mark.asyncio
async def test_scheduler_says_where_slots_were_lost() -> None:
    """TASK-178 п.4: empty отличает «источник пуст» от «мы всё отбросили»."""
    store = InMemoryParserJobStore([_job()])
    recorder = InMemoryScrapeRunRecorder()
    registry = ParserRegistry()
    registry.register(_ScriptedParser(["past", "empty"]))
    sched = IceIngestScheduler(store=store, recorder=recorder, registry=registry, rng=_NoJitter())

    await _run_at(sched, store, _NOW)
    await _run_at(sched, store, _NOW + timedelta(minutes=45))

    filtered, empty = recorder.runs
    assert filtered.status == RUN_STATUS_EMPTY
    assert filtered.error_code == ERROR_CODE_EMPTY_AFTER_FILTER
    assert (filtered.slot_count, filtered.slots_dropped) == (0, 4)
    assert filtered.error_message == "извлечено 4, опубликовано 0: в прошлом 3, неизвестный вид 1"
    assert empty.status == RUN_STATUS_EMPTY
    assert empty.error_code == ERROR_CODE_EMPTY_SOURCE
    assert (empty.slot_count, empty.slots_dropped) == (0, 0)
    assert store.get(1).state.last_error_code == ERROR_CODE_EMPTY_SOURCE


def test_normalize_report_counts_every_dropped_slot() -> None:
    from src.ingestion.normalize import IceSessionNormalizer

    extraction = Extraction(
        arena_id=100,
        parser_key="p_v1",
        snapshot=None,
        slots=[
            ExtractedSlot(local_date="2026-09-30", starts_at_local="18:00", kind_raw="Массовое катание"),
            ExtractedSlot(local_date="2026-10-02", starts_at_local="18:00", kind_raw="Массовое катание"),
            ExtractedSlot(local_date="2026-10-02", starts_at_local="18:00", kind_raw="Массовое катание"),
            ExtractedSlot(local_date="2026-10-02", starts_at_local="20:00", kind_raw="тренировка"),
        ],
    )
    drafts, report = IceSessionNormalizer().normalize_with_report(extraction, _job(), now=_NOW)
    assert len(drafts) == 1
    assert (report.extracted, report.published, report.dropped) == (4, 1, 3)
    assert (report.past, report.merged_duplicates, report.unknown_kind) == (1, 1, 1)
    assert IceSessionNormalizer().normalize(extraction, _job(), now=_NOW) == drafts


@pytest.mark.asyncio
async def test_scheduler_caps_jobs_per_tick_and_commits_each_job() -> None:
    jobs = [_job(id=i, arena_id=100 + i) for i in range(1, 6)]
    store = InMemoryParserJobStore(jobs)
    commits: list[int] = []

    async def checkpoint() -> None:
        commits.append(1)

    sched = _sched(store, _ScriptedParser(["ok"] * 5), max_jobs_per_tick=3, checkpoint=checkpoint)
    outcomes = await sched.run_due(_NOW)
    assert len(outcomes) == 3
    assert len(commits) == 3
    still_due = await store.list_due(_NOW)
    assert [j.id for j in still_due] == [4, 5]


# ── SQL-хранилище: состояние переживает прогон ──────────────────────────


async def _arena(db_session) -> int:
    city = (
        await db_session.execute(
            text(
                "INSERT INTO cities (name, country, price_group, is_active, sort_order) "
                "VALUES ('FreshCity', 'BY', 'BY_BASE', true, 9200) RETURNING id"
            )
        )
    ).scalar_one()
    return int(
        (
            await db_session.execute(
                text(
                    "INSERT INTO arenas (city_id, name, address, is_active, is_confirmed) "
                    "VALUES (:cid, 'Fresh Arena', 'ул. 1', true, true) RETURNING id"
                ),
                {"cid": city},
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_sql_store_persists_state_and_counts_only_parser_sessions(db_session) -> None:
    arena_id = await _arena(db_session)
    job_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                    VALUES (:aid, 'scripted_v1', true, 'weekly', :due, CAST(:cfg AS jsonb))
                    RETURNING id
                    """
                ),
                {"aid": arena_id, "due": _NOW - timedelta(minutes=1), "cfg": json.dumps({})},
            )
        ).scalar_one()
    )
    for source_id in ("run:1:12:00", "admin"):
        await db_session.execute(
            text(
                """
                INSERT INTO ice_sessions (arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                    starts_at_local, ends_at_local, currency_code, status, source_id, observed_at)
                VALUES (:aid, 'public_skate', :s, :e, :d, '12:00', '13:00', 'BYN', 'active', :sid, :obs)
                """
            ),
            {
                "aid": arena_id,
                "s": _NOW + timedelta(days=1),
                "e": _NOW + timedelta(days=1, hours=1),
                "d": (_NOW + timedelta(days=1)).date(),
                "sid": source_id,
                "obs": _NOW,
            },
        )
    store = SqlAlchemyParserJobStore(db_session)
    assert await store.count_shown_sessions(arena_id, _NOW) == 1

    sched = _sched(store, _ScriptedParser(["raise"]))
    await sched.run_due(_NOW)
    row = (
        await db_session.execute(
            text(
                "SELECT failure_streak, failing_since, last_error_code, next_run_at, alert_state "
                "FROM ice_parser_jobs WHERE id = :id"
            ),
            {"id": job_id},
        )
    ).one()
    assert row.failure_streak == 1
    assert row.failing_since == _NOW
    assert row.last_error_code == "extract_error"
    assert row.next_run_at == _NOW + timedelta(minutes=15)
    assert row.alert_state == "ok"  # алертные поля ведёт только тик алертов

    [job] = [j for j in await store.list_due(_NOW + timedelta(minutes=16)) if j.id == job_id]
    assert job.state.failure_streak == 1
    assert job.state.failing_since == _NOW
