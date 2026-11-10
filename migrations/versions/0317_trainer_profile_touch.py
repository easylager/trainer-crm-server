"""trainer_profiles.updated_at moves when services, prices, passes or rinks of a trainer change.

The catalog sitemap needs a real "page content changed" stamp per trainer. Only the profile and
pass products carry ``updated_at``; ``trainer_services``, ``trainer_service_price_variants`` and
``trainer_arenas`` are rewritten in place (DELETE + INSERT) and keep no time at all, so a removed
service or a new price never reached ``lastmod``.

One trigger on the four tables keeps the profile stamp honest for every write path (Mini App,
bot, quick setup, admin, raw SQL). It does nothing for changes nobody sees on the site
(``ui_accent``, ``client_notice``, bookkeeping ``updated_at``), and ``updated_at < now()`` makes
the rewrite of a whole service list one update per transaction, not one per row.

Backfill: pass products already carry a stamp — the profile takes the freshest of them, never a
date in the future.

Revision ID: 0317_trainer_profile_touch
Revises: 0316_spb_rink_cards_batch3
"""

from __future__ import annotations

from alembic import op

revision = "0317_trainer_profile_touch"
down_revision = "0316_spb_rink_cards_batch3"
branch_labels = None
depends_on = None

_TABLES = (
    "trainer_services",
    "trainer_service_price_variants",
    "trainer_arenas",
    "trainer_pass_products",
)


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION trainer_profile_touch() RETURNS trigger AS $$
        DECLARE
            tid integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                tid := OLD.trainer_id;
            ELSE
                tid := NEW.trainer_id;
                IF TG_OP = 'UPDATE'
                   AND (to_jsonb(NEW) - ARRAY['ui_accent', 'client_notice', 'updated_at'])
                       IS NOT DISTINCT FROM
                       (to_jsonb(OLD) - ARRAY['ui_accent', 'client_notice', 'updated_at']) THEN
                    RETURN NULL;
                END IF;
            END IF;
            UPDATE trainer_profiles SET updated_at = now() WHERE trainer_id = tid AND (updated_at IS NULL OR updated_at < now());
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """)
    for table in _TABLES:
        op.execute(f"""
            CREATE TRIGGER trg_{table}_touch_profile
            AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION trainer_profile_touch();
            """)
    op.execute("""
        UPDATE trainer_profiles p
        SET updated_at = LEAST(now(), x.stamp)
        FROM (
            SELECT trainer_id, MAX(updated_at) AS stamp FROM trainer_pass_products GROUP BY trainer_id
        ) x
        WHERE x.trainer_id = p.trainer_id AND (p.updated_at IS NULL OR x.stamp > p.updated_at)
        """)


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_touch_profile ON {table}")
    op.execute("DROP FUNCTION IF EXISTS trainer_profile_touch()")
