"""Fix cities and arenas ID sequences (set to MAX(id) to avoid duplicate key on insert)."""

from alembic import op


revision = "0054_fix_cities_arenas_sequences"
down_revision = "0053_cities_arenas_is_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # After seed/migration data with explicit ids, sequences can stay at 1 and cause UniqueViolation.
    op.execute(
        "SELECT setval(pg_get_serial_sequence('cities', 'id'), COALESCE((SELECT MAX(id) FROM cities), 1))"
    )
    op.execute(
        "SELECT setval(pg_get_serial_sequence('arenas', 'id'), COALESCE((SELECT MAX(id) FROM arenas), 1))"
    )


def downgrade() -> None:
    pass  # No safe way to revert sequence to previous value
