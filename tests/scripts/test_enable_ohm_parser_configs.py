"""TASK-201-A: enable_ohm_parser_configs.py — dry-run, apply, idempotent, scoped."""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from scripts.enable_ohm_parser_configs import (
    CHIZHOVKA_ARENA_ID,
    CHIZHOVKA_PARSER_KEY,
    DIAMOND_PARSER_KEY,
    OHM_SCHEDULE_URL,
    OhmConfigError,
    _load_job,
    apply_enable_ohm_configs,
    plan_patches,
)
from src.shared.config import Settings


def _sync_url() -> str:
    url = Settings().database_url_sync or Settings().database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    return url


def _insert_job(session: Session, *, arena_id: int, parser_key: str, config: dict) -> int:
    return int(
        session.execute(
            text(
                """
                INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                VALUES (:aid, :pkey, true, 'weekly', NOW(), CAST(:cfg AS jsonb))
                RETURNING id
                """
            ),
            {
                "aid": arena_id,
                "pkey": parser_key,
                "cfg": json.dumps(config, ensure_ascii=False),
            },
        ).scalar_one()
    )


def _ensure_arena(session: Session, arena_id: int) -> None:
    exists = session.execute(text("SELECT 1 FROM arenas WHERE id = :id"), {"id": arena_id}).scalar()
    if exists:
        return
    cid = int(
        session.execute(
            text(
                """
                INSERT INTO cities (name, country, price_group, is_active, sort_order)
                VALUES (:name, 'BY', 'BY_BASE', true, 9001)
                RETURNING id
                """
            ),
            {"name": f"OhmScript-{uuid.uuid4().hex[:8]}"},
        ).scalar_one()
    )
    session.execute(
        text(
            """
            INSERT INTO arenas (id, city_id, name, address, is_active, is_confirmed)
            VALUES (:id, :cid, 'Тестовый каток', 'ул. Тест, 1', true, true)
            """
        ),
        {"id": arena_id, "cid": cid},
    )


@pytest.fixture
def ohm_jobs_setup():
    engine = create_engine(_sync_url())
    with Session(engine) as session:
        trans = session.begin()
        try:
            _ensure_arena(session, 6)
            _ensure_arena(session, 7)
            cid = int(
                session.execute(
                    text("SELECT city_id FROM arenas WHERE id = 6 LIMIT 1"),
                ).scalar_one()
            )
            other_aid = int(
                session.execute(
                    text(
                        """
                        INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                        VALUES (:cid, 'Чужой каток', 'ул. Тест, 9', true, true)
                        RETURNING id
                        """
                    ),
                    {"cid": cid},
                ).scalar_one()
            )
            for aid, pkey in ((6, CHIZHOVKA_PARSER_KEY), (7, DIAMOND_PARSER_KEY)):
                session.execute(
                    text("DELETE FROM ice_parser_jobs WHERE arena_id = :aid AND parser_key = :pkey"),
                    {"aid": aid, "pkey": pkey},
                )
            other_job = _insert_job(
                session,
                arena_id=other_aid,
                parser_key="zamok_html_v1",
                config={"kind": "public_skate", "schedule_url": "https://example.test/"},
            )
            chiz_job = _insert_job(
                session,
                arena_id=6,
                parser_key=CHIZHOVKA_PARSER_KEY,
                config={
                    "schedule_url": "https://chizhovka-arena.by/fizkultura-i-sport/katanie-na-konkah",
                    "prices_url": "https://chizhovka-arena.by/czeny/katanie-na-konkah",
                },
            )
            diam_job = _insert_job(
                session,
                arena_id=7,
                parser_key=DIAMOND_PARSER_KEY,
                config={
                    "schedule_url": "https://diamondcity.by/ledovaya-arena",
                    "keep_labels": ["МК"],
                    "drop_labels": ["ОХМ", "ШРС"],
                },
            )
            session.flush()
            yield {
                "session": session,
                "other_job_id": other_job,
                "chiz_job_id": chiz_job,
                "diam_job_id": diam_job,
            }
        finally:
            trans.rollback()


