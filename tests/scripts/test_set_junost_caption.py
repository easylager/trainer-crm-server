"""Тесты scripts/set_junost_caption.py: разбор поста без БД, запись — на тестовой БД."""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from scripts import set_junost_caption as script
from tests.api.test_public_arenas import _insert_arena, _insert_city

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data/fixtures/minsk-junost/instagram-caption-latest.txt"

EXAMPLE_CAPTION = (
    "11 ОКТЯБРЯ ВОСКРЕСЕНЬЕ\n"
    "17:00-17:45\n"
    "18:15-19:00\n"
    "СТОИМОСТЬ БИЛЕТА:\n"
    "ВЗРОСЛЫЙ - 8р.\n"
    "ДЕТСКИЙ - 6р.\n"
    "УЛ. ПЕРВОМАЙСКАЯ 3,\n"
    "КРЫТЫЙ КАТОК (ПАРК ИМ. М.ГОРЬКОГО)\n"
)

# «Сегодня» в тестах фиксируем, чтобы даты постов не устаревали.
TODAY = date(2026, 10, 6)


# --- разбор текста (без БД) -------------------------------------------------


def test_example_caption_parses_two_sessions_with_prices() -> None:
    plan = script.build_plan(EXAMPLE_CAPTION, today=TODAY)

    assert len(plan.sessions) == 2
    first, second = plan.sessions
    assert first.local_date == date(2026, 10, 11)
    assert (first.starts_at_local, first.ends_at_local) == ("17:00", "17:45")
    assert (second.starts_at_local, second.ends_at_local) == ("18:15", "19:00")
    assert first.adult_minor == 800
    assert first.child_minor == 600
    assert first.rental_minor is None
    assert len(plan.future_sessions) == 2


def test_previous_fixture_caption_parses() -> None:
    plan = script.build_plan(FIXTURE.read_text(encoding="utf-8"), today=date(2026, 10, 1))

    assert [session.local_date for session in plan.sessions] == [date(2026, 10, 4), date(2026, 10, 4)]
    assert plan.sessions[0].adult_minor == 800
    assert plan.sessions[0].child_minor == 600
    assert plan.sessions[0].rental_minor == 700


def test_caption_without_date_or_time_raises_and_never_touches_db(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("БД не должна открываться, когда текст не разобрался")

    monkeypatch.setattr(script, "create_async_engine", _boom)

    with pytest.raises(script.CaptionError):
        asyncio.run(
            script.run(
                caption="Привет! Просто текст без расписания и цен.",
                apply=True,
                i_know_this_is_prod=False,
                today=TODAY,
            )
        )


def test_all_past_dates_raises() -> None:
    with pytest.raises(script.CaptionError, match="уже прошли"):
        script.build_plan(EXAMPLE_CAPTION, today=date(2026, 10, 12))


# --- dry-run: ничего не пишет -----------------------------------------------


class _Result:
    def __init__(self, row: tuple | None = None) -> None:
        self._row = row

    def fetchone(self) -> tuple | None:
        return self._row


class _Engine:
    async def dispose(self) -> None:
        return None


class _Session:
    """Фейковая сессия: помнит запросы и запрещает любой UPDATE."""

    def __init__(self, parser_key: str = script.PARSER_KEY) -> None:
        self.parser_key = parser_key
        self.queries: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, query: object, _params: dict | None = None) -> _Result:
        sql = str(query)
        self.queries.append(sql)
        if "FROM ice_parser_jobs" in sql:
            return _Result((script.JOB_ID, self.parser_key, {}))
        if "UPDATE" in sql:
            raise AssertionError("dry-run не должен писать")
        return _Result()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _patch_run_dependencies(monkeypatch: pytest.MonkeyPatch, session: _Session) -> None:
    monkeypatch.setattr(script, "_db_url", lambda: "postgresql://localhost/trainer_crm_test")
    monkeypatch.setattr(script, "create_async_engine", lambda *_args, **_kwargs: _Engine())
    monkeypatch.setattr(script, "async_sessionmaker", lambda *_args, **_kwargs: lambda: session)


def test_dry_run_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    _patch_run_dependencies(monkeypatch, session)

    asyncio.run(
        script.run(caption=EXAMPLE_CAPTION, apply=False, i_know_this_is_prod=False, today=TODAY)
    )

    assert session.commits == 0
    assert session.rollbacks == 1
    assert not any("UPDATE" in sql for sql in session.queries)


# --- запись на своей тестовой БД --------------------------------------------


async def _upsert_job(db_session, arena_id: int, *, parser_key: str = script.PARSER_KEY) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO ice_parser_jobs (id, arena_id, parser_key, is_enabled, cadence, next_run_at, config)
            VALUES (:id, :aid, :pk, true, 'weekly', now() - interval '1 day', '{}'::jsonb)
            ON CONFLICT (id) DO UPDATE
            SET arena_id = EXCLUDED.arena_id,
                parser_key = EXCLUDED.parser_key,
                is_enabled = true,
                config = '{}'::jsonb
            """
        ),
        {"id": script.JOB_ID, "aid": arena_id, "pk": parser_key},
    )
    await db_session.flush()


async def _new_arena(db_session) -> int:
    city_id = await _insert_city(db_session, name=f"Юность-{uuid.uuid4().hex[:6]}")
    return await _insert_arena(db_session, city_id, name=f"Каток ХК Юность {uuid.uuid4().hex[:6]}")


@pytest.mark.asyncio
async def test_apply_updates_caption_and_next_run_at(app_use_test_db, db_session) -> None:
    arena_id = await _new_arena(db_session)
    await _upsert_job(db_session, arena_id)
    stamp = datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc)

    await script.write_caption(db_session, caption=EXAMPLE_CAPTION, now=stamp)
    await db_session.flush()

    row = (
        await db_session.execute(
            text("SELECT config->>'caption_text', next_run_at FROM ice_parser_jobs WHERE id = :id"),
            {"id": script.JOB_ID},
        )
    ).one()
    assert row[0] == EXAMPLE_CAPTION
    assert row[1] == stamp


@pytest.mark.asyncio
async def test_apply_refuses_wrong_parser_key(app_use_test_db, db_session) -> None:
    arena_id = await _new_arena(db_session)
    await _upsert_job(db_session, arena_id, parser_key="junost_origin_html_v1")

    with pytest.raises(script.CaptionError, match="parser_key"):
        await script.write_caption(
            db_session, caption=EXAMPLE_CAPTION, now=datetime(2026, 5, 1, tzinfo=timezone.utc)
        )

    stored = (
        await db_session.execute(
            text("SELECT config->>'caption_text' FROM ice_parser_jobs WHERE id = :id"),
            {"id": script.JOB_ID},
        )
    ).scalar_one()
    assert stored is None


def test_cloud_url_refused_without_prod_ack() -> None:
    from src.shared.ops_db_guard import ProdDatabaseError

    with pytest.raises(ProdDatabaseError):
        script.assert_database_url(
            "postgresql://u:p@x.proxy.rlwy.net.railway.app:5432/railway", apply=False, allow_prod=False
        )
