"""trainer_cities: multi-city catalog membership (TASK-058).

trainer_profiles.city_id stays as the primary city. Catalog filters via
EXISTS trainer_cities. Backfill from profile city_id and from public arena cities.

EDGE-001: no profile city and no arenas → no trainer_cities rows (not a dummy city).
EDGE-002: partial unique index — at most one is_primary per trainer.

Revision ID: 0197_trainer_cities
Revises: 0196_ice_parser_jobs
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0197_trainer_cities"
down_revision = "0196_ice_parser_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_cities",
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("trainer_id", "city_id", name="uq_trainer_cities_trainer_city"),
    )
    op.create_index("ix_trainer_cities_city_id", "trainer_cities", ["city_id"])
    op.create_index(
        "uq_trainer_cities_one_primary",
        "trainer_cities",
        ["trainer_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION trainer_cities_add(
            p_trainer_id integer, p_city_id integer, p_primary boolean
        ) RETURNS void AS $$
        BEGIN
            IF p_city_id IS NULL THEN
                RETURN;
            END IF;
            IF p_primary THEN
                UPDATE trainer_cities
                SET is_primary = false
                WHERE trainer_id = p_trainer_id
                  AND is_primary
                  AND city_id IS DISTINCT FROM p_city_id;
            END IF;
            INSERT INTO trainer_cities (trainer_id, city_id, is_primary)
            VALUES (p_trainer_id, p_city_id, p_primary)
            ON CONFLICT (trainer_id, city_id) DO UPDATE
            SET is_primary = trainer_cities.is_primary OR EXCLUDED.is_primary;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trainer_cities_maybe_drop(
            p_trainer_id integer, p_city_id integer
        ) RETURNS void AS $$
        BEGIN
            IF p_city_id IS NULL THEN
                RETURN;
            END IF;
            IF EXISTS (
                SELECT 1 FROM trainer_profiles
                WHERE trainer_id = p_trainer_id AND city_id = p_city_id
            ) THEN
                RETURN;
            END IF;
            IF EXISTS (
                SELECT 1
                FROM trainer_arenas ta
                JOIN arenas a ON a.id = ta.arena_id
                WHERE ta.trainer_id = p_trainer_id
                  AND a.city_id = p_city_id
                  AND ta.is_public
            ) THEN
                RETURN;
            END IF;
            DELETE FROM trainer_cities
            WHERE trainer_id = p_trainer_id AND city_id = p_city_id;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_trainer_cities_profile() RETURNS trigger AS $$
        BEGIN
            IF NEW.city_id IS NOT NULL THEN
                PERFORM trainer_cities_add(NEW.trainer_id, NEW.city_id, true);
            END IF;
            IF TG_OP = 'UPDATE'
               AND OLD.city_id IS NOT NULL
               AND OLD.city_id IS DISTINCT FROM NEW.city_id THEN
                PERFORM trainer_cities_maybe_drop(NEW.trainer_id, OLD.city_id);
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_trainer_cities_arena() RETURNS trigger AS $$
        DECLARE
            cid integer;
            tid integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                tid := OLD.trainer_id;
                SELECT city_id INTO cid FROM arenas WHERE id = OLD.arena_id;
                IF OLD.is_public THEN
                    PERFORM trainer_cities_maybe_drop(tid, cid);
                END IF;
                RETURN OLD;
            END IF;
            tid := NEW.trainer_id;
            SELECT city_id INTO cid FROM arenas WHERE id = NEW.arena_id;
            IF TG_OP = 'INSERT' THEN
                IF NEW.is_public THEN
                    PERFORM trainer_cities_add(tid, cid, false);
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.is_public AND NOT OLD.is_public THEN
                PERFORM trainer_cities_add(tid, cid, false);
            ELSIF OLD.is_public AND NOT NEW.is_public THEN
                PERFORM trainer_cities_maybe_drop(tid, cid);
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_trainer_cities_profile
        AFTER INSERT OR UPDATE OF city_id ON trainer_profiles
        FOR EACH ROW
        EXECUTE FUNCTION trg_trainer_cities_profile()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_trainer_cities_arenas
        AFTER INSERT OR DELETE OR UPDATE OF is_public ON trainer_arenas
        FOR EACH ROW
        EXECUTE FUNCTION trg_trainer_cities_arena()
        """
    )

    op.execute(
        """
        INSERT INTO trainer_cities (trainer_id, city_id, is_primary)
        SELECT trainer_id, city_id, true
        FROM trainer_profiles
        WHERE city_id IS NOT NULL
        ON CONFLICT (trainer_id, city_id) DO UPDATE
        SET is_primary = true
        """
    )
    op.execute(
        """
        INSERT INTO trainer_cities (trainer_id, city_id, is_primary)
        SELECT DISTINCT ta.trainer_id, a.city_id, false
        FROM trainer_arenas ta
        JOIN arenas a ON a.id = ta.arena_id
        WHERE ta.is_public = true
        ON CONFLICT (trainer_id, city_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_trainer_cities_arenas ON trainer_arenas")
    op.execute("DROP TRIGGER IF EXISTS trg_trainer_cities_profile ON trainer_profiles")
    op.execute("DROP FUNCTION IF EXISTS trg_trainer_cities_arena()")
    op.execute("DROP FUNCTION IF EXISTS trg_trainer_cities_profile()")
    op.execute("DROP FUNCTION IF EXISTS trainer_cities_maybe_drop(integer, integer)")
    op.execute("DROP FUNCTION IF EXISTS trainer_cities_add(integer, integer, boolean)")
    op.drop_index("uq_trainer_cities_one_primary", table_name="trainer_cities")
    op.drop_index("ix_trainer_cities_city_id", table_name="trainer_cities")
    op.drop_table("trainer_cities")
