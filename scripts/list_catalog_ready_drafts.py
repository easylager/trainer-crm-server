"""Dry-run: trainers stuck in ``catalog_state='draft'`` whose card already passes the
minimal submission tier (publish-first, TASK: «Отправить себя в каталог»).

Before publish-first a trainer could fill everything and still sit outside the catalog —
the old checklist demanded a copied client link and a phone that were never real
publication blockers. This report shows how many of those «ready but stuck» drafts exist
and who they are, so we can decide how to invite them (e.g. show the
«Отправить себя в каталог» screen at next login) — NOT mass-publish them: a catalog card
is the trainer's public presence, publishing without their tap presumes consent we
don't have.

Read-only: everything runs inside one READ ONLY transaction; there is no --apply.

Usage (prod, values from Railway, never committed):
  DATABASE_URL=<DATABASE_PUBLIC_URL> PYTHONPATH=. python scripts/list_catalog_ready_drafts.py --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from src.shared.ops_db_guard import (  # noqa: E402
    add_i_know_this_is_prod_argument,
    assert_database_url,
    async_database_url,
    warn_prod_ack,
)

# Same minimal submission tier as SUBMIT_OPTIONAL_PROFILE_FIELD_KEYS semantics in
# trainer_profile_completeness.analyze_moderation_submission_readiness:
# first name, city, >=1 service, >=1 place of work (primary arena, own arena row,
# or non-venue work format like online/mobile).
READY_SQL = text(
    """
    SELECT
        t.id,
        p.first_name,
        c.name AS city_name,
        (SELECT COUNT(*) FROM trainer_services ts WHERE ts.trainer_id = t.id)::int AS services_count,
        (SELECT COUNT(*) FROM slots s WHERE s.trainer_id = t.id)::int AS slots_count,
        (t.client_invite_link_first_copied_at IS NOT NULL) AS link_copied,
        NULLIF(TRIM(p.phone), '') IS NOT NULL AS has_phone
    FROM trainers t
    JOIN trainer_profiles p ON p.trainer_id = t.id
    LEFT JOIN cities c ON c.id = p.city_id
    WHERE t.status <> 'deactivated'
      AND t.telegram_id IS NOT NULL
      AND COALESCE(t.catalog_state, 'draft') = 'draft'
      AND TRIM(COALESCE(p.first_name, '')) <> ''
      AND p.city_id IS NOT NULL
      AND EXISTS (SELECT 1 FROM trainer_services ts WHERE ts.trainer_id = t.id)
      AND (
          t.primary_arena_id IS NOT NULL
          OR t.arena_work_format IS NOT NULL
          OR EXISTS (SELECT 1 FROM trainer_arenas ta WHERE ta.trainer_id = t.id)
      )
    ORDER BY t.created_at DESC
    """
)

# The not-quite-ready drafts: one row per missing criterion (for the report tail).
STUCK_SQL = text(
    """
    SELECT
        COUNT(*) FILTER (
            WHERE TRIM(COALESCE(p.first_name, '')) = ''
        )::int AS no_name,
        COUNT(*) FILTER (
            WHERE TRIM(COALESCE(p.first_name, '')) <> '' AND p.city_id IS NULL
        )::int AS no_city,
        COUNT(*) FILTER (
            WHERE TRIM(COALESCE(p.first_name, '')) <> '' AND p.city_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM trainer_services ts WHERE ts.trainer_id = t.id)
        )::int AS no_services,
        COUNT(*) FILTER (
            WHERE TRIM(COALESCE(p.first_name, '')) <> '' AND p.city_id IS NOT NULL
              AND EXISTS (SELECT 1 FROM trainer_services ts WHERE ts.trainer_id = t.id)
              AND t.primary_arena_id IS NULL
              AND t.arena_work_format IS NULL
              AND NOT EXISTS (SELECT 1 FROM trainer_arenas ta WHERE ta.trainer_id = t.id)
        )::int AS no_place
    FROM trainers t
    JOIN trainer_profiles p ON p.trainer_id = t.id
    WHERE t.status <> 'deactivated'
      AND t.telegram_id IS NOT NULL
      AND COALESCE(t.catalog_state, 'draft') = 'draft'
    """
)


async def _run(url: str) -> int:
    engine = create_async_engine(async_database_url(url), pool_pre_ping=True)
    try:
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            ready = (await session.execute(READY_SQL)).mappings().all()
            stuck = (await session.execute(STUCK_SQL)).mappings().one()
    finally:
        await engine.dispose()

    print(f"Ready-but-stuck drafts: {len(ready)}")
    with_phone = sum(1 for r in ready if r["has_phone"])
    with_link = sum(1 for r in ready if r["link_copied"])
    print(f"  of them without phone: {len(ready) - with_phone}")
    print(f"  of them who never copied the client link: {len(ready) - with_link}")
    print()
    for r in ready[:50]:
        name = (r["first_name"] or "—").strip()
        print(
            f"  #{r['id']:<5} {name:<20} {r['city_name'] or '—':<18} "
            f"services={r['services_count']} slots={r['slots_count']} "
            f"phone={'yes' if r['has_phone'] else 'no'} link={'copied' if r['link_copied'] else 'never'}"
        )
    if len(ready) > 50:
        print(f"  … and {len(ready) - 50} more")
    print()
    print(
        "Still-blocked drafts (missing a real blocker): "
        f"no_name={stuck['no_name']} no_city={stuck['no_city']} "
        f"no_services={stuck['no_services']} no_place={stuck['no_place']}"
    )
    print()
    print("Next step suggestion: show these trainers the «Отправить себя в каталог» screen")
    print("at next login (trainer_dashboard next-step invite already covers drafts) rather")
    print("than publishing on their behalf — a public card needs the trainer's own tap.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()

    url = args.database_url or os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set DATABASE_URL_SYNC or DATABASE_URL")
    assert_database_url(url, apply=False, allow_prod=args.i_know_this_is_prod)
    if args.i_know_this_is_prod:
        warn_prod_ack()
    return asyncio.run(_run(url))


if __name__ == "__main__":
    raise SystemExit(main())
