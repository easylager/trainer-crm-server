"""TASK-204: запуск scripts/set_arena_schedule_modes.py, а не только внутренние куски."""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from scripts import set_arena_schedule_modes as script
from tests.api.test_public_arenas import _insert_arena, _insert_city

TODAY = date(2026, 10, 6)


def test_silichi_spec_is_closure_note_without_reopen_date() -> None:
    assert len(script.SPECS) == 10
    spec = next(item for item in script.SPECS if item.arena_id == 16)
    assert spec.mode == script.SCHEDULE_MODE_SEASON_CLOSED
    assert spec.reopen_date is None
    assert spec.note == "закрыт с 25.03.2026"
    script.reject_past_reopen_dates(script.SPECS, today=TODAY)


def test_reopen_date_today_is_allowed() -> None:
    spec = script.ArenaModeSpec(
        16, script.SCHEDULE_MODE_SEASON_CLOSED, reopen_date=TODAY, note="откроется сегодня"
    )
    script.reject_past_reopen_dates((spec,), today=TODAY)


def test_main_dry_run_against_test_db(capsys: pytest.CaptureFixture[str]) -> None:
    code = script.main([])

    captured = capsys.readouterr()
    assert code == 0
    assert "Traceback" not in captured.err
    assert "Dry-run only (no writes)." in captured.out
    for spec in script.SPECS:
        assert f"#{spec.arena_id}" in captured.out


def test_missing_database_url_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)

    code = script.main([])

    err = capsys.readouterr().err
    assert code == 2
    assert "Не задан DATABASE_URL или DATABASE_URL_SYNC" in err
    assert "Traceback" not in err


def test_prod_database_error_exits_2_without_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "s3cret-not-a-url-fragment"
    monkeypatch.setenv(
        "DATABASE_URL_SYNC",
        f"postgresql://user:{secret}@db.railway.app:5432/railway",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)

    code = script.main([])

    captured = capsys.readouterr()
    assert code == 2
    assert "ОШИБКА" in captured.err
    assert "Traceback" not in captured.err
    assert secret not in captured.err
    assert secret not in captured.out
    assert "railway.app" not in captured.err
    assert "railway.app" not in captured.out


@pytest.mark.asyncio
async def test_past_reopen_date_is_refused_and_not_written(app_use_test_db, db_session, monkeypatch) -> None:
    city_id = await _insert_city(db_session, name=f"Силичевск {uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, city_id, name="Силичи")
    monkeypatch.setattr(
        script,
        "SPECS",
        (
            script.ArenaModeSpec(
                arena_id,
                script.SCHEDULE_MODE_SEASON_CLOSED,
                reopen_date=date(2026, 3, 25),
                note="закрыт с 25.03.2026",
            ),
        ),
    )

    with pytest.raises(script.ScheduleModeError, match="прошлом"):
        await script.plan_updates(db_session, today=TODAY)
    with pytest.raises(script.ScheduleModeError, match="прошлом"):
        await script.apply_updates(db_session, today=TODAY)

    row = (
        await db_session.execute(
            text(
                """
                SELECT schedule_mode, reopen_date, schedule_mode_note
                FROM arena_profiles WHERE arena_id = :id
                """
            ),
            {"id": arena_id},
        )
    ).one()
    assert row == ("auto", None, None)


@pytest.mark.asyncio
async def test_repeat_apply_reports_already_and_changes_nothing(
    app_use_test_db, db_session, monkeypatch
) -> None:
    city_id = await _insert_city(db_session, name=f"Режимск {uuid.uuid4().hex[:6]}")
    cloned: list[script.ArenaModeSpec] = []
    for spec in script.SPECS:
        arena_id = await _insert_arena(db_session, city_id, name=f"Каток {spec.arena_id}")
        cloned.append(
            script.ArenaModeSpec(arena_id, spec.mode, reopen_date=spec.reopen_date, note=spec.note)
        )
    monkeypatch.setattr(script, "SPECS", tuple(cloned))

    first = await script.execute(db_session, apply=True, today=TODAY)
    assert len(first) == 10
    assert all("->" in line for line in first)
    before = await _snapshot(db_session, [spec.arena_id for spec in cloned])

    second = await script.execute(db_session, apply=True, today=TODAY)
    after = await _snapshot(db_session, [spec.arena_id for spec in cloned])

    assert len(second) == 10
    assert all(": already " in line for line in second)
    assert before == after
    for arena_id, mode, reopen, note, _updated_at in after:
        spec = next(item for item in cloned if item.arena_id == arena_id)
        assert mode == spec.mode
        assert reopen is None
        assert note == spec.note


async def _snapshot(db_session, arena_ids: list[int]) -> list[tuple]:
    rows = []
    for arena_id in sorted(arena_ids):
        row = (
            await db_session.execute(
                text(
                    """
                    SELECT arena_id, schedule_mode, reopen_date, schedule_mode_note, updated_at
                    FROM arena_profiles
                    WHERE arena_id = :id
                    """
                ),
                {"id": arena_id},
            )
        ).one()
        rows.append(tuple(row))
    return rows