def test_dry_run_does_not_write(ohm_jobs_setup) -> None:
    session = ohm_jobs_setup["session"]
    before_chiz = session.execute(
        text("SELECT config FROM ice_parser_jobs WHERE id = :id"),
        {"id": ohm_jobs_setup["chiz_job_id"]},
    ).scalar_one()
    patches = plan_patches(session)
    assert patches
    chiz_patch = next(p for p in patches if p.job.arena_id == CHIZHOVKA_ARENA_ID)
    assert "ohm_schedule_url" in chiz_patch.after
    after_chiz = session.execute(
        text("SELECT config FROM ice_parser_jobs WHERE id = :id"),
        {"id": ohm_jobs_setup["chiz_job_id"]},
    ).scalar_one()
    assert before_chiz == after_chiz


def test_apply_changes_only_ohm_keys(ohm_jobs_setup) -> None:
    session = ohm_jobs_setup["session"]
    other_before = dict(
        session.execute(
            text("SELECT config FROM ice_parser_jobs WHERE id = :id"),
            {"id": ohm_jobs_setup["other_job_id"]},
        ).scalar_one()
    )
    result = apply_enable_ohm_configs(session)
    assert result.applied == 2

    chiz_cfg = dict(
        session.execute(
            text("SELECT config FROM ice_parser_jobs WHERE id = :id"),
            {"id": ohm_jobs_setup["chiz_job_id"]},
        ).scalar_one()
    )
    assert chiz_cfg["ohm_schedule_url"] == OHM_SCHEDULE_URL
    assert chiz_cfg["schedule_url"].startswith("https://chizhovka")

    diam_cfg = dict(
        session.execute(
            text("SELECT config FROM ice_parser_jobs WHERE id = :id"),
            {"id": ohm_jobs_setup["diam_job_id"]},
        ).scalar_one()
    )
    assert "ОХМ" not in diam_cfg["drop_labels"]
    assert diam_cfg["ohm_labels"] == ["ОХМ"]
    assert diam_cfg["ohm_adult_minor"] == 1400
    assert diam_cfg["keep_labels"] == ["МК"]

    other_after = dict(
        session.execute(
            text("SELECT config FROM ice_parser_jobs WHERE id = :id"),
            {"id": ohm_jobs_setup["other_job_id"]},
        ).scalar_one()
    )
    assert other_before == other_after


def test_second_apply_is_noop(ohm_jobs_setup) -> None:
    session = ohm_jobs_setup["session"]
    apply_enable_ohm_configs(session)
    second = apply_enable_ohm_configs(session)
    assert second.applied == 0
    assert not second.patches


def test_missing_job_raises(ohm_jobs_setup) -> None:
    session = ohm_jobs_setup["session"]
    session.execute(
        text("DELETE FROM ice_parser_jobs WHERE id = :id"),
        {"id": ohm_jobs_setup["chiz_job_id"]},
    )
    with pytest.raises(OhmConfigError, match="no ice_parser_jobs row"):
        plan_patches(session)


def test_duplicate_job_raises() -> None:
    from unittest.mock import MagicMock

    class _Maps:
        def __init__(self, rows: list[dict]) -> None:
            self._rows = rows

        def mappings(self) -> _Maps:
            return self

        def all(self) -> list[dict]:
            return self._rows

    session = MagicMock()
    session.execute.return_value = _Maps(
        [
            {
                "id": 1,
                "arena_id": CHIZHOVKA_ARENA_ID,
                "parser_key": CHIZHOVKA_PARSER_KEY,
                "config": {},
            },
            {
                "id": 2,
                "arena_id": CHIZHOVKA_ARENA_ID,
                "parser_key": CHIZHOVKA_PARSER_KEY,
                "config": {},
            },
        ]
    )
    with pytest.raises(OhmConfigError, match="expected one job"):
        _load_job(session, arena_id=CHIZHOVKA_ARENA_ID, parser_key=CHIZHOVKA_PARSER_KEY)
