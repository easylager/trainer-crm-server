"""
Migration 0206 backfill: the one irreversible step of TASK-140.

It maps six legacy shapes of ``(status, is_catalog_visible, moderation_submitted_at,
moderation_feedback)`` onto the new ``catalog_state``. The property that matters is that the set
of publicly visible trainers is identical before and after — anything else is a silent outage
for whoever was in the catalog at deploy time.

The CASE expression is read out of the migration file rather than retyped, so this test cannot
drift away from the statement that will actually run.
"""
import pathlib
import re

import pytest
from sqlalchemy import text

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "0206_trainer_catalog_state.py"
)

# Legacy shape → expected state. Mirrors the table in the design doc.
LEGACY_SHAPES = [
    # (status, visible, submitted_at, feedback, expected_state)
    ("active", True, None, None, "published"),
    ("active", False, None, None, "hidden"),
    ("pending_profile", True, "now()", None, "pending_review"),
    ("pending_profile", True, "now()", "Добавьте фото", "needs_revision"),
    ("pending_profile", False, None, None, "draft"),
    ("pending_contract", False, None, None, "draft"),
    ("deactivated", True, None, None, "draft"),
]


def _backfill_case_expression() -> str:
    """Extract the CASE ... END that the migration assigns to catalog_state."""
    src = MIGRATION.read_text(encoding="utf-8")
    # \bEND\b matters: with IGNORECASE a bare "END" also matches the "end" inside
    # "pending_review", which truncates the expression mid-literal.
    m = re.search(r"catalog_state\s*=\s*(CASE\b.*?\bEND\b)", src, re.IGNORECASE | re.DOTALL)
    assert m, "migration 0206 no longer assigns catalog_state with a CASE expression"
    return m.group(1)


@pytest.mark.asyncio
async def test_backfill_maps_every_legacy_shape(db_session) -> None:
    case_sql = _backfill_case_expression()
    for status, visible, submitted, feedback, expected in LEGACY_SHAPES:
        r = await db_session.execute(
            text(
                "INSERT INTO trainers (status, is_catalog_visible, moderation_submitted_at, "
                f"moderation_feedback) VALUES (:s, :v, {submitted or 'NULL'}, :fb) RETURNING id"
            ),
            {"s": status, "v": visible, "fb": feedback},
        )
        (tid,) = r.fetchone()
        got = await db_session.execute(
            text(f"SELECT {case_sql} FROM trainers WHERE id = :tid"), {"tid": tid}
        )
        assert got.scalar() == expected, (
            f"status={status} visible={visible} submitted={bool(submitted)} "
            f"feedback={bool(feedback)} should backfill to {expected}"
        )


@pytest.mark.asyncio
async def test_backfill_preserves_exactly_who_is_in_the_catalog(db_session) -> None:
    """
    Old predicate ⟺ new predicate, over the same rows.

    This is the assertion that would have caught a backfill typo before it emptied the catalog.
    """
    case_sql = _backfill_case_expression()
    for status, visible, submitted, feedback, _ in LEGACY_SHAPES:
        await db_session.execute(
            text(
                "INSERT INTO trainers (status, is_catalog_visible, moderation_submitted_at, "
                f"moderation_feedback) VALUES (:s, :v, {submitted or 'NULL'}, :fb)"
            ),
            {"s": status, "v": visible, "fb": feedback},
        )
    mismatch = await db_session.execute(
        text(
            f"""
            SELECT count(*) FROM trainers
            WHERE (status = 'active' AND is_catalog_visible = true)
                IS DISTINCT FROM (({case_sql}) = 'published')
            """
        )
    )
    assert mismatch.scalar() == 0


@pytest.mark.asyncio
async def test_active_but_hidden_backfills_to_hidden_not_draft(db_session) -> None:
    """
    ``active`` is only reachable through an admin approval, so such a card has been reviewed.

    Backfilling it to ``hidden`` (not ``draft``) is what gives the trainer a one-tap return with
    no second review — the difference is invisible in the data and very visible in the product.
    """
    case_sql = _backfill_case_expression()
    r = await db_session.execute(
        text(
            "INSERT INTO trainers (status, is_catalog_visible) VALUES ('active', false) "
            "RETURNING id"
        )
    )
    (tid,) = r.fetchone()
    got = await db_session.execute(
        text(f"SELECT {case_sql} FROM trainers WHERE id = :tid"), {"tid": tid}
    )
    assert got.scalar() == "hidden"


def test_migration_creates_the_journal_and_its_index() -> None:
    src = MIGRATION.read_text(encoding="utf-8")
    assert "trainer_catalog_events" in src
    assert "ix_trainer_catalog_events_trainer" in src
    # A first event per trainer, so the history screen is never blank for existing accounts.
    assert "INSERT INTO trainer_catalog_events" in src
    assert "backfill_0206" in src
