"""Contract checks for the 0211 ice source-state backfill SQL.

The shared test database is intentionally not needed here: these checks keep the
decision points in the migration visible without running Alembic or touching data.
"""
import pathlib
import re


MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "0211_ice_source_state.py"
)


def _migration_sql() -> list[str]:
    source = MIGRATION.read_text(encoding="utf-8")
    return re.findall(r'op\.execute\(\s*"""(.*?)"""\s*\)', source, re.DOTALL)


def _failure_backfill_sql() -> str:
    statements = _migration_sql()
    assert len(statements) >= 2, "0211 must keep both freshness and failure backfills"
    return re.sub(r"\s+", " ", statements[1]).strip().lower()


def test_empty_run_with_visible_parser_sessions_is_a_failure() -> None:
    sql = _failure_backfill_sql()

    assert "when r.status = 'empty' and coalesce(v.shown_sessions, 0) > 0 then true" in sql
    assert "s.status = 'active'" in sql
    assert "s.kind in ('public_skate', 'open_ice')" in sql
    assert "s.starts_at_utc > now()" in sql
    assert "s.valid_until >= now()" in sql
    assert "s.source_id <> 'admin'" in sql
    assert "s.source_id not like 'etalon_%'" in sql


def test_empty_run_without_visible_parser_sessions_resets_prior_errors() -> None:
    sql = _failure_backfill_sql()

    assert "else false end as is_failure" in sql
    assert "where not is_failure" in sql
    assert "from classified_runs" in sql


def test_failures_after_an_empty_reset_form_a_new_streak() -> None:
    sql = _failure_backfill_sql()

    assert "last_reset" in sql
    assert "where run.is_failure" in sql
    assert "(run.finished_at, run.id) > (reset.finished_at, reset.id)" in sql
    assert "min(finished_at) as first_fail" in sql
    assert "count(*)::int as n" in sql
    assert "last_ok_at" not in sql


def test_last_ok_freshness_backfill_stays_based_on_latest_success() -> None:
    statements = _migration_sql()
    assert statements, "0211 must retain its last-ok freshness backfill"
    freshness_sql = re.sub(r"\s+", " ", statements[0]).strip().lower()

    assert "where status = 'ok'" in freshness_sql
    assert "order by job_id, finished_at desc, id desc" in freshness_sql
    assert "last_ok_at = ok.finished_at" in freshness_sql
